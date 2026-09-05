"""Asynchronous, GUI-independent probing of focused clip dimensions."""

# PySide6 exposes Qt types dynamically, which Pylint cannot introspect.
# pylint: disable=no-name-in-module

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import os
import shutil

from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal, Slot

from advanced_ai_video_tools.video.probe import FFprobeClient, ProbeError

FileIdentity = tuple[int, int, int, int] | None
Dimensions = tuple[int, int]
CachedDimensions = Dimensions | None


def file_identity(path: Path) -> FileIdentity:
    """Return the file version token used to invalidate stale cache entries."""

    try:
        stat = path.stat()
    except (OSError, ValueError):
        return None
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)


class DimensionProbeWorker(QObject):
    """Perform file inspection and FFprobe work on a non-GUI thread."""

    completed = Signal(object, object, object, object, object)

    @Slot(object, object, object, object)
    def probe(self, path: object, request_token: object, ffprobe_override: object, cached_entries: object) -> None:
        """Resolve one path's current identity and coded primary-video size."""

        if not isinstance(path, Path) or not isinstance(ffprobe_override, (Path, type(None))):
            self.completed.emit(path, request_token, None, None, None)
            return
        try:
            canonical = path.resolve(strict=False)
            identity = file_identity(canonical)
        except (OSError, RuntimeError, ValueError):
            canonical = Path(os.path.abspath(os.fspath(path)))
            identity = None
        if isinstance(cached_entries, Mapping) and identity in cached_entries:
            self.completed.emit(path, request_token, canonical, identity, cached_entries[identity])
            return
        try:
            executable = ffprobe_override
            if executable is None:
                resolved = shutil.which("ffprobe")
                if resolved is None:
                    raise ProbeError("FFprobe is unavailable")
                executable = Path(resolved)
            probe = FFprobeClient(executable).probe(path)
            video = probe.primary_video
            dimensions = (video.width, video.height) if video is not None else None
        except (OSError, ProbeError, ValueError):
            dimensions = None
        self.completed.emit(path, request_token, canonical, identity, dimensions)


class DimensionProbeController(QObject):
    """Own focused-first scheduling and a session-scoped versioned cache.

    The controller has no widget dependency. Consumers observe status and
    result signals and decide how those values should be presented.
    """

    request = Signal(object, object, object, object)
    status_changed = Signal(str)
    dimensions_changed = Signal(object)

    def __init__(self, ffprobe_override: Path | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._ffprobe_override = ffprobe_override
        self._settings_generation = 0
        self._next_request = 0
        self._paths: tuple[Path, ...] = ()
        self._selected = -1
        self._pending: set[Path] = set()
        self._prewarm: list[Path] = []
        self._cache: dict[tuple[Path, FileIdentity], CachedDimensions] = {}
        self._source_cache: dict[Path, dict[FileIdentity, CachedDimensions]] = {}
        self._thread = QThread(self)
        self._worker = DimensionProbeWorker()
        self._worker.moveToThread(self._thread)
        self.request.connect(self._worker.probe, Qt.ConnectionType.QueuedConnection)
        self._worker.completed.connect(self._completed, Qt.ConnectionType.QueuedConnection)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.start()

    def set_sources(self, paths: tuple[Path, ...], selected: int) -> None:
        """Set ordered sources and make the selected source highest priority."""

        self._pending.clear()
        self._paths = paths
        self._selected = selected
        self._prewarm = [path for index, path in enumerate(paths) if index != selected]
        if not 0 <= selected < len(paths):
            self.status_changed.emit("")
            self.dimensions_changed.emit(None)
            return
        self.status_changed.emit("Probing…")
        self._enqueue(paths[selected])

    def reconfigure(self, ffprobe_override: Path | None) -> None:
        """Invalidate cached results and apply the executable to new work."""

        self._settings_generation += 1
        self._ffprobe_override = ffprobe_override
        self._cache.clear()
        self._source_cache.clear()
        self._pending.clear()

    def _enqueue(self, path: Path) -> None:
        source_path = Path(os.path.abspath(os.fspath(path)))
        if source_path in self._pending:
            return
        self._pending.add(source_path)
        self._next_request += 1
        cached_entries = self._source_cache.get(source_path, {})
        self.request.emit(source_path, (self._settings_generation, self._next_request), self._ffprobe_override, cached_entries)

    @Slot(object, object, object, object, object)
    def _completed(self, path: object, request_token: object, canonical: object, identity: object, dimensions: object) -> None:
        """Accept only current-setting results and retain unfocused results."""

        if not isinstance(path, Path) or not isinstance(canonical, Path) or (not isinstance(identity, tuple) and identity is not None):
            return
        source_path = Path(os.path.abspath(os.fspath(path)))
        self._pending.discard(source_path)
        if not isinstance(request_token, tuple) or len(request_token) != 2 or request_token[0] != self._settings_generation:
            QTimer.singleShot(0, self._prewarm_next)
            return
        value = dimensions if isinstance(dimensions, tuple) and len(dimensions) == 2 else None
        self._cache[(canonical, identity)] = value
        self._source_cache.setdefault(source_path, {})[identity] = value
        self._source_cache.setdefault(canonical, {})[identity] = value
        selected_path = Path(os.path.abspath(os.fspath(self._paths[self._selected]))) if 0 <= self._selected < len(self._paths) else None
        is_selected = selected_path == source_path
        if is_selected:
            self.dimensions_changed.emit(value)
            self.status_changed.emit("" if value is not None else "Unavailable")
        QTimer.singleShot(0, self._prewarm_next)

    def _prewarm_next(self) -> None:
        """Start the next source in source-list order."""

        if self._prewarm:
            self._enqueue(self._prewarm.pop(0))

    def shutdown(self) -> None:
        """Stop and join the worker before the controller is destroyed."""

        if self._thread.isRunning():
            self._thread.quit()
            self._thread.wait()
