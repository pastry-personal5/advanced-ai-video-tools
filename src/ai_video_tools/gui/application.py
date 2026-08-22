"""PySide6 application bootstrap and owned GUI service lifetime."""

# PySide6 exposes Qt types dynamically, which Pylint cannot introspect.
# pylint: disable=no-name-in-module

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from PySide6.QtCore import QCoreApplication, QLockFile, QStandardPaths
from PySide6.QtWidgets import QApplication, QMessageBox

from ai_video_tools.gui.jobs import JobListModel, QueueSnapshotBridge
from ai_video_tools.gui.preflight import GuiPreflightController
from ai_video_tools.gui.submission import JobSubmissionController
from ai_video_tools.gui.tool_settings import ToolSettingsValidator
from ai_video_tools.gui.window import MainWindow
from ai_video_tools.services.pipeline import PipelineService
from ai_video_tools.services.queue import JobQueue, PipelineRunner
from ai_video_tools.system.diagnostics import current_log_path
from ai_video_tools.system.settings import ApplicationSettings, SettingsError, SettingsStore


def _single_instance_lock() -> QLockFile:
    """Return the process lock used to enforce one GUI instance."""

    directory = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.TempLocation))
    lock = QLockFile(str(directory / "ai-video-tools-gui.lock"))
    lock.setStaleLockTime(30_000)
    return lock


@dataclass
class GuiRuntime:
    """Strong ownership of services and Qt objects for one desktop session."""

    settings: ApplicationSettings
    bridge: QueueSnapshotBridge
    queue: JobQueue
    model: JobListModel
    preview: GuiPreflightController
    submission: JobSubmissionController
    tool_validator: ToolSettingsValidator
    window: MainWindow

    def shutdown(self) -> None:
        """Cancel unfinished work and join the queue worker before exit."""

        self.preview.shutdown()
        self.tool_validator.shutdown()
        if not self.queue.shutdown():
            logger.error("GUI queue worker did not stop during shutdown")


def create_gui_runtime(*, runner: PipelineRunner | None = None, settings_store: SettingsStore | None = None) -> GuiRuntime:
    """Compose settings, backend queue, Qt model, and main window."""

    if not isinstance(QCoreApplication.instance(), QApplication):
        raise RuntimeError("QApplication must exist before creating GUI objects")
    store = settings_store or SettingsStore()
    settings = store.load()
    bridge = QueueSnapshotBridge()
    queue = JobQueue(runner or PipelineService(), event_callback=bridge.forward)
    preview = GuiPreflightController()
    tool_validator = ToolSettingsValidator()
    try:
        model = JobListModel(queue, bridge)
        submission = JobSubmissionController(queue, preview, settings, store)
        window = MainWindow(model, settings, current_log_path(), submission=submission, tool_validator=tool_validator, settings_store=store)
        submission.set_dialog_parent(window)
    except Exception:
        preview.shutdown()
        tool_validator.shutdown()
        queue.shutdown()
        raise
    return GuiRuntime(settings, bridge, queue, model, preview, submission, tool_validator, window)


def run_gui(arguments: list[str] | None = None) -> int:
    """Create and execute the native desktop application."""

    existing = QCoreApplication.instance()
    if existing is not None:
        raise RuntimeError("the GUI entry point requires ownership of the Qt application")
    application = QApplication(["ai-video-tools", *(arguments or [])])
    instance_lock = _single_instance_lock()
    if not instance_lock.tryLock(0):
        QMessageBox.warning(None, "AI Video Tools", "AI Video Tools is already running.")
        return 1
    application.setOrganizationName("AI Video Tools")
    application.setApplicationName("AI Video Tools")
    application.setApplicationDisplayName("AI Video Tools")
    try:
        runtime = create_gui_runtime()
    except SettingsError as error:
        logger.error("GUI startup failed while loading settings: {}", error)
        QMessageBox.critical(None, "AI Video Tools", f"Could not load application settings:\n{error}")
        instance_lock.unlock()
        return 1
    application.aboutToQuit.connect(runtime.shutdown)
    runtime.window.show()
    try:
        return application.exec()
    finally:
        runtime.shutdown()
        instance_lock.unlock()
