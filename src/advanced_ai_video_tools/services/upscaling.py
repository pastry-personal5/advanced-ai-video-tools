"""Cancellable Real-ESRGAN execution with bounded Vulkan-memory retries."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Thread

from advanced_ai_video_tools.core.models import JobPlan, PipelineStage, Toolchain
from advanced_ai_video_tools.services.frame_extraction import FrameExtractionResult
from advanced_ai_video_tools.services.progress import ProgressCallback, ProgressEmitter
from advanced_ai_video_tools.services.context import StageContext
from advanced_ai_video_tools.storage.workspaces import OwnedWorkspace, WorkspaceError, WorkspaceManager
from advanced_ai_video_tools.system.processes import CancellationToken, ProcessCancelled, ProcessError, ProcessExecutionError, ProcessResult, ProcessRunner
from advanced_ai_video_tools.upscaling.realesrgan import AUTOMATIC_TILE_SIZE, MEMORY_RETRY_TILE_SIZES, UpscalePlan, create_realesrgan_command, create_upscale_plan, is_vulkan_memory_failure
from advanced_ai_video_tools.video.frames import FRAME_FILENAME_TEMPLATE, FrameInventoryError, FrameInventoryVerifier

DEFAULT_UPSCALE_TIMEOUT_SECONDS = 24 * 60 * 60
UPSCALE_PROGRESS_POLL_SECONDS = 1.0
LIVE_PREVIEW_FRAME_INTERVAL = 16


@dataclass(frozen=True)
class UpscaleAttempt:
    """Bounded diagnostics for one automatic or fixed-tile invocation."""

    tile_size: int
    command: tuple[str, ...]
    returncode: int | None
    stdout_tail: str
    stderr_tail: str

    @property
    def succeeded(self) -> bool:
        """Whether the external process completed successfully."""

        return self.returncode == 0


class UpscalingFailed(RuntimeError):
    """Upscaling failed and the caller-owned workspace was retained."""

    def __init__(self, message: str, workspace_path: Path, attempts: Sequence[UpscaleAttempt] = (), diagnostic_tail: str = "") -> None:
        super().__init__(message)
        self.workspace_path = workspace_path
        self.stage = PipelineStage.UPSCALE
        self.attempts = tuple(attempts)
        self.diagnostic_tail = diagnostic_tail


class UpscalingCancelled(RuntimeError):
    """Upscaling was cancelled with cleanup left to the full-job owner."""

    def __init__(self, message: str, workspace_path: Path, attempts: Sequence[UpscaleAttempt] = ()) -> None:
        super().__init__(message)
        self.workspace_path = workspace_path
        self.stage = PipelineStage.UPSCALE
        self.attempts = tuple(attempts)


@dataclass(frozen=True)
class UpscalingResult:
    """Verified frames selected for final encoding and retained audio source."""

    frames_directory: Path
    frame_pattern: Path
    frame_count: int
    frame_width: int
    frame_height: int
    scale: int | None
    skipped: bool
    audio_source_path: Path | None
    attempts: tuple[UpscaleAttempt, ...]
    workspace_identifier: str


class UpscalingExecutor:
    """Run one directory upscale stage inside a caller-owned workspace."""

    def __init__(self, workspace_manager: WorkspaceManager, process_runner: ProcessRunner, verifier: FrameInventoryVerifier | None = None, command_timeout_seconds: float = DEFAULT_UPSCALE_TIMEOUT_SECONDS) -> None:
        if command_timeout_seconds <= 0:
            raise ValueError("upscale timeout must be positive")
        self._workspace_manager = workspace_manager
        self._process_runner = process_runner
        self._verifier = verifier or FrameInventoryVerifier()
        self._command_timeout_seconds = command_timeout_seconds

    @staticmethod
    def _attempt(tile_size: int, command: Sequence[str], result: ProcessResult | ProcessError) -> UpscaleAttempt:
        return UpscaleAttempt(tile_size, tuple(command), result.returncode if isinstance(result, (ProcessResult, ProcessExecutionError)) else None, result.stdout_tail, result.stderr_tail)

    def _plan(self, extracted: FrameExtractionResult, job: JobPlan, toolchain: Toolchain, workspace: OwnedWorkspace) -> UpscalePlan:
        workspace_path = self._workspace_manager.validate(workspace)
        if extracted.workspace_identifier != workspace.identifier:
            raise ValueError("extracted frames belong to a different workspace")
        upscale_plan = create_upscale_plan(job, toolchain, workspace_path, input_directory=extracted.frames_directory, frame_count=extracted.frame_count, input_width=extracted.frame_width, input_height=extracted.frame_height)
        self._verifier.verify(upscale_plan.input_directory, upscale_plan.input_width, upscale_plan.input_height, upscale_plan.expected_frame_count)
        return upscale_plan

    @staticmethod
    def _count_output_frames(directory: Path) -> int:
        """Count Real-ESRGAN frame-shaped outputs without validating partial files."""

        try:
            return sum(1 for entry in directory.iterdir() if entry.name.startswith("frame-") and entry.suffix == ".png")
        except OSError:
            return 0

    @staticmethod
    def _sampled_preview_frame(directory: Path, completed: int) -> Path | None:
        """Return frame one immediately, then the latest sixteen-frame sample."""

        if completed < 1:
            return None
        sample = 1 if completed < LIVE_PREVIEW_FRAME_INTERVAL else completed // LIVE_PREVIEW_FRAME_INTERVAL * LIVE_PREVIEW_FRAME_INTERVAL
        candidate = directory / f"frame-{sample:09d}.png"
        return candidate if candidate.is_file() and not candidate.is_symlink() else None

    def _monitor_output_progress(self, input_directory: Path, output_directory: Path, total: int, callback: ProgressCallback, stop: Event) -> None:
        """Report observed output-frame counts while the child process runs."""

        observed = 0
        while not stop.wait(UPSCALE_PROGRESS_POLL_SECONDS):
            count = min(total, self._count_output_frames(output_directory))
            if count > observed:
                observed = count
                ProgressEmitter.emit(
                    callback,
                    PipelineStage.UPSCALE,
                    count,
                    total,
                    f"Upscaling frame {count} of {total}",
                    original_preview_image_path=self._sampled_preview_frame(input_directory, count),
                    upscaled_preview_image_path=self._sampled_preview_frame(output_directory, count),
                )

    # The bounded retry/error branches mirror the pipeline's explicit stage contract.
    # pylint: disable=too-many-branches,too-many-statements
    def execute_upscaling(self, extracted: FrameExtractionResult, job: JobPlan, toolchain: Toolchain, *, workspace: OwnedWorkspace, cancellation: CancellationToken | None = None, progress: ProgressCallback | None = None, context: StageContext | None = None) -> UpscalingResult:
        """Skip or upscale once, retrying only recognized Vulkan-memory failures."""

        if context is not None:
            workspace = context.workspace
            cancellation = context.cancellation
            progress = context.progress
            toolchain = context.toolchain or toolchain
        token = cancellation or CancellationToken()
        try:
            upscale_plan = self._plan(extracted, job, toolchain, workspace)
        except (FrameInventoryError, WorkspaceError, OSError, ValueError) as error:
            raise UpscalingFailed(f"Upscaling could not start: {error}. Workspace retained at {workspace.path}", workspace.path) from error
        if token.cancelled:
            raise UpscalingCancelled("Upscaling cancelled before launch. The caller still owns the workspace.", workspace.path)
        if upscale_plan.skipped:
            ProgressEmitter.emit(progress, PipelineStage.UPSCALE, 0, upscale_plan.expected_frame_count, "AI upscaling is not required for the requested height")
            ProgressEmitter.emit(progress, PipelineStage.UPSCALE, upscale_plan.expected_frame_count, upscale_plan.expected_frame_count, "Using the verified extracted frames without AI upscaling")
            return UpscalingResult(upscale_plan.input_directory, upscale_plan.input_directory / FRAME_FILENAME_TEMPLATE, upscale_plan.expected_frame_count, upscale_plan.input_width, upscale_plan.input_height, None, True, extracted.audio_source_path, (), workspace.identifier)
        attempts: list[UpscaleAttempt] = []
        tile_sizes = (AUTOMATIC_TILE_SIZE,) + MEMORY_RETRY_TILE_SIZES
        scale = upscale_plan.scale
        if scale is None:
            raise AssertionError("non-skipped upscale plan has no scale")
        for attempt_number, tile_size in enumerate(tile_sizes, start=1):
            command_args = create_realesrgan_command(upscale_plan, tile_size)
            tile_label = "automatic tiling" if tile_size == AUTOMATIC_TILE_SIZE else f"tile size {tile_size}"
            try:
                self._workspace_manager.recreate_direct_child(workspace, upscale_plan.output_directory.name)
                ProgressEmitter.emit(progress, PipelineStage.UPSCALE, 0, upscale_plan.expected_frame_count, f"Upscaling {upscale_plan.expected_frame_count} frames with {tile_label} (attempt {attempt_number} of {len(tile_sizes)})")
                monitor_stop = Event()
                monitor = Thread(target=self._monitor_output_progress, args=(upscale_plan.input_directory, upscale_plan.output_directory, upscale_plan.expected_frame_count, progress, monitor_stop), daemon=True) if progress is not None else None
                if monitor is not None:
                    monitor.start()
                try:
                    result = self._process_runner.run(command_args, token, self._command_timeout_seconds)
                finally:
                    monitor_stop.set()
                    if monitor is not None:
                        monitor.join()
                if token.cancelled:
                    raise ProcessCancelled("upscaling cancelled", command_args, result.stdout_tail, result.stderr_tail)
                attempts.append(self._attempt(tile_size, command_args, result))
                output_count = self._verifier.verify(upscale_plan.output_directory, upscale_plan.input_width * scale, upscale_plan.input_height * scale, upscale_plan.expected_frame_count)
            except ProcessCancelled as error:
                attempts.append(self._attempt(tile_size, command_args, error))
                raise UpscalingCancelled("Upscaling cancelled; child processes terminated. The caller still owns the workspace.", workspace.path, attempts) from error
            except ProcessExecutionError as error:
                attempts.append(self._attempt(tile_size, command_args, error))
                if is_vulkan_memory_failure(error.stdout_tail, error.stderr_tail) and attempt_number < len(tile_sizes):
                    continue
                raise UpscalingFailed(f"Real-ESRGAN failed with {tile_label}. Workspace retained at {workspace.path}", workspace.path, attempts, error.stderr_tail) from error
            except (FrameInventoryError, ProcessError, WorkspaceError, OSError, ValueError) as error:
                if isinstance(error, ProcessError):
                    attempts.append(self._attempt(tile_size, command_args, error))
                diagnostic = error.stderr_tail if isinstance(error, ProcessError) else ""
                raise UpscalingFailed(f"Upscaling failed during {tile_label}: {error}. Workspace retained at {workspace.path}", workspace.path, attempts, diagnostic) from error
            ProgressEmitter.emit(
                progress,
                PipelineStage.UPSCALE,
                output_count,
                upscale_plan.expected_frame_count,
                f"Upscaled and verified {output_count} frames",
                original_preview_image_path=self._sampled_preview_frame(upscale_plan.input_directory, output_count),
                upscaled_preview_image_path=self._sampled_preview_frame(upscale_plan.output_directory, output_count),
            )
            return UpscalingResult(upscale_plan.output_directory, upscale_plan.output_directory / FRAME_FILENAME_TEMPLATE, output_count, upscale_plan.input_width * scale, upscale_plan.input_height * scale, scale, False, extracted.audio_source_path, tuple(attempts), workspace.identifier)
        raise AssertionError("bounded Real-ESRGAN attempts exhausted without a terminal result")
