"""Execute and verify exact-CFR RGB PNG extraction from prepared media."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ai_video_tools.core.models import JobPlan, PipelineStage, ProgressEvent
from ai_video_tools.services.media_preparation import PreparationResult
from ai_video_tools.storage.workspaces import OwnedWorkspace, WorkspaceError, WorkspaceManager
from ai_video_tools.system.processes import CancellationToken, ProcessCancelled, ProcessError, ProcessResult, ProcessRunner
from ai_video_tools.video.commands import build_frame_extraction_plan
from ai_video_tools.video.frames import FrameInventoryError, FrameInventoryVerifier

ProgressCallback = Callable[[ProgressEvent], None]
DEFAULT_EXTRACTION_TIMEOUT_SECONDS = 24 * 60 * 60


class FrameExtractionFailed(RuntimeError):
    """Frame extraction failed and the caller-owned workspace was retained."""

    def __init__(self, message: str, workspace_path: Path, diagnostic_tail: str = "") -> None:
        super().__init__(message)
        self.workspace_path = workspace_path
        self.stage = PipelineStage.EXTRACT
        self.diagnostic_tail = diagnostic_tail


class FrameExtractionCancelled(RuntimeError):
    """Frame extraction was cancelled with cleanup left to the job owner."""

    def __init__(self, message: str, workspace_path: Path) -> None:
        super().__init__(message)
        self.workspace_path = workspace_path
        self.stage = PipelineStage.EXTRACT


@dataclass(frozen=True)
class FrameExtractionResult:
    """Verified frame inventory and retained merged-audio source."""

    frames_directory: Path
    frame_pattern: Path
    frame_count: int
    expected_frame_count: int
    frame_width: int
    frame_height: int
    audio_source_path: Path | None
    process_result: ProcessResult
    workspace_identifier: str


class FrameExtractionExecutor:
    """Extract frames within a caller-owned workspace without cleaning it."""

    def __init__(self, workspace_manager: WorkspaceManager, process_runner: ProcessRunner, verifier: FrameInventoryVerifier | None = None, command_timeout_seconds: float = DEFAULT_EXTRACTION_TIMEOUT_SECONDS) -> None:
        if command_timeout_seconds <= 0:
            raise ValueError("frame extraction timeout must be positive")
        self._workspace_manager = workspace_manager
        self._process_runner = process_runner
        self._verifier = verifier or FrameInventoryVerifier()
        self._command_timeout_seconds = command_timeout_seconds

    @staticmethod
    def _emit(callback: ProgressCallback | None, completed: int, total: int | None, message: str) -> None:
        if callback is not None:
            callback(ProgressEvent(PipelineStage.EXTRACT, completed, total, message))

    def execute(self, prepared: PreparationResult, job: JobPlan, ffmpeg: Path, *, workspace: OwnedWorkspace, cancellation: CancellationToken | None = None, progress: ProgressCallback | None = None) -> FrameExtractionResult:
        """Extract and verify frames while retaining merged media for later muxing."""

        token = cancellation or CancellationToken()
        try:
            workspace_path = self._workspace_manager.validate(workspace)
            if prepared.workspace_identifier != workspace.identifier:
                raise ValueError("prepared media belongs to a different workspace")
            plan = build_frame_extraction_plan(job, ffmpeg, prepared.merged_probe, workspace_path)
            plan.frames_directory.mkdir(parents=False, exist_ok=False)
            self._emit(progress, 0, plan.expected_frame_count, f"Extracting approximately {plan.expected_frame_count} RGB frames")
            process_result = self._process_runner.run(plan.command, token, self._command_timeout_seconds)
            if token.cancelled:
                raise ProcessCancelled("frame extraction cancelled", plan.command)
            video = prepared.merged_probe.primary_video
            if video is None:
                raise FrameInventoryError("verified merged media lost its primary video")
            frame_count = self._verifier.verify(plan.frames_directory, video.width, video.height, plan.expected_frame_count, count_tolerance=1)
            self._emit(progress, frame_count, frame_count, f"Extracted and verified {frame_count} RGB frames")
        except ProcessCancelled as error:
            raise FrameExtractionCancelled("Frame extraction cancelled; child processes terminated. The caller still owns the workspace.", workspace.path) from error
        except (FrameInventoryError, ProcessError, WorkspaceError, OSError, ValueError) as error:
            diagnostic = error.stderr_tail if isinstance(error, ProcessError) else ""
            raise FrameExtractionFailed(f"Frame extraction failed: {error}. Workspace retained at {workspace.path}", workspace.path, diagnostic) from error
        return FrameExtractionResult(plan.frames_directory, plan.frame_pattern, frame_count, plan.expected_frame_count, video.width, video.height, plan.audio_source_path, process_result, workspace.identifier)
