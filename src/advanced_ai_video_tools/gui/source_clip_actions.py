"""Business rules for source-clip filesystem actions."""

# PySide6 exposes Qt types dynamically, which Pylint cannot introspect.
# pylint: disable=no-name-in-module

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QFile, QFileInfo

from advanced_ai_video_tools.system.settings import DEFAULT_DELETION_RULES, DeletionRule


@dataclass(frozen=True)
class TrashMoveResult:
    """Outcome of one guarded source-file Trash request."""

    moved: bool
    message: str
    related_deleted: tuple[Path, ...] = ()
    related_failed: tuple[Path, ...] = ()


class SourceClipTrashService:
    """Guard source-file Trash operations against queued job intent."""

    _default_mover = staticmethod(QFile.moveToTrash)

    def __init__(self, mover: Callable[[str], bool] | None = None, *, deletion_rules: tuple[DeletionRule, ...] | None = None, message_callback: Callable[[str], None] | None = None) -> None:
        self._mover = mover or self._default_mover
        self._deletion_rules = deletion_rules
        self._message_callback = message_callback

    def configure(self, deletion_rules: tuple[DeletionRule, ...] | None) -> None:
        """Apply rules saved after this service was created."""

        self._deletion_rules = deletion_rules

    def set_message_callback(self, callback: Callable[[str], None] | None) -> None:
        """Set the presentation callback used for related-file diagnostics."""

        self._message_callback = callback

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
        related_deleted, related_failed = self._move_related_to_trash(path)
        return TrashMoveResult(True, f"Moved source clip to Trash: {path.name}", related_deleted, related_failed)

    def _move_related_to_trash(self, source_path: Path) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
        """Move eligible matching siblings after a successful source move."""

        rules = DEFAULT_DELETION_RULES if self._deletion_rules is None else self._deletion_rules
        selected_rule = next((rule for rule in rules if rule.enabled and rule.matches_source(source_path.name)), None)
        if selected_rule is None:
            return (), ()
        try:
            candidates = sorted(source_path.parent.iterdir(), key=lambda candidate: (candidate.name.casefold(), candidate.name))
        except OSError:
            return (), ()
        deleted: list[Path] = []
        failed: list[Path] = []
        for candidate in candidates:
            if not self._is_eligible_related_file(candidate, source_path) or not selected_rule.matches_target(source_path.name, candidate.name):
                continue
            try:
                moved = self._mover(str(candidate))
                reason = "Trash provider rejected the request"
            except (OSError, RuntimeError, ValueError) as error:
                moved = False
                reason = str(error) or "Trash provider failed"
            if moved:
                deleted.append(candidate)
                self._emit_related_message(f"Also moved related file to Trash: {candidate.name}")
            else:
                failed.append(candidate)
                self._emit_related_message(f"Could not move related file to Trash: {candidate.name}: {reason}")
        return tuple(deleted), tuple(failed)

    def _emit_related_message(self, message: str) -> None:
        if self._message_callback is not None:
            self._message_callback(message)

    @staticmethod
    def _is_eligible_related_file(candidate: Path, source_path: Path) -> bool:
        """Accept only immediate regular files that are neither links nor aliases."""

        if candidate == source_path or candidate.is_symlink() or not candidate.is_file():
            return False
        return not QFileInfo(str(candidate)).isAlias()
