"""Direct stream-copy concat, verification, publication, and cleanup."""

from __future__ import annotations

from dataclasses import replace

from advanced_ai_video_tools.core.models import ConcatStrategy, JobPlan, OverwriteMode, PipelineStage, Toolchain
from advanced_ai_video_tools.services.context import StageContext
from advanced_ai_video_tools.services.finalization import FinalizationCancelled, FinalizationFailed, FinalizationResult
from advanced_ai_video_tools.services.media_preparation import MergedOutputVerificationError, MergedOutputVerifier
from advanced_ai_video_tools.services.progress import ProgressCallback, ProgressEmitter
from advanced_ai_video_tools.storage.naming import OutputCollisionError
from advanced_ai_video_tools.storage.publication import AtomicOutputPublisher, PartialOutput, PublicationError
from advanced_ai_video_tools.storage.workspaces import OwnedWorkspace, WorkspaceError, WorkspaceManager
from advanced_ai_video_tools.system.processes import CancellationToken, ProcessCancelled, ProcessError, ProcessRunner
from advanced_ai_video_tools.video.commands import create_direct_concat_command
from advanced_ai_video_tools.video.finalization import FinalAudioMode
from advanced_ai_video_tools.video.manifest import write_concat_manifest

DEFAULT_CONCAT_TIMEOUT_SECONDS = 24 * 60 * 60
_QUICKTIME_FORMATS = frozenset({"mov", "mp4", "m4a", "3gp", "3g2", "mj2"})


class DirectConcatExecutor:
    """Publish a verified MP4/MOV without decoding or encoding its streams."""

    def __init__(self, workspace_manager: WorkspaceManager, process_runner: ProcessRunner, verifier: MergedOutputVerifier, *, publisher: AtomicOutputPublisher | None = None, command_timeout_seconds: float = DEFAULT_CONCAT_TIMEOUT_SECONDS) -> None:
        self._workspace_manager = workspace_manager
        self._process_runner = process_runner
        self._verifier = verifier
        self._publisher = publisher or AtomicOutputPublisher()
        self._command_timeout_seconds = command_timeout_seconds

    def _discard(self, partial: PartialOutput | None) -> None:
        if partial is not None and partial.path.exists():
            self._publisher.discard(partial)

    def execute(
        self,
        job: JobPlan,
        toolchain: Toolchain,
        *,
        workspace: OwnedWorkspace,
        cancellation: CancellationToken | None = None,
        progress: ProgressCallback | None = None,
        context: StageContext | None = None,
    ) -> FinalizationResult:
        """Run one direct concat command and atomically publish its verified result."""

        # The explicit stage sequence keeps cleanup and publication ownership visible.
        # pylint: disable=too-many-statements

        if context is not None:
            workspace = context.workspace
            cancellation = context.cancellation
            progress = context.progress
            toolchain = context.toolchain or toolchain
        token = cancellation or CancellationToken()
        partial: PartialOutput | None = None
        stage = PipelineStage.CONCATENATE
        try:
            workspace_path = self._workspace_manager.validate(workspace)
            if job.concat_strategy is not ConcatStrategy.STREAM_COPY or job.normalization_reasons:
                raise ValueError("concat-only execution requires an exact stream-copy plan")
            suffix = job.output_path.suffix.lower()
            if suffix not in {".mp4", ".mov"}:
                raise ValueError("concat-only destination must be MP4 or MOV")
            replace_existing = not job.generated_output_name and job.overwrite_mode is OverwriteMode.REPLACE
            if not replace_existing and job.output_path.exists():
                raise OutputCollisionError(f"destination already exists before concat: {job.output_path}")
            manifest = workspace_path / "concat.ffconcat"
            write_concat_manifest(manifest, tuple(probe.path for probe in job.probes))
            partial = self._publisher.create_partial(job.output_path)
            command = create_direct_concat_command(toolchain.ffmpeg.path, manifest, partial.path, has_audio=job.output_audio_layout is not None, suffix=suffix)
            ProgressEmitter.emit(progress, PipelineStage.NORMALIZE, 0, 0, "Concat only does not normalize or encode media")
            ProgressEmitter.emit(progress, stage, 0, 1, f"Stream-copying clips into {suffix.upper()[1:]}")
            process_result = self._process_runner.run(command, token, self._command_timeout_seconds)
            if token.cancelled:
                raise ProcessCancelled("concat-only processing cancelled", command, process_result.stdout_tail, process_result.stderr_tail)
            ProgressEmitter.emit(progress, stage, 1, 1, "Completed direct stream-copy concat")
            stage = PipelineStage.VERIFY
            ProgressEmitter.emit(progress, stage, 0, 1, "Verifying the stream-copied output")
            output_probe = self._verifier.verify(partial.path, job, ConcatStrategy.STREAM_COPY)
            if not _QUICKTIME_FORMATS.intersection(output_probe.format_names):
                raise MergedOutputVerificationError("stream-copied output is not QuickTime/ISO base media")
            baseline = job.probes[0].primary_video
            output_video = output_probe.primary_video
            if baseline is None or output_video is None or output_video.sample_aspect_ratio != baseline.sample_aspect_ratio:
                raise MergedOutputVerificationError("stream-copied output sample aspect ratio changed")
            ProgressEmitter.emit(progress, stage, 1, 1, "Verified the stream-copied output")
            stage = PipelineStage.PUBLISH
            ProgressEmitter.emit(progress, stage, 0, 1, "Publishing the verified stream-copy output")
            output_path = self._publisher.publish(partial, replace=replace_existing)
            output_probe = replace(output_probe, path=output_path)
            partial = None
            ProgressEmitter.emit(progress, stage, 1, 1, "Published the verified stream-copy output")
        except ProcessCancelled as error:
            try:
                self._discard(partial)
                self._workspace_manager.cleanup(workspace)
            except (PublicationError, WorkspaceError) as cleanup_error:
                raise FinalizationFailed("Concat was cancelled, but owned temporary state could not be cleaned.", workspace.path, PipelineStage.CLEANUP) from cleanup_error
            raise FinalizationCancelled("Concat cancelled; child process terminated, partial removed, and workspace cleaned.", workspace.path, stage) from error
        except (MergedOutputVerificationError, OutputCollisionError, ProcessError, PublicationError, WorkspaceError, OSError, ValueError) as error:
            try:
                self._discard(partial)
            except PublicationError as discard_error:
                raise FinalizationFailed("Concat failed and its partial output could not be removed.", workspace.path, stage) from discard_error
            diagnostic = error.stderr_tail if isinstance(error, ProcessError) else ""
            raise FinalizationFailed(f"Concat-only processing failed during {stage.value}: {error}. Workspace retained at {workspace.path}", workspace.path, stage, diagnostic) from error
        try:
            self._workspace_manager.cleanup(workspace)
        except WorkspaceError as error:
            raise FinalizationFailed(f"Output was published, but workspace cleanup failed: {error}", workspace.path, PipelineStage.CLEANUP) from error
        audio_mode = FinalAudioMode.COPY if job.output_audio_layout is not None else FinalAudioMode.NONE
        return FinalizationResult(output_path, output_probe, audio_mode, process_result, workspace.identifier)
