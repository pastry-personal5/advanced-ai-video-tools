"""Business rules for source-clip filesystem actions."""

# PySide6 exposes Qt types dynamically, which Pylint cannot introspect.
# pylint: disable=no-name-in-module

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QFile


@dataclass(frozen=True)
class TrashMoveResult:
    """Outcome of one guarded source-file Trash request."""

    moved: bool
    message: str


class SourceClipTrashService:
    """Guard source-file Trash operations against queued job intent."""

    _default_mover = staticmethod(QFile.moveToTrash)

    def __init__(self, mover: Callable[[str], bool] | None = None) -> None:
        self._mover = mover or self._default_mover

    @staticmethod
    def canonical_path(path: Path) -> Path:
        """Normalize a source identity for duplicate and queue comparisons."""

        return path.expanduser().resolve(strict=False)

    def move_to_trash(self, path: Path, queued_inputs: Iterable[Path] = ()) -> TrashMoveResult:
        """Move a source to Trash unless active queue intent references it."""

        try:
            canonical = self.canonical_path(path)
            if any(self.canonical_path(candidate) == canonical for candidate in queued_inputs):
                return TrashMoveResult(False, f"Cannot move source clip to Trash because it is already queued: {path.name}")
        except (OSError, RuntimeError, ValueError):
            return TrashMoveResult(False, f"Could not verify whether source clip is safe to move to Trash: {path.name}")
        if not path.is_file() or path.is_dir():
            return TrashMoveResult(False, f"Could not move source clip to Trash; file is unavailable: {path.name}")
        try:
            moved = self._mover(str(path))
        except (OSError, RuntimeError, ValueError):
            moved = False
        if not moved:
            return TrashMoveResult(False, f"Could not move source clip to Trash: {path.name}")
        return TrashMoveResult(True, f"Moved source clip to Trash: {path.name}")
