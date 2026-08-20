"""Creation and guarded cleanup of application-owned job workspaces."""

from __future__ import annotations

import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

_MARKER_NAME = ".ai-video-tools-owned"


class WorkspaceError(RuntimeError):
    """A workspace could not be created or safely cleaned."""


@dataclass(frozen=True)
class OwnedWorkspace:
    """Identity needed to prove ownership before recursive cleanup."""

    root: Path
    path: Path
    identifier: str

    @property
    def marker_path(self) -> Path:
        """Return the marker whose exact contents prove ownership."""

        return self.path / _MARKER_NAME


class WorkspaceManager:
    """Manage only randomly named, explicitly marked direct child directories."""

    def __init__(self, root: Path) -> None:
        resolved = root.expanduser().resolve(strict=False)
        if resolved == Path(resolved.anchor):
            raise WorkspaceError("the filesystem root cannot be a job workspace root")
        self._root = resolved

    @property
    def root(self) -> Path:
        """Return the configured job root."""

        return self._root

    def create(self) -> OwnedWorkspace:
        """Create a private random workspace and write its ownership marker."""

        self._root.mkdir(parents=True, exist_ok=True)
        if not self._root.is_dir():
            raise WorkspaceError(f"job workspace root is not a directory: {self._root}")
        identifier = uuid.uuid4().hex
        path = Path(tempfile.mkdtemp(prefix=f"job-{identifier}-", dir=self._root)).resolve()
        workspace = OwnedWorkspace(self._root, path, identifier)
        try:
            path.chmod(0o700)
            workspace.marker_path.write_text(identifier + "\n", encoding="ascii", newline="\n")
        except OSError as error:
            if path.parent == self._root and path.exists():
                shutil.rmtree(path)
            raise WorkspaceError(f"could not initialize job workspace: {error}") from error
        return workspace

    def cleanup(self, workspace: OwnedWorkspace) -> None:
        """Delete a workspace only after containment and marker verification."""

        path = self.validate(workspace)
        try:
            shutil.rmtree(path)
        except OSError as error:
            raise WorkspaceError(f"could not clean job workspace: {path}") from error

    def validate(self, workspace: OwnedWorkspace) -> Path:
        """Return the verified workspace path without changing its contents."""

        path = workspace.path.resolve(strict=False)
        if workspace.root.resolve(strict=False) != self._root or path.parent != self._root or path == self._root:
            raise WorkspaceError(f"workspace is outside the configured job root: {path}")
        marker = path / _MARKER_NAME
        if not path.is_dir() or marker.is_symlink() or not marker.is_file():
            raise WorkspaceError(f"workspace is unmarked or missing its ownership marker: {path}")
        try:
            marker_value = marker.read_text(encoding="ascii").strip()
        except OSError as error:
            raise WorkspaceError(f"could not read workspace ownership marker: {path}") from error
        if marker_value != workspace.identifier:
            raise WorkspaceError(f"workspace ownership marker does not match: {path}")
        return path
