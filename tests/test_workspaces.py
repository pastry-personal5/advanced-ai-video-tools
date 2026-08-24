"""Tests for guarded creation and deletion of owned job workspaces."""

import stat
from pathlib import Path

import pytest

from advanced_ai_video_tools.storage.workspaces import OwnedWorkspace, WorkspaceError, WorkspaceManager


def test_owned_workspace_is_private_marked_and_cleanable(tmp_path: Path) -> None:
    """A manager can delete exactly the random workspace it created."""

    manager = WorkspaceManager(tmp_path / "jobs")
    workspace = manager.create()

    assert workspace.path.parent == manager.root
    assert workspace.marker_path.read_text(encoding="ascii").strip() == workspace.identifier
    assert stat.S_IMODE(workspace.path.stat().st_mode) == 0o700
    manager.cleanup(workspace)
    assert not workspace.path.exists()


def test_cleanup_refuses_unmarked_mismatched_and_outside_directories(tmp_path: Path) -> None:
    """Recursive deletion requires containment and an exact ownership marker."""

    manager = WorkspaceManager(tmp_path / "jobs")
    unmarked = manager.root / "unmarked"
    unmarked.mkdir(parents=True)
    with pytest.raises(WorkspaceError, match="unmarked"):
        manager.cleanup(OwnedWorkspace(manager.root, unmarked, "id"))
    assert unmarked.exists()

    workspace = manager.create()
    assert manager.validate(workspace) == workspace.path
    forged = OwnedWorkspace(manager.root, workspace.path, "wrong-id")
    with pytest.raises(WorkspaceError, match="does not match"):
        manager.cleanup(forged)
    assert workspace.path.exists()

    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(WorkspaceError, match="outside"):
        manager.cleanup(OwnedWorkspace(manager.root, outside, "id"))
    assert outside.exists()


def test_filesystem_root_cannot_be_configured_as_job_root() -> None:
    """A broad destructive target is rejected at construction time."""

    with pytest.raises(WorkspaceError, match="filesystem root"):
        WorkspaceManager(Path("/"))


def test_recreate_direct_child_removes_only_verified_owned_content(tmp_path: Path) -> None:
    """Retry cleanup cannot escape the workspace or retain stale output."""

    manager = WorkspaceManager(tmp_path / "jobs")
    workspace = manager.create()
    output = workspace.path / "upscaled"
    output.mkdir()
    (output / "partial.png").write_bytes(b"partial")

    recreated = manager.recreate_direct_child(workspace, "upscaled")

    assert recreated == output
    assert not any(recreated.iterdir())
    with pytest.raises(WorkspaceError, match="invalid"):
        manager.recreate_direct_child(workspace, "../outside")
