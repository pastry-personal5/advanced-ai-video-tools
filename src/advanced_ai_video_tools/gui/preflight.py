"""Asynchronous diagnostic preflight for GUI review before queue submission."""

# PySide6 exposes Qt types dynamically, which Pylint cannot introspect.
# pylint: disable=no-name-in-module

from __future__ import annotations

from collections.abc import Callable

from loguru import logger
from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot

from advanced_ai_video_tools.core.models import JobRequest
from advanced_ai_video_tools.gui.worker_lifecycle import connect_completion_cleanup, shutdown_worker_thread
from advanced_ai_video_tools.services.preflight import PreflightService


class _PreflightWorker(QObject):
    finished = Signal(object, object)
    failed = Signal(object, str)
    progress = Signal(object)

    def __init__(self, request: JobRequest, service_factory: Callable[[], PreflightService]) -> None:
        super().__init__()
        self._request = request
        self._service_factory = service_factory

    @Slot()
    def run(self) -> None:
        """Run and release one diagnostic-only reservation on the worker thread."""

        try:
            service = self._service_factory()
            report = service.execute_preflight(self._request, self.progress.emit)
            if report.plan is not None:
                service.registry.release(report.plan.output_path)
        except Exception as error:  # pylint: disable=broad-exception-caught
            logger.opt(exception=error).error("GUI diagnostic preflight failed unexpectedly")
            self.failed.emit(self._request, f"Diagnostic preflight failed: {error}")
            return
        self.finished.emit(self._request, report)


class GuiPreflightController(QObject):
    """Own at most one QThread-backed diagnostic preview at a time."""

    finished = Signal(object, object)
    failed = Signal(object, str)
    progress = Signal(object)
    busy_changed = Signal(bool)

    def __init__(self, service_factory: Callable[[], PreflightService] = PreflightService, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._service_factory = service_factory
        self._thread: QThread | None = None
        self._worker: _PreflightWorker | None = None

    @property
    def busy(self) -> bool:
        """Whether diagnostic media inspection is still running."""

        return self._thread is not None

    def begin_preview(self, request: JobRequest) -> bool:
        """Start a non-authoritative preview without blocking the Qt thread."""

        if self.busy:
            return False
        thread = QThread(self)
        worker = _PreflightWorker(request, self._service_factory)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._forward_progress, Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(self._forward_finished, Qt.ConnectionType.QueuedConnection)
        worker.failed.connect(self._forward_failed, Qt.ConnectionType.QueuedConnection)
        connect_completion_cleanup(thread, worker, worker.finished, worker.failed)
        thread.finished.connect(self._thread_finished)
        self._thread = thread
        self._worker = worker
        self.busy_changed.emit(True)
        thread.start()
        return True

    def shutdown(self) -> None:
        """Wait for bounded diagnostic preflight before destroying Qt objects."""

        thread = self._thread
        shutdown_worker_thread(thread)
        self._thread = None
        self._worker = None

    @Slot()
    def _thread_finished(self) -> None:
        self._thread = None
        self._worker = None
        self.busy_changed.emit(False)

    @Slot(object)
    def _forward_progress(self, event: object) -> None:
        self.progress.emit(event)

    @Slot(object, object)
    def _forward_finished(self, request: object, report: object) -> None:
        self.finished.emit(request, report)

    @Slot(object, str)
    def _forward_failed(self, request: object, message: str) -> None:
        self.failed.emit(request, message)
