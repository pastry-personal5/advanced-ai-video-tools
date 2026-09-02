"""Compose one validated video job through every processing stage."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from loguru import logger

from advanced_ai_video_tools.core.models import IssueSeverity, JobPlan, JobRequest, JobState, PipelineStage, PreflightReport, Toolchain
from advanced_ai_video_tools.services.finalization import FinalOutputVerifier, FinalizationCancelled, FinalizationExecutor, FinalizationFailed, FinalizationResult
from advanced_ai_video_tools.services.frame_extraction import FrameExtractionCancelled, FrameExtractionExecutor, FrameExtractionFailed
from advanced_ai_video_tools.services.media_preparation import MediaPreparationExecutor, MergedOutputVerifier, PreparationCancelled, PreparationFailed
from advanced_ai_video_tools.services.contracts import ExtractionContract, FinalizationContract, PreparationContract, PreflightContract, UpscaleContract
from advanced_ai_video_tools.services.context import StageContext
from advanced_ai_video_tools.services.preflight import PreflightService
from advanced_ai_video_tools.services.progress import ProgressCallback, ProgressEmitter
from advanced_ai_video_tools.services.upscaling import UpscalingCancelled, UpscalingExecutor, UpscalingFailed
from advanced_ai_video_tools.storage.paths import job_cache_directory
from advanced_ai_video_tools.storage.workspaces import OwnedWorkspace, WorkspaceError, WorkspaceManager
from advanced_ai_video_tools.system.processes import CancellationToken, ProcessRunner, SubprocessRunner
from advanced_ai_video_tools.video.probe import FFprobeClient

StateCallback = Callable[[JobState], None]


@dataclass(frozen=True)
class PipelineResult:
    """Successful full-job result shared by future CLI and GUI adapters."""

    preflight: PreflightReport
    finalization: FinalizationResult

    @property
    def output_path(self) -> Path:
        """Return the published output destination."""

        return self.finalization.output_path


class PipelineFailed(RuntimeError):
    """A job failed validation or processing and retained diagnostics when available."""

    def __init__(self, message: str, stage: PipelineStage, *, preflight: PreflightReport, workspace_path: Path | None = None, diagnostic_tail: str = "") -> None:
        super().__init__(message)
        self.stage = stage
        self.preflight = preflight
        self.workspace_path = workspace_path
        self.diagnostic_tail = diagnostic_tail


class PipelineCancelled(RuntimeError):
    """A job reached a clean cancelled terminal state."""

    def __init__(self, message: str, stage: PipelineStage, *, preflight: PreflightReport | None = None, workspace_path: Path | None = None) -> None:
        super().__init__(message)
        self.stage = stage
        self.preflight = preflight
        self.workspace_path = workspace_path


class InvalidJobStateTransition(RuntimeError):
    """The orchestration attempted an impossible lifecycle transition."""


_ALLOWED_TRANSITIONS: dict[JobState, frozenset[JobState]] = {
    JobState.QUEUED: frozenset({JobState.VALIDATING, JobState.CANCELLING}),
    JobState.VALIDATING: frozenset({JobState.RUNNING, JobState.CANCELLING, JobState.FAILED}),
    JobState.RUNNING: frozenset({JobState.CANCELLING, JobState.FAILED, JobState.COMPLETED}),
    JobState.CANCELLING: frozenset({JobState.CANCELLED, JobState.FAILED}),
    JobState.CANCELLED: frozenset(),
    JobState.FAILED: frozenset(),
    JobState.COMPLETED: frozenset(),
}


class JobLifecycle:
    """Enforce and report the legal state sequence for one synchronous job."""

    def __init__(self, callback: StateCallback | None = None) -> None:
        self._callback = callback
        self._state = JobState.QUEUED
        logger.info("Job state={}", self._state.value)
        if callback is not None:
            callback(self._state)

    @property
    def state(self) -> JobState:
        """Return the current lifecycle state."""

        return self._state

    def transition(self, state: JobState) -> None:
        """Move to one legal next state and notify the caller."""

        if state not in _ALLOWED_TRANSITIONS[self._state]:
            raise InvalidJobStateTransition(f"cannot transition a job from {self._state.value} to {state.value}")
        self._state = state
        logger.info("Job state={}", state.value)
        if self._callback is not None:
            self._callback(state)


class PipelineService:
    """Run one job synchronously through the shared concat-first pipeline."""

    def __init__(
        self,
        *,
        preflight: PreflightContract | None = None,
        workspace_manager: WorkspaceManager | None = None,
        process_runner: ProcessRunner | None = None,
        preparation: PreparationContract | None = None,
        extraction: ExtractionContract | None = None,
        upscaling: UpscaleContract | None = None,
        finalization: FinalizationContract | None = None,
    ) -> None:
        self._preflight = preflight or PreflightService()
        self._workspace_manager = workspace_manager or WorkspaceManager(job_cache_directory())
        self._process_runner = process_runner or SubprocessRunner()
        self._preparation = preparation
        self._extraction = extraction
        self._upscaling = upscaling
        self._finalization = finalization

    def _stage_runners(self, toolchain: Toolchain) -> tuple[PreparationContract, ExtractionContract, UpscaleContract, FinalizationContract]:
        prober = FFprobeClient(toolchain.ffprobe.path)
        preparation = self._preparation or MediaPreparationExecutor(self._workspace_manager, self._process_runner, MergedOutputVerifier(prober))
        extraction = self._extraction or FrameExtractionExecutor(self._workspace_manager, self._process_runner)
        upscaling = self._upscaling or UpscalingExecutor(self._workspace_manager, self._process_runner)
        finalization = self._finalization or FinalizationExecutor(self._workspace_manager, self._process_runner, FinalOutputVerifier(prober))
        return preparation, extraction, upscaling, finalization

    def _execute_stages(self, plan: JobPlan, toolchain: Toolchain, workspace: OwnedWorkspace, token: CancellationToken, progress: ProgressCallback | None) -> FinalizationResult:
        """Pass one workspace and cancellation token through every stage."""

        preparation, extraction, upscaling, finalization = self._stage_runners(toolchain)
        context = StageContext(workspace=workspace, cancellation=token, progress=progress, toolchain=toolchain)
        with logger.contextualize(stage=PipelineStage.NORMALIZE.value):
            logger.info("Starting media preparation")
            prepared = preparation.execute_preparation_in_workspace(plan, toolchain.ffmpeg.path, workspace, token, progress, context=context)
        with logger.contextualize(stage=PipelineStage.EXTRACT.value):
            logger.info("Starting frame extraction")
            extracted = extraction.execute_extraction(prepared, plan, toolchain.ffmpeg.path, workspace=workspace, cancellation=token, progress=progress, context=context)
        with logger.contextualize(stage=PipelineStage.UPSCALE.value):
            logger.info("Starting AI upscale scale={} model={}", plan.ai_scale or "skip", plan.model_name)
            upscaled = upscaling.execute_upscaling(extracted, plan, toolchain, workspace=workspace, cancellation=token, progress=progress, context=context)
        with logger.contextualize(stage=PipelineStage.ENCODE.value):
            logger.info("Starting final encoding and publication")
            return finalization.execute_finalization(prepared, upscaled, plan, toolchain, workspace=workspace, cancellation=token, progress=progress, context=context)

    @staticmethod
    def _emit_cleanup(progress: ProgressCallback | None, completed: int, message: str) -> None:
        ProgressEmitter.emit(progress, PipelineStage.CLEANUP, completed, 1, message)

    def _clean_cancelled_workspace(self, workspace: OwnedWorkspace, progress: ProgressCallback | None) -> None:
        self._emit_cleanup(progress, 0, "Cleaning the cancelled job workspace")
        self._workspace_manager.cleanup(workspace)
        self._emit_cleanup(progress, 1, "Cancelled job workspace cleaned")

    @staticmethod
    def _blocking_message(report: PreflightReport) -> str:
        messages = tuple(issue.message for issue in report.issues if issue.severity is IssueSeverity.ERROR)
        return "; ".join(messages) if messages else "Preflight did not produce a runnable job plan."

    def _create_workspace(self, report: PreflightReport, lifecycle: JobLifecycle) -> OwnedWorkspace:
        """Create the caller-owned workspace after validation succeeds."""

        try:
            workspace = self._workspace_manager.create()
            logger.info("Created owned workspace identifier={}", workspace.identifier)
            return workspace
        except WorkspaceError as error:
            lifecycle.transition(JobState.FAILED)
            raise PipelineFailed(f"Could not create the job workspace: {error}", PipelineStage.VALIDATE, preflight=report) from error

    def _validate(self, request: JobRequest, token: CancellationToken, lifecycle: JobLifecycle, progress: ProgressCallback | None) -> tuple[PreflightReport, JobPlan, Toolchain]:
        """Run preflight and return only a complete runnable plan."""

        if token.cancelled:
            lifecycle.transition(JobState.CANCELLING)
            lifecycle.transition(JobState.CANCELLED)
            raise PipelineCancelled("Processing cancelled before validation.", PipelineStage.VALIDATE)
        lifecycle.transition(JobState.VALIDATING)
        report = self._preflight.execute_preflight(request, progress)
        plan = report.plan
        toolchain = report.toolchain
        if not report.ready or plan is None or toolchain is None:
            lifecycle.transition(JobState.FAILED)
            raise PipelineFailed(self._blocking_message(report), PipelineStage.VALIDATE, preflight=report)
        return report, plan, toolchain

    def _run_job(self, request: JobRequest, cancellation: CancellationToken | None, progress: ProgressCallback | None, state_changed: StateCallback | None) -> PipelineResult:
        """Execute one contextualized job, retaining failures and cleaning cancellation."""

        token = cancellation or CancellationToken()
        lifecycle = JobLifecycle(state_changed)
        with logger.contextualize(stage=PipelineStage.VALIDATE.value):
            report, plan, toolchain = self._validate(request, token, lifecycle, progress)
            logger.info("Preflight accepted output={}x{} rate={} concat={} ffmpeg={} ffprobe={} realesrgan={}", plan.output_width, plan.output_height, plan.output_frame_rate, plan.concat_strategy.value, toolchain.ffmpeg.path.name, toolchain.ffprobe.path.name, toolchain.realesrgan.path.name)
        reservation = plan.output_path
        workspace: OwnedWorkspace | None = None
        try:
            if token.cancelled:
                lifecycle.transition(JobState.CANCELLING)
                lifecycle.transition(JobState.CANCELLED)
                raise PipelineCancelled("Processing cancelled after validation.", PipelineStage.VALIDATE, preflight=report)
            lifecycle.transition(JobState.RUNNING)
            workspace = self._create_workspace(report, lifecycle)
            finalized = self._execute_stages(plan, toolchain, workspace, token, progress)
        except FinalizationCancelled as error:
            lifecycle.transition(JobState.CANCELLING)
            lifecycle.transition(JobState.CANCELLED)
            raise PipelineCancelled(str(error), error.stage, preflight=report, workspace_path=error.workspace_path) from error
        except (PreparationCancelled, FrameExtractionCancelled, UpscalingCancelled) as error:
            lifecycle.transition(JobState.CANCELLING)
            if workspace is None:
                lifecycle.transition(JobState.FAILED)
                raise PipelineFailed("Cancellation lost ownership of the job workspace.", PipelineStage.CLEANUP, preflight=report) from error
            try:
                self._clean_cancelled_workspace(workspace, progress)
            except WorkspaceError as cleanup_error:
                lifecycle.transition(JobState.FAILED)
                raise PipelineFailed(f"Processing was cancelled, but the owned workspace could not be cleaned: {cleanup_error}", PipelineStage.CLEANUP, preflight=report, workspace_path=workspace.path) from cleanup_error
            lifecycle.transition(JobState.CANCELLED)
            raise PipelineCancelled("Processing cancelled; child processes terminated and workspace cleaned.", error.stage, preflight=report, workspace_path=workspace.path) from error
        except (PreparationFailed, FrameExtractionFailed, UpscalingFailed, FinalizationFailed) as error:
            lifecycle.transition(JobState.FAILED)
            raise PipelineFailed(str(error), error.stage, preflight=report, workspace_path=error.workspace_path, diagnostic_tail=error.diagnostic_tail) from error
        else:
            lifecycle.transition(JobState.COMPLETED)
            return PipelineResult(report, finalized)
        finally:
            self._preflight.registry.release(reservation)

    def execute_pipeline(self, request: JobRequest, *, cancellation: CancellationToken | None = None, progress: ProgressCallback | None = None, state_changed: StateCallback | None = None, job_id: str | None = None) -> PipelineResult:
        """Execute one complete job with stable privacy-conscious log context."""

        resolved_job_id = job_id or uuid4().hex
        with logger.contextualize(job_id=resolved_job_id, stage=JobState.QUEUED.value):
            logger.info("Job submitted input_count={} target_height={} model={}", len(request.inputs), request.target_height, request.model_name)
            try:
                result = self._run_job(request, cancellation, progress, state_changed)
            except PipelineCancelled as error:
                logger.info("Job cancelled stage={} workspace_retained={}", error.stage.value, bool(error.workspace_path and error.workspace_path.exists()))
                raise
            except PipelineFailed as error:
                logger.error("Job failed stage={} workspace_retained={} diagnostic_bytes={}", error.stage.value, bool(error.workspace_path and error.workspace_path.exists()), len(error.diagnostic_tail.encode("utf-8")))
                raise
            logger.info("Job completed workspace_identifier={}", result.finalization.workspace_identifier)
            return result
