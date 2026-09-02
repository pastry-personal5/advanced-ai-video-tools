"""Typed contracts shared by pipeline orchestration and stage executors."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from advanced_ai_video_tools.core.models import JobPlan, JobRequest, PreflightReport, Toolchain
from advanced_ai_video_tools.services.finalization import FinalizationResult
from advanced_ai_video_tools.services.context import StageContext
from advanced_ai_video_tools.services.frame_extraction import FrameExtractionResult
from advanced_ai_video_tools.services.media_preparation import PreparationResult
from advanced_ai_video_tools.services.progress import ProgressCallback
from advanced_ai_video_tools.services.upscaling import UpscalingResult
from advanced_ai_video_tools.storage.naming import OutputPathRegistry
from advanced_ai_video_tools.storage.workspaces import OwnedWorkspace
from advanced_ai_video_tools.system.processes import CancellationToken


class PreflightContract(Protocol):
    """Validation boundary that owns destination reservations."""

    @property
    def registry(self) -> OutputPathRegistry:
        """Return the registry holding successful plan reservations."""

    def execute_preflight(self, request: JobRequest, progress: ProgressCallback | None = None) -> PreflightReport:
        """Validate user intent and return a frozen execution plan."""


class PreparationContract(Protocol):
    """Composable media-preparation boundary."""

    # The explicit positional inputs preserve the existing stage API.
    # pylint: disable=too-many-positional-arguments
    def execute_preparation_in_workspace(
        self,
        job: JobPlan,
        ffmpeg: Path,
        workspace: OwnedWorkspace,
        cancellation: CancellationToken | None = None,
        progress: ProgressCallback | None = None,
        context: StageContext | None = None,
    ) -> PreparationResult:
        """Prepare one merged timeline in the shared workspace."""


class ExtractionContract(Protocol):
    """Composable frame-extraction boundary."""

    def execute_extraction(
        self,
        prepared: PreparationResult,
        job: JobPlan,
        ffmpeg: Path,
        *,
        workspace: OwnedWorkspace,
        cancellation: CancellationToken | None = None,
        progress: ProgressCallback | None = None,
        context: StageContext | None = None,
    ) -> FrameExtractionResult:
        """Extract one verified frame sequence."""


class UpscaleContract(Protocol):
    """Composable directory-upscaling boundary."""

    def execute_upscaling(
        self,
        extracted: FrameExtractionResult,
        job: JobPlan,
        toolchain: Toolchain,
        *,
        workspace: OwnedWorkspace,
        cancellation: CancellationToken | None = None,
        progress: ProgressCallback | None = None,
        context: StageContext | None = None,
    ) -> UpscalingResult:
        """Skip or execute the one permitted AI pass."""


class FinalizationContract(Protocol):
    """Terminal encoding, publication, and cleanup boundary."""

    def execute_finalization(
        self,
        prepared: PreparationResult,
        upscaled: UpscalingResult,
        job: JobPlan,
        toolchain: Toolchain,
        *,
        workspace: OwnedWorkspace,
        cancellation: CancellationToken | None = None,
        progress: ProgressCallback | None = None,
        context: StageContext | None = None,
    ) -> FinalizationResult:
        """Publish the verified output and clean terminal temporary state."""


__all__ = [
    "ExtractionContract",
    "FinalizationContract",
    "PreparationContract",
    "PreflightContract",
    "UpscaleContract",
]
