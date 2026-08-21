"""Encode, verify, atomically publish, and clean a completed media job."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace as dataclass_replace
from decimal import Decimal
from pathlib import Path

from loguru import logger

from ai_video_tools.core.models import JobPlan, MediaProbe, OverwriteMode, PipelineStage, ProgressEvent, Toolchain, VideoStream
from ai_video_tools.services.media_preparation import PreparationResult
from ai_video_tools.services.upscaling import UpscalingResult
from ai_video_tools.storage.naming import OutputCollisionError
from ai_video_tools.storage.publication import AtomicOutputPublisher, PartialOutput, PublicationError
from ai_video_tools.storage.workspaces import OwnedWorkspace, WorkspaceError, WorkspaceManager
from ai_video_tools.system.processes import CancellationToken, ProcessCancelled, ProcessError, ProcessResult, ProcessRunner
from ai_video_tools.video.compatibility import assess_frame_timing
from ai_video_tools.video.finalization import FinalAudioMode, FinalEncodingPlan, build_final_encoding_plan
from ai_video_tools.video.frames import FrameInventoryError, FrameInventoryVerifier
from ai_video_tools.video.probe import MediaProber, ProbeError

ProgressCallback = Callable[[ProgressEvent], None]
DEFAULT_FINAL_ENCODING_TIMEOUT_SECONDS = 24 * 60 * 60


class FinalOutputVerificationError(RuntimeError):
    """The encoded partial MP4 does not satisfy the final media contract."""


class FinalizationFailed(RuntimeError):
    """A terminal stage failed, preserving the workspace for diagnosis."""

    def __init__(self, message: str, workspace_path: Path, stage: PipelineStage, diagnostic_tail: str = "") -> None:
        super().__init__(message)
        self.workspace_path = workspace_path
        self.stage = stage
        self.diagnostic_tail = diagnostic_tail


class FinalizationCancelled(RuntimeError):
    """Final encoding was cancelled and owned temporary state was cleaned."""

    def __init__(self, message: str, workspace_path: Path, stage: PipelineStage) -> None:
        super().__init__(message)
        self.workspace_path = workspace_path
        self.stage = stage


@dataclass(frozen=True)
class FinalizationResult:
    """Published output facts retained after successful workspace cleanup."""

    output_path: Path
    output_probe: MediaProbe
    audio_mode: FinalAudioMode
    process_result: ProcessResult
    workspace_identifier: str


class FinalOutputVerifier:
    """Probe final H.264/MP4 output before it can replace the destination."""

    def __init__(self, prober: MediaProber) -> None:
        self._prober = prober

    @staticmethod
    def _verify_video(probe: MediaProbe, job: JobPlan, expected_duration: Decimal, failures: list[str]) -> VideoStream | None:
        video = probe.primary_video
        if video is None:
            failures.append("final output has no video stream")
            return None
        if len(probe.video_streams) != 1:
            failures.append("final output must contain exactly one video stream")
        if video.codec_name != "h264" or video.pixel_format != "yuv420p":
            failures.append("final video is not H.264 yuv420p")
        if (video.width, video.height) != (job.output_width, job.output_height):
            failures.append("final video dimensions differ from the frozen output size")
        timing = assess_frame_timing(video, job.output_frame_rate)
        logger.debug("Final frame timing {}", timing.diagnostic())
        if not timing.accepted:
            failures.append(f"final video frame timing mismatch ({timing.diagnostic()})")
        if video.rotation:
            failures.append("final video contains unsupported rotation metadata")
        expected_color = (job.output_color_profile.matrix.value, job.output_color_profile.transfer, job.output_color_profile.primaries)
        if (video.color_space, video.color_transfer, video.color_primaries) != expected_color or video.color_range not in {"tv", "limited"}:
            failures.append("final video differs from the frozen limited-range SDR color profile")
        frame_duration = Decimal(job.output_frame_rate.denominator) / Decimal(job.output_frame_rate.numerator)
        if video.duration is None or abs(video.duration - expected_duration) > max(Decimal("0.05"), frame_duration):
            failures.append("final video duration differs from the authoritative frame timeline")
        return video

    @staticmethod
    def _verify_audio(probe: MediaProbe, job: JobPlan, plan: FinalEncodingPlan, video: VideoStream | None, failures: list[str]) -> None:
        audio = probe.primary_audio
        if plan.audio_mode is FinalAudioMode.NONE:
            if probe.audio_streams:
                failures.append("final output unexpectedly contains audio")
            return
        if audio is None:
            failures.append("final output is missing expected audio")
            return
        if len(probe.audio_streams) != 1:
            failures.append("final output must contain exactly one audio stream")
        if audio.codec_name != plan.expected_audio_codec:
            failures.append(f"final audio codec is {audio.codec_name}, expected {plan.expected_audio_codec}")
        if plan.audio_mode is FinalAudioMode.AAC and audio.sample_rate != 48000:
            failures.append("encoded final audio is not 48 kHz AAC-LC")
        effective_layout = audio.channel_layout or {1: "mono", 2: "stereo"}.get(audio.channels)
        if effective_layout != job.output_audio_layout:
            failures.append("final audio layout differs from the frozen job layout")
        video_duration = video.duration if video is not None and video.duration is not None else probe.duration
        if video_duration is None or audio.duration is None or abs(video_duration - audio.duration) > Decimal("0.08"):
            failures.append("final audio and video durations are not aligned")

    def verify(self, path: Path, job: JobPlan, plan: FinalEncodingPlan) -> MediaProbe:
        """Return typed output facts only when every publication gate passes."""

        if not path.is_file() or path.is_symlink() or path.stat().st_size <= 0:
            raise FinalOutputVerificationError(f"final partial output is missing, unsafe, or empty: {path}")
        probe = self._prober.probe(path)
        failures: list[str] = []
        video = self._verify_video(probe, job, plan.duration, failures)
        self._verify_audio(probe, job, plan, video, failures)
        if probe.other_streams or probe.chapter_count:
            failures.append("final output contains unsupported secondary data")
        if failures:
            raise FinalOutputVerificationError("; ".join(failures))
        return probe


class FinalizationExecutor:
    """Own terminal encode, verification, publication, and workspace cleanup."""

    def __init__(self, workspace_manager: WorkspaceManager, process_runner: ProcessRunner, verifier: FinalOutputVerifier, *, publisher: AtomicOutputPublisher | None = None, frame_verifier: FrameInventoryVerifier | None = None, command_timeout_seconds: float = DEFAULT_FINAL_ENCODING_TIMEOUT_SECONDS) -> None:
        if command_timeout_seconds <= 0:
            raise ValueError("final encoding timeout must be positive")
        self._workspace_manager = workspace_manager
        self._process_runner = process_runner
        self._verifier = verifier
        self._publisher = publisher or AtomicOutputPublisher()
        self._frame_verifier = frame_verifier or FrameInventoryVerifier()
        self._command_timeout_seconds = command_timeout_seconds

    @staticmethod
    def _emit(callback: ProgressCallback | None, stage: PipelineStage, completed: int, total: int, message: str) -> None:
        if callback is not None:
            callback(ProgressEvent(stage, completed, total, message))

    def _discard_partial(self, partial: PartialOutput | None) -> None:
        if partial is not None and partial.path.exists():
            self._publisher.discard(partial)

    def _cleanup_workspace(self, workspace: OwnedWorkspace, progress: ProgressCallback | None) -> None:
        self._emit(progress, PipelineStage.CLEANUP, 0, 1, "Cleaning the completed job workspace")
        self._workspace_manager.cleanup(workspace)
        self._emit(progress, PipelineStage.CLEANUP, 1, 1, "Completed job workspace cleaned")

    def _validate_start(self, prepared: PreparationResult, upscaled: UpscalingResult, job: JobPlan, workspace: OwnedWorkspace) -> tuple[Path, bool]:
        workspace_path = self._workspace_manager.validate(workspace)
        if prepared.workspace_identifier != workspace.identifier or upscaled.workspace_identifier != workspace.identifier:
            raise ValueError("finalization inputs belong to a different workspace")
        self._frame_verifier.verify(upscaled.frames_directory, upscaled.frame_width, upscaled.frame_height, upscaled.frame_count)
        replace = not job.generated_output_name and job.overwrite_mode is OverwriteMode.REPLACE
        if not replace and job.output_path.exists():
            raise OutputCollisionError(f"destination already exists before encoding: {job.output_path}")
        return workspace_path, replace

    def execute(self, prepared: PreparationResult, upscaled: UpscalingResult, job: JobPlan, toolchain: Toolchain, *, workspace: OwnedWorkspace, cancellation: CancellationToken | None = None, progress: ProgressCallback | None = None) -> FinalizationResult:
        """Encode to a partial, verify, publish atomically, and clean terminal state."""

        token = cancellation or CancellationToken()
        partial: PartialOutput | None = None
        stage = PipelineStage.ENCODE
        try:
            workspace_path, replace = self._validate_start(prepared, upscaled, job, workspace)
            if token.cancelled:
                raise ProcessCancelled("finalization cancelled before encoding", ())
            partial = self._publisher.create_partial(job.output_path)
            plan = build_final_encoding_plan(job, toolchain.ffmpeg.path, prepared.merged_probe, workspace_path, partial.path, frames_directory=upscaled.frames_directory, frame_count=upscaled.frame_count, frame_width=upscaled.frame_width, frame_height=upscaled.frame_height, audio_source_path=upscaled.audio_source_path)
            self._emit(progress, stage, 0, upscaled.frame_count, f"Encoding {upscaled.frame_count} final video frames")
            process_result = self._process_runner.run(plan.command, token, self._command_timeout_seconds)
            if token.cancelled:
                raise ProcessCancelled("finalization cancelled after encoding", plan.command, process_result.stdout_tail, process_result.stderr_tail)
            self._emit(progress, stage, upscaled.frame_count, upscaled.frame_count, "Encoded the final MP4 partial")
            stage = PipelineStage.VERIFY
            self._emit(progress, stage, 0, 1, "Verifying the final MP4 partial")
            output_probe = self._verifier.verify(partial.path, job, plan)
            if token.cancelled:
                raise ProcessCancelled("finalization cancelled after verification", plan.command)
            self._emit(progress, stage, 1, 1, "Verified the final MP4 partial")
            stage = PipelineStage.PUBLISH
            self._emit(progress, stage, 0, 1, "Publishing the verified final output")
            output_path = self._publisher.publish(partial, replace=replace)
            output_probe = dataclass_replace(output_probe, path=output_path)
            partial = None
            self._emit(progress, stage, 1, 1, "Published the verified final output")
        except ProcessCancelled as error:
            try:
                self._discard_partial(partial)
                self._cleanup_workspace(workspace, progress)
            except (PublicationError, WorkspaceError) as cleanup_error:
                raise FinalizationFailed("Finalization was cancelled, but owned temporary state could not be cleaned.", workspace.path, PipelineStage.CLEANUP) from cleanup_error
            raise FinalizationCancelled("Finalization cancelled; child processes terminated, partial output removed, and workspace cleaned.", workspace.path, stage) from error
        except (FinalOutputVerificationError, FrameInventoryError, OutputCollisionError, ProcessError, ProbeError, PublicationError, WorkspaceError, OSError, ValueError) as error:
            try:
                self._discard_partial(partial)
            except PublicationError as discard_error:
                raise FinalizationFailed(f"Finalization failed during {stage.value}, and its partial output could not be removed: {partial.path if partial is not None else 'unknown'}", workspace.path, stage) from discard_error
            diagnostic = error.stderr_tail if isinstance(error, ProcessError) else ""
            raise FinalizationFailed(f"Finalization failed during {stage.value}: {error}. Workspace retained at {workspace.path}", workspace.path, stage, diagnostic) from error
        try:
            self._cleanup_workspace(workspace, progress)
        except WorkspaceError as error:
            raise FinalizationFailed(f"Output was published, but workspace cleanup failed: {error}", workspace.path, PipelineStage.CLEANUP) from error
        return FinalizationResult(output_path, output_probe, plan.audio_mode, process_result, workspace.identifier)
