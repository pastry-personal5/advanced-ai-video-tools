"""Execute and verify the normalize-then-concat preparation stage."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from loguru import logger

from advanced_ai_video_tools.core.models import ConcatStrategy, JobPlan, MediaProbe, PipelineStage, ProgressEvent, VideoStream
from advanced_ai_video_tools.storage.workspaces import OwnedWorkspace, WorkspaceError, WorkspaceManager
from advanced_ai_video_tools.system.processes import CancellationToken, ProcessCancelled, ProcessError, ProcessResult, ProcessRunner
from advanced_ai_video_tools.video.commands import MediaPreparationPlan, build_media_preparation_plan
from advanced_ai_video_tools.video.compatibility import assess_frame_timing
from advanced_ai_video_tools.video.manifest import write_concat_manifest
from advanced_ai_video_tools.video.probe import MediaProber, ProbeError

ProgressCallback = Callable[[ProgressEvent], None]
DEFAULT_COMMAND_TIMEOUT_SECONDS = 24 * 60 * 60


class MergedOutputVerificationError(RuntimeError):
    """The concat output does not match the frozen preparation contract."""


class PreparationFailed(RuntimeError):
    """Preparation failed and its owned workspace was retained for diagnosis."""

    def __init__(self, message: str, workspace_path: Path, stage: PipelineStage, diagnostic_tail: str = "") -> None:
        super().__init__(message)
        self.workspace_path = workspace_path
        self.stage = stage
        self.diagnostic_tail = diagnostic_tail


class PreparationCancelled(RuntimeError):
    """Preparation was cancelled after terminating its active child process."""

    def __init__(self, message: str, workspace_path: Path, stage: PipelineStage) -> None:
        super().__init__(message)
        self.workspace_path = workspace_path
        self.stage = stage


@dataclass(frozen=True)
class PreparationResult:
    """Verified merged facts whose artifact lifetime belongs to the caller."""

    merged_probe: MediaProbe
    normalization_count: int
    process_results: tuple[ProcessResult, ...]
    workspace_identifier: str


class MergedOutputVerifier:
    """Probe and validate the concat result against its frozen job plan."""

    def __init__(self, prober: MediaProber) -> None:
        self._prober = prober

    @staticmethod
    def _source_duration(probe: MediaProbe) -> Decimal:
        video = probe.primary_video
        duration = video.duration if video is not None and video.duration is not None else probe.duration
        if duration is None or duration <= 0:
            raise MergedOutputVerificationError(f"source video duration is unavailable: {probe.path}")
        return duration

    def verify(self, path: Path, job: JobPlan, strategy: ConcatStrategy) -> MediaProbe:
        """Return the merged probe only when all expected stream facts match."""

        if not path.is_file() or path.stat().st_size <= 0:
            raise MergedOutputVerificationError(f"merged output is missing or empty: {path}")
        merged = self._prober.probe(path)
        failures: list[str] = []
        video = self._verify_video(merged, job, strategy, failures)
        self._verify_audio(merged, job, strategy, video, failures)
        if merged.other_streams or merged.chapter_count:
            failures.append("merged output contains unsupported secondary data")
        self._verify_duration(merged, job, video, failures)
        if failures:
            raise MergedOutputVerificationError("; ".join(failures))
        return merged

    @staticmethod
    def _verify_video(merged: MediaProbe, job: JobPlan, strategy: ConcatStrategy, failures: list[str]) -> VideoStream | None:
        video = merged.primary_video
        baseline_video = job.probes[0].primary_video if job.probes else None
        if video is None or baseline_video is None:
            failures.append("merged output has no primary video")
            return video
        if len(merged.video_streams) != 1:
            failures.append("merged output must contain exactly one video stream")
        if (video.width, video.height) != (baseline_video.width, baseline_video.height):
            failures.append("merged video dimensions differ from the normalization canvas")
        timing = assess_frame_timing(video, job.output_frame_rate)
        logger.debug("Merged frame timing {}", timing.diagnostic())
        if not timing.accepted:
            failures.append(f"merged video frame timing mismatch ({timing.diagnostic()})")
        if video.rotation:
            failures.append("merged video contains unsupported rotation metadata")
        expected_color = (job.output_color_profile.matrix.value, job.output_color_profile.transfer, job.output_color_profile.primaries)
        if (video.color_space, video.color_transfer, video.color_primaries) != expected_color or video.color_range not in {"tv", "limited"}:
            failures.append("merged video differs from the frozen limited-range SDR color profile")
        expected_codec = "ffv1" if strategy is ConcatStrategy.NORMALIZE else baseline_video.codec_name
        if video.codec_name != expected_codec:
            failures.append(f"merged video codec is {video.codec_name}, expected {expected_codec}")
        return video

    @staticmethod
    def _verify_audio(merged: MediaProbe, job: JobPlan, strategy: ConcatStrategy, video: VideoStream | None, failures: list[str]) -> None:
        expects_audio = job.output_audio_layout is not None
        audio = merged.primary_audio
        if expects_audio and audio is None:
            failures.append("merged output is missing its expected audio stream")
        if not expects_audio and merged.audio_streams:
            failures.append("merged output unexpectedly contains audio")
        if expects_audio and audio is not None:
            if len(merged.audio_streams) != 1:
                failures.append("merged output must contain exactly one audio stream")
            effective_layout = audio.channel_layout or {1: "mono", 2: "stereo"}.get(audio.channels)
            if effective_layout != job.output_audio_layout:
                failures.append("merged audio channel layout differs from the job layout")
            if strategy is ConcatStrategy.NORMALIZE and (audio.codec_name != "pcm_s24le" or audio.sample_rate != 48000):
                failures.append("normalized merged audio is not pcm_s24le at 48 kHz")
            video_duration = video.duration if video is not None and video.duration is not None else merged.duration
            if video_duration is None or audio.duration is None or abs(video_duration - audio.duration) > Decimal("0.05"):
                failures.append("merged audio and video durations are not aligned")

    def _verify_duration(self, merged: MediaProbe, job: JobPlan, video: VideoStream | None, failures: list[str]) -> None:
        expected_duration = sum((self._source_duration(probe) for probe in job.probes), Decimal(0))
        actual_duration = video.duration if video is not None and video.duration is not None else merged.duration
        frame_tolerance = Decimal(job.output_frame_rate.denominator) / Decimal(job.output_frame_rate.numerator) * 2
        duration_tolerance = max(Decimal("0.10"), frame_tolerance)
        if actual_duration is None or actual_duration <= 0 or abs(actual_duration - expected_duration) > duration_tolerance:
            failures.append(f"merged duration is implausible; expected approximately {expected_duration} seconds")


class MediaPreparationExecutor:
    """Own the preparation workspace and execute normalization before concat."""

    def __init__(self, workspace_manager: WorkspaceManager, process_runner: ProcessRunner, verifier: MergedOutputVerifier, command_timeout_seconds: float = DEFAULT_COMMAND_TIMEOUT_SECONDS) -> None:
        if command_timeout_seconds <= 0:
            raise ValueError("command timeout must be positive")
        self._workspace_manager = workspace_manager
        self._process_runner = process_runner
        self._verifier = verifier
        self._command_timeout_seconds = command_timeout_seconds

    @staticmethod
    def _emit(callback: ProgressCallback | None, stage: PipelineStage, completed: int, total: int | None, message: str) -> None:
        if callback is not None:
            callback(ProgressEvent(stage, completed, total, message))

    def _cleanup(self, workspace: OwnedWorkspace, callback: ProgressCallback | None) -> None:
        self._emit(callback, PipelineStage.CLEANUP, 0, 1, "Cleaning the preparation workspace")
        self._workspace_manager.cleanup(workspace)
        self._emit(callback, PipelineStage.CLEANUP, 1, 1, "Preparation workspace cleaned")

    def execute(self, job: JobPlan, ffmpeg: Path, cancellation: CancellationToken | None = None, progress: ProgressCallback | None = None) -> PreparationResult:
        """Run normalize-all-or-none, concat once, verify, then clean success."""

        token = cancellation or CancellationToken()
        workspace = self._workspace_manager.create()
        try:
            result = self.execute_in_workspace(job, ffmpeg, workspace, token, progress)
        except PreparationCancelled as error:
            try:
                self._cleanup(workspace, progress)
            except WorkspaceError as cleanup_error:
                raise PreparationFailed("Preparation was cancelled, but its workspace could not be cleaned.", workspace.path, PipelineStage.CLEANUP) from cleanup_error
            raise PreparationCancelled("Preparation cancelled; child processes terminated and workspace cleaned.", workspace.path, error.stage) from error
        try:
            self._cleanup(workspace, progress)
        except WorkspaceError as error:
            raise PreparationFailed(f"Preparation succeeded, but workspace cleanup failed: {error}", workspace.path, PipelineStage.CLEANUP) from error
        return result

    def execute_in_workspace(self, job: JobPlan, ffmpeg: Path, workspace: OwnedWorkspace, cancellation: CancellationToken | None = None, progress: ProgressCallback | None = None) -> PreparationResult:
        """Prepare media in a caller-owned workspace without cleaning it."""

        token = cancellation or CancellationToken()
        stage = PipelineStage.NORMALIZE
        results: list[ProcessResult] = []
        try:
            workspace_path = self._workspace_manager.validate(workspace)
            plan = build_media_preparation_plan(job, ffmpeg, workspace_path)
            self._prepare_directories(plan)
            normalization_total = len(plan.normalization_commands)
            if normalization_total == 0:
                self._emit(progress, PipelineStage.NORMALIZE, 0, 0, "Normalization is not required")
            else:
                self._emit(progress, PipelineStage.NORMALIZE, 0, normalization_total, "Starting lossless normalization")
                for index, command in enumerate(plan.normalization_commands, start=1):
                    results.append(self._process_runner.run(command, token, self._command_timeout_seconds))
                    self._emit(progress, PipelineStage.NORMALIZE, index, normalization_total, f"Normalized clip {index} of {normalization_total}")
            if token.cancelled:
                raise ProcessCancelled("preparation cancelled", ())
            write_concat_manifest(plan.concat_manifest_path, plan.concat_inputs)
            stage = PipelineStage.CONCATENATE
            self._emit(progress, stage, 0, 1, "Concatenating the prepared timeline")
            results.append(self._process_runner.run(plan.concat_command, token, self._command_timeout_seconds))
            self._emit(progress, stage, 1, 1, "Concatenated the prepared timeline")
            if token.cancelled:
                raise ProcessCancelled("preparation cancelled", ())
            stage = PipelineStage.VERIFY
            self._emit(progress, stage, 0, 1, "Verifying the merged timeline")
            merged_probe = self._verifier.verify(plan.merged_output_path, job, plan.compatibility.strategy)
            self._emit(progress, stage, 1, 1, "Verified the merged timeline")
        except ProcessCancelled as error:
            raise PreparationCancelled("Preparation cancelled; child processes terminated. The caller still owns the workspace.", workspace.path, stage) from error
        except (MergedOutputVerificationError, ProcessError, ProbeError, WorkspaceError, OSError, ValueError) as error:
            diagnostic = error.stderr_tail if isinstance(error, ProcessError) else ""
            raise PreparationFailed(f"Preparation failed during {stage.value}: {error}. Workspace retained at {workspace.path}", workspace.path, stage, diagnostic) from error
        return PreparationResult(merged_probe, len(plan.normalization_commands), tuple(results), workspace.identifier)

    @staticmethod
    def _prepare_directories(plan: MediaPreparationPlan) -> None:
        if plan.normalization_commands:
            normalized_parent = plan.concat_inputs[0].parent
            normalized_parent.mkdir(parents=True, exist_ok=False)
