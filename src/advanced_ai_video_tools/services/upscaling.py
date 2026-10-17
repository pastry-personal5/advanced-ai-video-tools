"""Cancellable ordered AI upscale passes with bounded Real-ESRGAN memory retries."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Thread

from advanced_ai_video_tools.core.models import FileIdentity, JobPlan, PipelineStage, Toolchain, UpscaleBackend, UpscalePassPlan
from advanced_ai_video_tools.services.frame_extraction import FrameExtractionResult
from advanced_ai_video_tools.services.progress import ProgressCallback, ProgressEmitter
from advanced_ai_video_tools.services.context import StageContext
from advanced_ai_video_tools.storage.workspaces import OwnedWorkspace, WorkspaceError, WorkspaceManager
from advanced_ai_video_tools.system.processes import CancellationToken, ProcessCancelled, ProcessError, ProcessExecutionError, ProcessResult, ProcessRunner
from advanced_ai_video_tools.system.spandrel import SPANDREL_PROTOCOL_VERSION, create_spandrel_run_command, spandrel_failure_summary
from advanced_ai_video_tools.upscaling.realesrgan import AUTOMATIC_TILE_SIZE, MEMORY_RETRY_TILE_SIZES, create_realesrgan_command, create_realesrgan_plan, is_vulkan_memory_failure
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


@dataclass
class _PassProgress:
    """Monotonic aggregate progress for one pass, shared by all of its attempts."""

    callback: ProgressCallback | None
    upscale_pass: UpscalePassPlan
    pass_count: int
    frame_count: int
    original_directory: Path | None
    highest: int = 0

    @property
    def total(self) -> int:
        """Return the measured frame total across every planned pass."""

        return self.frame_count * self.pass_count

    @property
    def label(self) -> str:
        """Name the pass only when more than one runs."""

        return f"pass {self.upscale_pass.index} of {self.pass_count}: " if self.pass_count > 1 else ""

    def emit(self, completed: int, message: str, output_directory: Path | None = None) -> None:
        """Publish an aggregate count that never moves backwards, with matched previews on the final pass."""

        aggregate = min(self.total, max(self.highest, (self.upscale_pass.index - 1) * self.frame_count + completed))
        self.highest = aggregate
        original: Path | None = None
        upscaled: Path | None = None
        if self.original_directory is not None and output_directory is not None:
            original, upscaled = UpscalingExecutor.preview_pair(self.original_directory, output_directory, completed)
        ProgressEmitter.emit(
            self.callback,
            PipelineStage.UPSCALE,
            aggregate,
            self.total,
            message,
            original_preview_image_path=original,
            upscaled_preview_image_path=upscaled,
            pass_index=self.upscale_pass.index,
            pass_count=self.pass_count,
            pass_scale=self.upscale_pass.scale,
        )


@dataclass
class _PassRun:
    """Everything one backend invocation needs, owned by a single executing pass."""

    upscale_pass: UpscalePassPlan
    input_directory: Path
    output_directory: Path
    frame_count: int
    workspace: OwnedWorkspace
    token: CancellationToken
    tracker: _PassProgress
    attempts: list[UpscaleAttempt]


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

    @staticmethod
    def preview_pair(original_directory: Path, output_directory: Path, completed: int) -> tuple[Path | None, Path | None]:
        """Return a matched Original/Upscaled sample, or neither until both frames exist."""

        original = UpscalingExecutor._sampled_preview_frame(original_directory, completed)
        upscaled = UpscalingExecutor._sampled_preview_frame(output_directory, completed)
        return (original, upscaled) if original is not None and upscaled is not None else (None, None)

    def _monitor_output_progress(self, tracker: _PassProgress, output_directory: Path, stop: Event) -> None:
        """Report observed output-frame counts while the child process runs."""

        observed = 0
        while not stop.wait(UPSCALE_PROGRESS_POLL_SECONDS):
            count = min(tracker.frame_count, self._count_output_frames(output_directory))
            if count > observed:
                observed = count
                tracker.emit(count, f"Upscaling {tracker.label}frame {count} of {tracker.frame_count}", output_directory)

    def _run_monitored(self, command: Sequence[str], run: _PassRun) -> ProcessResult:
        """Run one backend command while a monitor reports completed output frames."""

        monitor_stop = Event()
        monitor = Thread(target=self._monitor_output_progress, args=(run.tracker, run.output_directory, monitor_stop), daemon=True) if run.tracker.callback is not None else None
        if monitor is not None:
            monitor.start()
        try:
            result = self._process_runner.run(command, run.token, self._command_timeout_seconds)
        finally:
            monitor_stop.set()
            if monitor is not None:
                monitor.join()
        if run.token.cancelled:
            raise ProcessCancelled("upscaling cancelled", command, result.stdout_tail, result.stderr_tail)
        return result

    @staticmethod
    def _file_identity(path: Path) -> FileIdentity:
        """Hash one stable file for the runner manifest change guard."""

        before = path.stat()
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        after = path.stat()
        before_values = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        after_values = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        if before_values != after_values:
            raise ValueError(f"file changed while its identity was calculated: {path}")
        return FileIdentity(path.resolve(), before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, digest.hexdigest())

    @staticmethod
    def _identity_document(identity: FileIdentity) -> dict[str, object]:
        return {
            "path": str(identity.path),
            "device": identity.device,
            "inode": identity.inode,
            "size_bytes": identity.size_bytes,
            "modified_ns": identity.modified_ns,
            "sha256": identity.sha256,
        }

    def _spandrel_manifest(self, run: _PassRun, workspace: Path) -> Path:
        """Freeze exact input identities and output names for one runner invocation."""

        upscale_pass, input_directory, output_directory, frame_count = run.upscale_pass, run.input_directory, run.output_directory, run.frame_count
        if upscale_pass.model_identity is None:
            raise ValueError("Spandrel pass has no inspected model identity")
        current_model = self._file_identity(upscale_pass.model_path)
        if current_model != upscale_pass.model_identity:
            raise ValueError("Spandrel model identity changed before launch")
        jobs: list[dict[str, object]] = []
        for number in range(1, frame_count + 1):
            if run.token.cancelled:
                raise ProcessCancelled("upscaling cancelled while preparing the runner manifest", ())
            source = input_directory / (FRAME_FILENAME_TEMPLATE % number)
            destination = output_directory / (FRAME_FILENAME_TEMPLATE % number)
            identity = self._file_identity(source)
            jobs.append(
                {
                    "input": {"path": str(source.resolve()), "identity": self._identity_document(identity), "width": upscale_pass.input_width, "height": upscale_pass.input_height},
                    "output": {"path": str(destination.resolve(strict=False)), "width": upscale_pass.output_width, "height": upscale_pass.output_height},
                }
            )
        manifest = workspace / f"spandrel-pass-{upscale_pass.index}.json"
        document = {"protocol_version": SPANDREL_PROTOCOL_VERSION, "model_identity": self._identity_document(upscale_pass.model_identity), "output_directory": str(output_directory.resolve()), "jobs": jobs}
        manifest.write_text(json.dumps(document, sort_keys=True), encoding="utf-8")
        return manifest

    def _run_realesrgan_pass(self, run: _PassRun, model_name: str) -> int:
        """Run one Real-ESRGAN pass, retrying only recognized Vulkan-memory failures."""

        plan = create_realesrgan_plan(run.upscale_pass, model_name, input_directory=run.input_directory, output_directory=run.output_directory, frame_count=run.frame_count)
        tile_sizes = (AUTOMATIC_TILE_SIZE,) + MEMORY_RETRY_TILE_SIZES
        for attempt_number, tile_size in enumerate(tile_sizes, start=1):
            command_args = create_realesrgan_command(plan, tile_size)
            tile_label = "automatic tiling" if tile_size == AUTOMATIC_TILE_SIZE else f"tile size {tile_size}"
            try:
                self._workspace_manager.recreate_direct_child(run.workspace, run.output_directory.name)
                run.tracker.emit(0, f"Upscaling {run.tracker.label}{run.frame_count} frames with {tile_label} (attempt {attempt_number} of {len(tile_sizes)})")
                result = self._run_monitored(command_args, run)
                run.attempts.append(self._attempt(tile_size, command_args, result))
                return self._verifier.verify(run.output_directory, run.upscale_pass.output_width, run.upscale_pass.output_height, run.frame_count)
            except ProcessCancelled as error:
                run.attempts.append(self._attempt(tile_size, command_args, error))
                raise
            except ProcessExecutionError as error:
                run.attempts.append(self._attempt(tile_size, command_args, error))
                if is_vulkan_memory_failure(error.stdout_tail, error.stderr_tail) and attempt_number < len(tile_sizes):
                    continue
                raise UpscalingFailed(f"Real-ESRGAN failed with {tile_label}. Workspace retained at {run.workspace.path}", run.workspace.path, run.attempts, error.stderr_tail) from error
            except (FrameInventoryError, ProcessError, WorkspaceError, OSError, ValueError) as error:
                if isinstance(error, ProcessError):
                    run.attempts.append(self._attempt(tile_size, command_args, error))
                diagnostic = error.stderr_tail if isinstance(error, ProcessError) else ""
                raise UpscalingFailed(f"Upscaling failed during {tile_label}: {error}. Workspace retained at {run.workspace.path}", run.workspace.path, run.attempts, diagnostic) from error
        raise AssertionError("bounded Real-ESRGAN attempts exhausted without a terminal result")

    def _run_spandrel_pass(self, run: _PassRun) -> int:
        """Run one direct-inference Spandrel pass exactly once; failures are never retried or moved off MPS."""

        upscale_pass = run.upscale_pass
        manifest = self._spandrel_manifest(run, self._workspace_manager.validate(run.workspace))
        command_args = create_spandrel_run_command(upscale_pass.executable_path, upscale_pass.model_path, manifest)
        run.tracker.emit(0, f"Upscaling {run.tracker.label}{run.frame_count} frames with the {upscale_pass.scale}x Spandrel model")
        try:
            result = self._run_monitored(command_args, run)
            run.attempts.append(self._attempt(AUTOMATIC_TILE_SIZE, command_args, result))
            return self._verifier.verify(run.output_directory, upscale_pass.output_width, upscale_pass.output_height, run.frame_count)
        except ProcessCancelled as error:
            run.attempts.append(self._attempt(AUTOMATIC_TILE_SIZE, command_args, error))
            raise
        except ProcessError as error:
            run.attempts.append(self._attempt(AUTOMATIC_TILE_SIZE, command_args, error))
            summary = spandrel_failure_summary(error.stderr_tail) or str(error)
            raise UpscalingFailed(f"Spandrel pass {upscale_pass.index} ({upscale_pass.scale}x) failed: {summary}. Workspace retained at {run.workspace.path}", run.workspace.path, run.attempts, error.stderr_tail) from error

    def _execute_passes(self, extracted: FrameExtractionResult, job: JobPlan, workspace: OwnedWorkspace, token: CancellationToken, *, progress: ProgressCallback | None, attempts: list[UpscaleAttempt]) -> UpscalingResult:
        """Skip, or run and verify every frozen pass before the next consumes its frames."""

        workspace_path = self._workspace_manager.validate(workspace)
        if extracted.workspace_identifier != workspace.identifier:
            raise ValueError("extracted frames belong to a different workspace")
        if extracted.frames_directory.resolve(strict=False).parent != workspace_path.resolve(strict=False):
            raise ValueError("extracted frames must be a direct child of the owned workspace")
        frame_count = extracted.frame_count
        self._verifier.verify(extracted.frames_directory, extracted.frame_width, extracted.frame_height, frame_count)
        if token.cancelled:
            raise UpscalingCancelled("Upscaling cancelled before launch. The caller still owns the workspace.", workspace.path, attempts)
        passes = job.upscale_passes
        if not passes:
            ProgressEmitter.emit(progress, PipelineStage.UPSCALE, 0, frame_count, "AI upscaling is not required for the requested height")
            ProgressEmitter.emit(progress, PipelineStage.UPSCALE, frame_count, frame_count, "Using the verified extracted frames without AI upscaling")
            return UpscalingResult(extracted.frames_directory, extracted.frames_directory / FRAME_FILENAME_TEMPLATE, frame_count, extracted.frame_width, extracted.frame_height, None, True, extracted.audio_source_path, (), workspace.identifier)
        current_directory = extracted.frames_directory
        current_width = extracted.frame_width
        current_height = extracted.frame_height
        for upscale_pass in passes:
            if token.cancelled:
                raise UpscalingCancelled("Upscaling cancelled before the next pass. The caller still owns the workspace.", workspace.path, attempts)
            if (current_width, current_height) != (upscale_pass.input_width, upscale_pass.input_height):
                raise ValueError(f"pass {upscale_pass.index} input dimensions differ from the verified prior inventory")
            is_final = upscale_pass.index == len(passes)
            tracker = _PassProgress(progress, upscale_pass, len(passes), frame_count, extracted.frames_directory if is_final else None)
            output_directory = self._workspace_manager.recreate_direct_child(workspace, "upscaled" if len(passes) == 1 else f"upscaled-pass-{upscale_pass.index}")
            run = _PassRun(upscale_pass, current_directory, output_directory, frame_count, workspace, token, tracker, attempts)
            output_count = self._run_spandrel_pass(run) if upscale_pass.backend is UpscaleBackend.SPANDREL else self._run_realesrgan_pass(run, job.model_name)
            tracker.emit(output_count, f"Upscaled and verified {tracker.label}{output_count} frames at {upscale_pass.scale}x", output_directory)
            current_directory, current_width, current_height = output_directory, upscale_pass.output_width, upscale_pass.output_height
        return UpscalingResult(current_directory, current_directory / FRAME_FILENAME_TEMPLATE, frame_count, current_width, current_height, math.prod(item.scale for item in passes), False, extracted.audio_source_path, tuple(attempts), workspace.identifier)

    def execute_upscaling(self, extracted: FrameExtractionResult, job: JobPlan, toolchain: Toolchain, *, workspace: OwnedWorkspace, cancellation: CancellationToken | None = None, progress: ProgressCallback | None = None, context: StageContext | None = None) -> UpscalingResult:
        """Run the frozen ordered AI passes, or reuse the extracted frames when none are planned."""

        if context is not None:
            workspace = context.workspace
            cancellation = context.cancellation
            progress = context.progress
        del toolchain  # Every executable and model path is frozen in the job's pass plan.
        token = cancellation or CancellationToken()
        attempts: list[UpscaleAttempt] = []
        try:
            return self._execute_passes(extracted, job, workspace, token, progress=progress, attempts=attempts)
        except ProcessCancelled as error:
            raise UpscalingCancelled("Upscaling cancelled; child processes terminated. The caller still owns the workspace.", workspace.path, attempts) from error
        except (FrameInventoryError, ProcessError, WorkspaceError, OSError, ValueError) as error:
            diagnostic = error.stderr_tail if isinstance(error, ProcessError) else ""
            raise UpscalingFailed(f"Upscaling failed: {error}. Workspace retained at {workspace.path}", workspace.path, attempts, diagnostic) from error
