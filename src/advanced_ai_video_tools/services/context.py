"""Immutable dependencies shared by future pipeline stages."""

from __future__ import annotations

from dataclasses import dataclass

from advanced_ai_video_tools.services.progress import ProgressCallback
from advanced_ai_video_tools.storage.workspaces import OwnedWorkspace
from advanced_ai_video_tools.system.processes import CancellationToken
from advanced_ai_video_tools.core.models import Toolchain


@dataclass(frozen=True)
class StageContext:
    """Execution dependencies that must flow unchanged through a stage."""

    workspace: OwnedWorkspace
    cancellation: CancellationToken
    progress: ProgressCallback | None = None
    toolchain: Toolchain | None = None
