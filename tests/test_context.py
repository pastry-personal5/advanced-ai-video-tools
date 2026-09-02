"""Tests for immutable future-facing stage execution context."""

from pathlib import Path

import pytest

from advanced_ai_video_tools.services.context import StageContext
from advanced_ai_video_tools.storage.workspaces import OwnedWorkspace
from advanced_ai_video_tools.system.processes import CancellationToken


def test_stage_context_is_frozen_and_keeps_shared_dependencies() -> None:
    """Stages receive one immutable set of lifecycle dependencies."""

    workspace = OwnedWorkspace(Path("/jobs"), Path("/jobs/job-1"), "job-1")
    cancellation = CancellationToken()
    context = StageContext(workspace=workspace, cancellation=cancellation)

    assert context.workspace is workspace
    assert context.cancellation is cancellation
    assert context.progress is None
    with pytest.raises(AttributeError):
        context.workspace = workspace  # type: ignore[misc]
