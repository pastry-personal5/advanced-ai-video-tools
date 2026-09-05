"""PySide6 application bootstrap and owned GUI service lifetime."""

# PySide6 exposes Qt types dynamically, which Pylint cannot introspect.
# pylint: disable=no-name-in-module

from __future__ import annotations

import signal
from dataclasses import dataclass
from pathlib import Path
from types import FrameType

from loguru import logger

from PySide6.QtCore import QCoreApplication, QLockFile, QStandardPaths, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from advanced_ai_video_tools.gui.jobs import JobListModel, QueueSnapshotBridge
from advanced_ai_video_tools.gui.identity import GUI_DISPLAY_NAME, GUI_MENU_NAME, GUI_ORGANIZATION_NAME
from advanced_ai_video_tools.identity import IDENTITY
from advanced_ai_video_tools.gui.preflight import GuiPreflightController
from advanced_ai_video_tools.gui.submission import JobSubmissionController
from advanced_ai_video_tools.gui.theme import apply_dark_theme
from advanced_ai_video_tools.gui.preferences import ToolSettingsValidator
from advanced_ai_video_tools.gui.window import MainWindow
from advanced_ai_video_tools.services.pipeline import PipelineService
from advanced_ai_video_tools.services.queue import JobQueue, PipelineRunner
from advanced_ai_video_tools.system.diagnostics import current_log_path
from advanced_ai_video_tools.system.settings import ApplicationSettings, SettingsError, SettingsStore


def _single_instance_lock() -> QLockFile:
    """Return the process lock used to enforce one GUI instance."""

    directory = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.TempLocation))
    lock = QLockFile(str(directory / IDENTITY.gui_lock_filename))
    lock.setStaleLockTime(30_000)
    return lock


class _GuiSigintBridge:
    """Route terminal Ctrl+C through the GUI's normal close lifecycle."""

    def __init__(self, application: QApplication, window: MainWindow) -> None:
        self._application = application
        self._window = window
        self._timer = QTimer(application)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._close_when_requested)
        self._previous_handler: object | None = None
        self._installed = False
        self._shutdown_requested = False
        self._shutdown_started = False

    def install(self) -> None:
        """Install a SIGINT flag handler and keep Python signal delivery active."""

        if self._installed:
            return
        self._previous_handler = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, self._request_shutdown)
        self._installed = True
        self._timer.start()

    def uninstall(self) -> None:
        """Restore the caller's SIGINT behavior after the Qt event loop exits."""

        if not self._installed:
            return
        self._timer.stop()
        signal.signal(signal.SIGINT, self._previous_handler)  # type: ignore[arg-type]
        self._installed = False

    def _request_shutdown(self, _signum: int, _frame: FrameType | None) -> None:
        """Record SIGINT only; Qt performs window work from its event loop."""

        self._shutdown_requested = True

    def _close_when_requested(self) -> None:
        """Close the window once so Qt emits its usual graceful-exit signals."""

        if not self._shutdown_requested or self._shutdown_started:
            return
        self._shutdown_started = True
        self._timer.stop()
        logger.info("Received Ctrl+C; requesting graceful GUI shutdown")
        self._window.close()
        self._application.quit()


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
    settings_report = store.load_report()
    settings = settings_report.settings
    bridge = QueueSnapshotBridge()
    queue = JobQueue(runner or PipelineService(), event_callback=bridge.forward)
    preview = GuiPreflightController()
    tool_validator = ToolSettingsValidator()
    try:
        model = JobListModel(queue, bridge)
        submission = JobSubmissionController(queue, preview, settings, store)
        window = MainWindow(model, settings, current_log_path(), submission=submission, tool_validator=tool_validator, settings_store=store)
        for warning in settings_report.warnings:
            window._append_global_message(warning)  # pylint: disable=protected-access
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
    application = QApplication([GUI_MENU_NAME, *(arguments or [])])
    apply_dark_theme(application)
    instance_lock = _single_instance_lock()
    if not instance_lock.tryLock(0):
        QMessageBox.warning(None, GUI_DISPLAY_NAME, f"{GUI_DISPLAY_NAME} is already running.")
        return 1
    application.setOrganizationName(GUI_ORGANIZATION_NAME)
    # Set the application name explicitly so macOS does not derive the menu
    # title from the Python interpreter executable (for example, "python3").
    application.setApplicationName(GUI_MENU_NAME)
    application.setApplicationDisplayName(GUI_MENU_NAME)
    try:
        runtime = create_gui_runtime()
    except SettingsError as error:
        logger.error("GUI startup failed while loading settings: {}", error)
        QMessageBox.critical(None, GUI_DISPLAY_NAME, f"Could not load application settings:\n{error}")
        instance_lock.unlock()
        return 1
    sigint_bridge = _GuiSigintBridge(application, runtime.window)
    application.aboutToQuit.connect(runtime.shutdown)
    try:
        sigint_bridge.install()
        runtime.window.show()
        return application.exec()
    finally:
        # Leave the cooperative handler installed until every worker and
        # preview resource has finished its own shutdown. A second Ctrl+C must
        # never restore Python's abrupt KeyboardInterrupt behavior mid-cleanup.
        try:
            runtime.shutdown()
        finally:
            try:
                sigint_bridge.uninstall()
            finally:
                instance_lock.unlock()
