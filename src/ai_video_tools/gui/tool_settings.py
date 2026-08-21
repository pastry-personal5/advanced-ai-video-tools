"""Native external-tool settings with asynchronous launch validation."""

# PySide6 exposes Qt types dynamically, which Pylint cannot introspect.
# pylint: disable=no-name-in-module

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from loguru import logger
from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from ai_video_tools.core.models import ToolOverrides, Toolchain
from ai_video_tools.system.settings import ApplicationSettings, SettingsError, SettingsStore
from ai_video_tools.system.tools import ToolDiscovery, ToolDiscoveryError


class _ToolValidationWorker(QObject):
    succeeded = Signal(object, object)
    failed = Signal(object, str)

    def __init__(self, overrides: ToolOverrides, discovery: ToolDiscovery) -> None:
        super().__init__()
        self._overrides = overrides
        self._discovery = discovery

    @Slot()
    def run(self) -> None:
        """Resolve and launch every configured prerequisite off the GUI thread."""

        try:
            toolchain = self._discovery.discover(self._overrides)
        except ToolDiscoveryError as error:
            self.failed.emit(self._overrides, str(error))
            return
        except Exception as error:  # pylint: disable=broad-exception-caught
            logger.opt(exception=error).error("Tool-settings validation failed unexpectedly")
            self.failed.emit(self._overrides, f"Tool validation failed unexpectedly: {error}")
            return
        self.succeeded.emit(self._overrides, toolchain)


class ToolSettingsValidator(QObject):
    """Own at most one external-tool validation thread at a time."""

    succeeded = Signal(object, object)
    failed = Signal(object, str)
    busy_changed = Signal(bool)

    def __init__(self, discovery: ToolDiscovery | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._discovery = discovery or ToolDiscovery()
        self._thread: QThread | None = None
        self._worker: _ToolValidationWorker | None = None

    @property
    def busy(self) -> bool:
        """Whether a bounded validation is currently running."""

        return self._thread is not None

    def start(self, overrides: ToolOverrides) -> bool:
        """Validate one immutable override set without blocking Qt."""

        if self.busy:
            return False
        thread = QThread(self)
        worker = _ToolValidationWorker(overrides, self._discovery)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.succeeded.connect(self._forward_success, Qt.ConnectionType.QueuedConnection)
        worker.failed.connect(self._forward_failure, Qt.ConnectionType.QueuedConnection)
        worker.succeeded.connect(thread.quit, Qt.ConnectionType.DirectConnection)
        worker.failed.connect(thread.quit, Qt.ConnectionType.DirectConnection)
        worker.succeeded.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(self._thread_finished)
        thread.finished.connect(thread.deleteLater)
        self._thread = thread
        self._worker = worker
        self.busy_changed.emit(True)
        thread.start()
        return True

    def shutdown(self) -> None:
        """Wait for bounded validation before destroying its Qt objects."""

        thread = self._thread
        if thread is not None and thread.isRunning():
            thread.quit()
            thread.wait()
        self._thread = None
        self._worker = None

    @Slot()
    def _thread_finished(self) -> None:
        self._thread = None
        self._worker = None
        self.busy_changed.emit(False)

    @Slot(object, object)
    def _forward_success(self, overrides: object, toolchain: object) -> None:
        self.succeeded.emit(overrides, toolchain)

    @Slot(object, str)
    def _forward_failure(self, overrides: object, message: str) -> None:
        self.failed.emit(overrides, message)


class ToolSettingsDialog(QDialog):
    """Edit overrides, prove them usable, then atomically persist them."""

    settings_saved = Signal(object)

    def __init__(self, settings: ApplicationSettings, validator: ToolSettingsValidator, settings_store: SettingsStore, parent: QWidget | None = None) -> None:
        # Declarative widget construction is intentionally kept together.
        # pylint: disable=too-many-statements
        super().__init__(parent)
        self._settings = settings
        self._validator = validator
        self._settings_store = settings_store
        self._path_controls: list[QWidget] = []
        self.setWindowTitle("External tools")
        self.setMinimumWidth(760)

        explanation = QLabel("Leave an executable blank to resolve it from PATH. Leave the model directory blank to use the models directory beside Real-ESRGAN. Validation includes a small Vulkan inference test.")
        explanation.setWordWrap(True)

        self.ffmpeg = QLineEdit(self._path_text(settings.tools.ffmpeg))
        self.ffmpeg.setObjectName("ffmpegPath")
        ffmpeg_row = self._executable_row(self.ffmpeg, "Choose FFmpeg", "usePathFfmpegButton")
        self.ffprobe = QLineEdit(self._path_text(settings.tools.ffprobe))
        self.ffprobe.setObjectName("ffprobePath")
        ffprobe_row = self._executable_row(self.ffprobe, "Choose FFprobe", "usePathFfprobeButton")
        self.realesrgan = QLineEdit(self._path_text(settings.tools.realesrgan))
        self.realesrgan.setObjectName("realesrganPath")
        realesrgan_row = self._executable_row(self.realesrgan, "Choose Real-ESRGAN", "usePathRealesrganButton")

        self.model_directory = QLineEdit(self._path_text(settings.tools.model_directory))
        self.model_directory.setObjectName("modelDirectoryPath")
        choose_models = QPushButton("Choose…")
        choose_models.setObjectName("chooseModelDirectoryButton")
        choose_models.clicked.connect(self._choose_model_directory)
        automatic_models = QPushButton("Automatic")
        automatic_models.setObjectName("automaticModelDirectoryButton")
        automatic_models.clicked.connect(self.model_directory.clear)
        self._path_controls.extend((choose_models, automatic_models))
        model_row = QHBoxLayout()
        model_row.addWidget(self.model_directory, 1)
        model_row.addWidget(choose_models)
        model_row.addWidget(automatic_models)

        form = QFormLayout()
        form.addRow("FFmpeg", ffmpeg_row)
        form.addRow("FFprobe", ffprobe_row)
        form.addRow("Real-ESRGAN", realesrgan_row)
        form.addRow("Model directory", model_row)

        self.status = QLabel("Changes are saved only after every tool passes validation.")
        self.status.setObjectName("toolSettingsStatus")
        self.status.setWordWrap(True)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.save_button = self.buttons.addButton("Validate & Save", QDialogButtonBox.ButtonRole.AcceptRole)
        self.save_button.setObjectName("validateAndSaveToolsButton")
        self.buttons.rejected.connect(self.reject)
        self.save_button.clicked.connect(self._validate)

        layout = QVBoxLayout()
        layout.addWidget(explanation)
        layout.addLayout(form)
        layout.addWidget(self.status)
        layout.addWidget(self.buttons)
        self.setLayout(layout)

        validator.succeeded.connect(self._validation_succeeded)
        validator.failed.connect(self._validation_failed)
        validator.busy_changed.connect(self._set_busy)
        self._set_busy(validator.busy)

    @staticmethod
    def _path_text(path: Path | None) -> str:
        return str(path) if path is not None else ""

    def overrides(self) -> ToolOverrides:
        """Return the current fields as typed optional paths."""

        def optional_path(field: QLineEdit) -> Path | None:
            value = field.text().strip()
            return Path(value).expanduser() if value else None

        return ToolOverrides(optional_path(self.ffmpeg), optional_path(self.ffprobe), optional_path(self.realesrgan), optional_path(self.model_directory))

    def _executable_row(self, field: QLineEdit, caption: str, reset_name: str) -> QHBoxLayout:
        choose = QPushButton("Choose…")
        choose.clicked.connect(lambda: self._choose_executable(field, caption))
        use_path = QPushButton("Use PATH")
        use_path.setObjectName(reset_name)
        use_path.clicked.connect(field.clear)
        self._path_controls.extend((choose, use_path))
        row = QHBoxLayout()
        row.addWidget(field, 1)
        row.addWidget(choose)
        row.addWidget(use_path)
        return row

    def _choose_executable(self, field: QLineEdit, caption: str) -> None:
        selected, _filter = QFileDialog.getOpenFileName(self, caption, field.text().strip(), "All files (*)")
        if selected:
            field.setText(selected)

    @Slot()
    def _choose_model_directory(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Choose Real-ESRGAN model directory", self.model_directory.text().strip())
        if selected:
            self.model_directory.setText(selected)

    @Slot()
    def _validate(self) -> None:
        overrides = self.overrides()
        if not self._validator.start(overrides):
            self.status.setText("Another tool validation is already running.")
            return
        self.status.setText("Validating executables, model files, and Vulkan inference…")

    @Slot(object, object)
    def _validation_succeeded(self, overrides_value: object, toolchain_value: object) -> None:
        if not isinstance(overrides_value, ToolOverrides) or not isinstance(toolchain_value, Toolchain):
            self.status.setText("Tool validation returned an invalid result.")
            return
        updated = replace(self._settings, tools=overrides_value)
        try:
            self._settings_store.save(updated)
        except SettingsError as error:
            logger.warning("Validated tool settings could not be saved: {}", error)
            self.status.setText(f"Tools passed validation, but settings could not be saved: {error}")
            return
        self._settings = updated
        self.settings_saved.emit(updated)
        self.accept()

    @Slot(object, str)
    def _validation_failed(self, overrides_value: object, message: str) -> None:
        if isinstance(overrides_value, ToolOverrides):
            self.status.setText(f"Validation failed: {message}")

    @Slot(bool)
    def _set_busy(self, busy: bool) -> None:
        for widget in (self.ffmpeg, self.ffprobe, self.realesrgan, self.model_directory, self.buttons, *self._path_controls):
            widget.setEnabled(not busy)

    def closeEvent(self, event: QCloseEvent) -> None:  # pylint: disable=invalid-name
        """Keep the dialog and its signal targets alive during validation."""

        if self._validator.busy:
            event.ignore()
            return
        super().closeEvent(event)
