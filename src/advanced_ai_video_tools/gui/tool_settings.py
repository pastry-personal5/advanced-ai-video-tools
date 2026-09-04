"""Native external-tool settings with asynchronous launch validation."""

# PySide6 exposes Qt types dynamically, which Pylint cannot introspect.
# pylint: disable=no-name-in-module

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from loguru import logger
from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QLineEdit, QMessageBox, QPushButton, QTextEdit, QVBoxLayout, QWidget

from advanced_ai_video_tools.core.models import ToolOverrides, Toolchain
from advanced_ai_video_tools.gui.worker_lifecycle import connect_completion_cleanup, shutdown_worker_thread
from advanced_ai_video_tools.system.settings import DEFAULT_DELETION_RULES, ApplicationSettings, DeletionRule, SettingsError, SettingsStore
from advanced_ai_video_tools.system.tools import ToolDiscovery, ToolDiscoveryError


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

    def begin_validation(self, overrides: ToolOverrides) -> bool:
        """Validate one immutable override set without blocking Qt."""

        if self.busy:
            return False
        thread = QThread(self)
        worker = _ToolValidationWorker(overrides, self._discovery)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.succeeded.connect(self._forward_success, Qt.ConnectionType.QueuedConnection)
        worker.failed.connect(self._forward_failure, Qt.ConnectionType.QueuedConnection)
        connect_completion_cleanup(thread, worker, worker.succeeded, worker.failed)
        thread.finished.connect(self._thread_finished)
        self._thread = thread
        self._worker = worker
        self.busy_changed.emit(True)
        thread.start()
        return True

    def shutdown(self) -> None:
        """Wait for bounded validation before destroying its Qt objects."""

        thread = self._thread
        shutdown_worker_thread(thread)
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


def validate_deletion_pattern(pattern: str, *, target: bool = False) -> str | None:
    """Return a concise validation message for one safe basename glob."""

    try:
        DeletionRule("*.mov", (pattern,)) if target else DeletionRule(pattern, ("placeholder",))
    except (TypeError, ValueError) as error:
        return str(error)
    return None


class DeletionRuleDialog(QDialog):
    """Edit one deletion rule without touching the filesystem."""

    def __init__(self, rule: DeletionRule | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Deletion rule")
        self.source = QLineEdit(rule.source_pattern if rule else "")
        self.source.setObjectName("deletionSourcePattern")
        self.targets = QTextEdit("\n".join(rule.target_patterns) if rule else "")
        self.targets.setObjectName("deletionTargetPatterns")
        self.source_sample = QLineEdit()
        self.source_sample.setObjectName("deletionSourceSampleFilename")
        self.source_sample.setPlaceholderText("Try a source, e.g. foo-bar.mov")
        self.sample = QLineEdit()
        self.sample.setObjectName("deletionSampleFilename")
        self.sample.setPlaceholderText("Try a related file, e.g. foo-bar-last-frame.png")
        self.preview = QLabel()
        self.preview.setObjectName("deletionSamplePreview")
        self.status = QLabel()
        self.status.setObjectName("deletionRuleValidation")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        save = buttons.addButton("Save Rule", QDialogButtonBox.ButtonRole.AcceptRole)
        save.setObjectName("saveDeletionRuleButton")
        save.clicked.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        form = QFormLayout()
        form.addRow("Source pattern", self.source)
        form.addRow("Target patterns", self.targets)
        form.addRow("Sample source filename", self.source_sample)
        form.addRow("Sample related filename", self.sample)
        explanation = QLabel("Patterns match immediate sibling basenames case-insensitively. Target patterns may use {source_stem}, {source_name}, and {source_suffix}; enter one target pattern per line.")
        explanation.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addWidget(explanation)
        layout.addLayout(form)
        layout.addWidget(self.status)
        layout.addWidget(self.preview)
        layout.addWidget(buttons)
        self.source.textChanged.connect(self._validate)
        self.targets.textChanged.connect(self._validate)
        self.source_sample.textChanged.connect(self._validate)
        self.sample.textChanged.connect(self._validate)
        self._validate()

    def rule(self) -> DeletionRule:
        """Return the validated rule represented by the dialog fields."""

        return DeletionRule(self.source.text().strip(), tuple(line.strip() for line in self.targets.toPlainText().splitlines() if line.strip()))

    def _validate(self) -> bool:
        source_error = validate_deletion_pattern(self.source.text().strip())
        targets = tuple(line.strip() for line in self.targets.toPlainText().splitlines() if line.strip())
        target_error = next((validate_deletion_pattern(pattern, target=True) for pattern in targets if validate_deletion_pattern(pattern, target=True)), None)
        error = source_error or ("Enter one or more target patterns." if not targets else target_error)
        self.status.setText(error or "Valid basename-only rule.")
        if error:
            self.preview.setText("Preview unavailable until the rule is valid.")
        else:
            source_sample = self.source_sample.text().strip()
            sample = self.sample.text().strip()
            rule = DeletionRule(self.source.text().strip(), targets)
            if not source_sample or not sample:
                self.preview.setText("Enter source and related sample filenames to preview matching.")
            elif not rule.matches_source(source_sample):
                self.preview.setText("Sample source does not match the source pattern.")
            elif rule.matches_target(source_sample, sample):
                self.preview.setText("Matches a target pattern.")
            else:
                self.preview.setText("Does not match any target pattern.")
        return error is None

    def _accept_if_valid(self) -> None:
        if self._validate():
            self.accept()


class DeletionRulesDialog(QDialog):
    """Ordered editor for GUI-only related-file Trash rules."""

    settings_saved = Signal(object)

    def __init__(self, settings: ApplicationSettings, settings_store: SettingsStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._settings_store = settings_store
        self._rendering = False
        self._rules = list(settings.deletion_rules if settings.deletion_rules is not None else DEFAULT_DELETION_RULES)
        self.setWindowTitle("Related-file deletion rules")
        self.setMinimumWidth(700)
        self.rules = QListWidget()
        self.rules.setObjectName("deletionRulesList")
        self.add_button = QPushButton("Add")
        self.edit_button = QPushButton("Edit")
        self.delete_button = QPushButton("Delete")
        self.enable_button = QPushButton("Enable/Disable")
        self.up_button = QPushButton("Move Up")
        self.down_button = QPushButton("Move Down")
        self.restore_button = QPushButton("Restore Built-in Defaults")
        controls = QHBoxLayout()
        for button in (self.add_button, self.edit_button, self.delete_button, self.enable_button, self.up_button, self.down_button):
            controls.addWidget(button)
        controls.addStretch(1)
        controls.addWidget(self.restore_button)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        save = buttons.addButton("Save", QDialogButtonBox.ButtonRole.AcceptRole)
        save.setObjectName("saveDeletionRulesButton")
        save.clicked.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Rules apply only after a source clip is successfully moved to Trash."))
        layout.addWidget(self.rules)
        layout.addLayout(controls)
        layout.addWidget(buttons)
        self.add_button.clicked.connect(self._add)
        self.edit_button.clicked.connect(self._edit)
        self.delete_button.clicked.connect(self._delete)
        self.enable_button.clicked.connect(self._toggle)
        self.up_button.clicked.connect(lambda: self._move(-1))
        self.down_button.clicked.connect(lambda: self._move(1))
        self.restore_button.clicked.connect(self._restore)
        self.rules.itemChanged.connect(self._item_changed)
        self._render()

    def _render(self) -> None:
        self._rendering = True
        self.rules.clear()
        for rule in self._rules:
            item = QListWidgetItem(f"{'Enabled' if rule.enabled else 'Disabled'} — {rule.source_pattern} → {', '.join(rule.target_patterns)}")
            item.setCheckState(Qt.CheckState.Checked if rule.enabled else Qt.CheckState.Unchecked)
            self.rules.addItem(item)
        self._rendering = False

    def _item_changed(self, item: QListWidgetItem) -> None:
        """Persist direct checkbox enablement into the draft rule list."""

        if self._rendering:
            return
        row = self.rules.row(item)
        if 0 <= row < len(self._rules):
            rule = self._rules[row]
            enabled = item.checkState() == Qt.CheckState.Checked
            if enabled != rule.enabled:
                self._rules[row] = DeletionRule(rule.source_pattern, rule.target_patterns, enabled)
                item.setText(f"{'Enabled' if enabled else 'Disabled'} — {rule.source_pattern} → {', '.join(rule.target_patterns)}")

    def _add(self) -> None:
        dialog = DeletionRuleDialog(parent=self)
        if dialog.exec() == int(QDialog.DialogCode.Accepted):
            self._rules.append(dialog.rule())
            self._render()

    def _edit(self) -> None:
        row = self.rules.currentRow()
        if row < 0:
            return
        dialog = DeletionRuleDialog(self._rules[row], self)
        if dialog.exec() == int(QDialog.DialogCode.Accepted):
            self._rules[row] = DeletionRule(dialog.rule().source_pattern, dialog.rule().target_patterns, self._rules[row].enabled)
            self._render()
            self.rules.setCurrentRow(row)

    def _delete(self) -> None:
        row = self.rules.currentRow()
        if row >= 0:
            self._rules.pop(row)
            self._render()

    def _toggle(self) -> None:
        row = self.rules.currentRow()
        if row >= 0:
            rule = self._rules[row]
            self._rules[row] = DeletionRule(rule.source_pattern, rule.target_patterns, not rule.enabled)
            self._render()
            self.rules.setCurrentRow(row)

    def _move(self, offset: int) -> None:
        row = self.rules.currentRow()
        target = row + offset
        if 0 <= row < len(self._rules) and 0 <= target < len(self._rules):
            self._rules[row], self._rules[target] = self._rules[target], self._rules[row]
            self._render()
            self.rules.setCurrentRow(target)

    def _restore(self) -> None:
        self._rules = list(DEFAULT_DELETION_RULES)
        self._render()

    def _save(self) -> None:
        updated = replace(self._settings, deletion_rules=tuple(self._rules))
        try:
            self._settings_store.save(updated)
        except SettingsError as error:
            QMessageBox.warning(self, "Deletion rules not saved", str(error))
            return
        self._settings = updated
        self.settings_saved.emit(updated)
        self.accept()


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
        self.deletion_button = QPushButton("Edit Related-File Deletion Rules…")
        self.deletion_button.setObjectName("editDeletionRulesButton")
        self.deletion_button.clicked.connect(self._open_deletion_rules)

        layout = QVBoxLayout()
        layout.addWidget(explanation)
        layout.addLayout(form)
        layout.addWidget(self.deletion_button)
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
    def _open_deletion_rules(self) -> None:
        dialog = DeletionRulesDialog(self._settings, self._settings_store, self)
        dialog.settings_saved.connect(self._deletion_rules_saved)
        dialog.exec()

    @Slot(object)
    def _deletion_rules_saved(self, value: object) -> None:
        if isinstance(value, ApplicationSettings):
            self._settings = value
            self.settings_saved.emit(value)

    @Slot()
    def _validate(self) -> None:
        overrides = self.overrides()
        if not self._validator.begin_validation(overrides):
            self.status.setText("Another tool validation is already running.")
            return
        self.status.setText("Validating executables, model files, and Vulkan inference…")

    @Slot(object, object)
    def _validation_succeeded(self, tool_overrides: object, resolved_toolchain: object) -> None:
        if not isinstance(tool_overrides, ToolOverrides) or not isinstance(resolved_toolchain, Toolchain):
            self.status.setText("Tool validation returned an invalid result.")
            return
        updated = replace(self._settings, tools=tool_overrides)
        try:
            self._settings_store.save(updated)
        except SettingsError as error:
            logger.warning("Validated tool settings could not be saved: {}", error)
            self.status.setText(f"Tools passed validation, but settings could not be saved: {error}")
            return
        self._settings = updated
        self.status.setText("Validated and saved. Resolved tools: " f"FFmpeg {resolved_toolchain.ffmpeg.path}; FFprobe {resolved_toolchain.ffprobe.path}; " f"Real-ESRGAN {resolved_toolchain.realesrgan.path}; models {resolved_toolchain.model_directory}.")
        self.settings_saved.emit(updated)
        self.accept()

    @Slot(object, str)
    def _validation_failed(self, tool_overrides: object, message: str) -> None:
        if isinstance(tool_overrides, ToolOverrides):
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
