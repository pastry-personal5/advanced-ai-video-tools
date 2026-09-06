"""Unified application settings dialog and asynchronous tool validation."""

# PySide6 exposes Qt types dynamically, which Pylint cannot introspect. The
# dialog, its two embedded pages, and their validation coordinator stay in one
# explicit boundary because they share one atomic draft lifecycle.
# pylint: disable=no-name-in-module,too-many-lines

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path

from loguru import logger
from PySide6.QtCore import QObject, QSize, Qt, QThread, Signal, Slot
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence, QShowEvent
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from advanced_ai_video_tools.core.models import ToolInfo, ToolOverrides, Toolchain
from advanced_ai_video_tools.gui.theme import CONTROL_HEIGHT, SPACE_2, SPACE_3, SPACE_4
from advanced_ai_video_tools.gui.worker_lifecycle import connect_completion_cleanup, shutdown_worker_thread
from advanced_ai_video_tools.system.settings import DEFAULT_DELETION_RULES, ApplicationSettings, DeletionRule, SettingsError, SettingsStore
from advanced_ai_video_tools.system.tools import ToolDiscovery, ToolDiscoveryError


class _ExternalToolsValidationWorker(QObject):
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
            logger.opt(exception=error).error("External-tools validation failed unexpectedly")
            self.failed.emit(self._overrides, f"Tool validation failed unexpectedly: {error}")
            return
        self.succeeded.emit(self._overrides, toolchain)


class ExternalToolsValidator(QObject):
    """Own at most one external-tool validation thread at a time."""

    succeeded = Signal(object, object)
    failed = Signal(object, str)
    busy_changed = Signal(bool)

    def __init__(self, discovery: ToolDiscovery | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._discovery = discovery or ToolDiscovery()
        self._thread: QThread | None = None
        self._worker: _ExternalToolsValidationWorker | None = None

    @property
    def busy(self) -> bool:
        """Whether a bounded validation is currently running."""

        return self._thread is not None

    def begin_validation(self, overrides: ToolOverrides) -> bool:
        """Validate one immutable override set without blocking Qt."""

        if self.busy:
            return False
        thread = QThread(self)
        worker = _ExternalToolsValidationWorker(overrides, self._discovery)
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


def _toolchain_summary(value: object) -> str | None:
    """Return a display summary only for a completely typed toolchain."""

    if not isinstance(value, Toolchain):
        return None
    tools = (value.ffmpeg, value.ffprobe, value.realesrgan)
    if any(not isinstance(tool, ToolInfo) or not isinstance(tool.path, Path) or not isinstance(tool.version, str) for tool in tools) or not isinstance(value.model_directory, Path):
        return None
    return "Resolved tools: " f"FFmpeg {value.ffmpeg.path}; FFprobe {value.ffprobe.path}; " f"Real-ESRGAN {value.realesrgan.path}; models {value.model_directory}."


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
        self.preview.setWordWrap(True)
        self.status = QLabel()
        self.status.setObjectName("deletionRuleValidation")
        self.status.setAccessibleName("Deletion rule validation status")
        self.status.setWordWrap(True)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.save_button = buttons.addButton("Save Rule", QDialogButtonBox.ButtonRole.AcceptRole)
        self.save_button.setObjectName("saveDeletionRuleButton")
        self.save_button.clicked.connect(self._accept_if_valid)
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
        target_error = next((message for pattern in targets if (message := validate_deletion_pattern(pattern, target=True))), None)
        target_error = "Enter one or more target patterns." if not targets else target_error
        error = source_error or target_error
        self._show_field_error(self.source, source_error)
        self._show_field_error(self.targets, target_error)
        self.status.setText(error or "Valid basename-only rule.")
        self.save_button.setEnabled(error is None)
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

    @staticmethod
    def _show_field_error(field: QWidget, message: str | None) -> None:
        field.setProperty("validationError", message is not None)
        field.setAccessibleDescription(message or "")
        field.setToolTip(message or "")
        field.style().unpolish(field)
        field.style().polish(field)

    def _accept_if_valid(self) -> None:
        if self._validate():
            self.accept()


class FileSettingsPage(QWidget):
    """Edit ordered GUI-only related-file Trash rules as one local draft."""

    draft_changed = Signal()

    def __init__(self, settings: ApplicationSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("fileSettingsPage")
        self._rendering = False
        self._original_deletion_rules = settings.deletion_rules
        self._rules = list(settings.deletion_rules if settings.deletion_rules is not None else DEFAULT_DELETION_RULES)

        heading = QLabel("Automatic File Deletion Rules")
        heading.setObjectName("settingsPageHeading")
        explanation = QLabel("After a source clip is moved to Trash, the first enabled matching rule can also move eligible immediate sibling files. Changes are applied only when Settings is saved.")
        explanation.setWordWrap(True)
        self.rules = QListWidget()
        self.rules.setObjectName("deletionRulesList")
        self.rules.setMinimumHeight(240)
        self.rules.setAccessibleName("Automatic file deletion rules")

        self.add_button = QPushButton("Add")
        self.edit_button = QPushButton("Edit")
        self.delete_button = QPushButton("Delete")
        self.enable_button = QPushButton("Enable/Disable")
        self.up_button = QPushButton("Move Up")
        self.down_button = QPushButton("Move Down")
        self.restore_button = QPushButton("Restore Built-in Defaults")
        first_controls = QHBoxLayout()
        first_controls.setSpacing(SPACE_2)
        for button in (self.add_button, self.edit_button, self.delete_button, self.enable_button):
            first_controls.addWidget(button)
        first_controls.addStretch(1)
        second_controls = QHBoxLayout()
        second_controls.setSpacing(SPACE_2)
        second_controls.addWidget(self.up_button)
        second_controls.addWidget(self.down_button)
        second_controls.addStretch(1)
        second_controls.addWidget(self.restore_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE_4, SPACE_4, SPACE_4, SPACE_4)
        layout.setSpacing(SPACE_3)
        layout.addWidget(heading)
        layout.addWidget(explanation)
        layout.addWidget(self.rules, 1)
        layout.addLayout(first_controls)
        layout.addLayout(second_controls)

        self.add_button.clicked.connect(self._add)
        self.edit_button.clicked.connect(self._edit)
        self.delete_button.clicked.connect(self._delete)
        self.enable_button.clicked.connect(self._toggle)
        self.up_button.clicked.connect(lambda: self._move(-1))
        self.down_button.clicked.connect(lambda: self._move(1))
        self.restore_button.clicked.connect(self._restore)
        self.rules.itemChanged.connect(self._item_changed)
        self.rules.currentRowChanged.connect(lambda _row: self._update_controls())
        self._render()

    def deletion_rules(self) -> tuple[DeletionRule, ...]:
        """Return the page's complete ordered rule draft."""

        return tuple(self._rules)

    def settings_value(self) -> tuple[DeletionRule, ...] | None:
        """Preserve the nullable built-in-default representation until edited."""

        original_effective = self._original_deletion_rules if self._original_deletion_rules is not None else DEFAULT_DELETION_RULES
        return self._original_deletion_rules if self.deletion_rules() == tuple(original_effective) else self.deletion_rules()

    def _render(self, selected_row: int | None = None) -> None:
        self._rendering = True
        self.rules.clear()
        for rule in self._rules:
            item = QListWidgetItem(f"{'Enabled' if rule.enabled else 'Disabled'} — {rule.source_pattern} → {', '.join(rule.target_patterns)}")
            item.setCheckState(Qt.CheckState.Checked if rule.enabled else Qt.CheckState.Unchecked)
            item.setToolTip(item.text())
            self.rules.addItem(item)
        self._rendering = False
        if selected_row is not None and self._rules:
            self.rules.setCurrentRow(min(selected_row, len(self._rules) - 1))
        self._update_controls()

    def _changed(self) -> None:
        self._update_controls()
        self.draft_changed.emit()

    def _update_controls(self) -> None:
        row = self.rules.currentRow()
        selected = 0 <= row < len(self._rules)
        self.edit_button.setEnabled(selected)
        self.delete_button.setEnabled(selected)
        self.enable_button.setEnabled(selected)
        self.up_button.setEnabled(selected and row > 0)
        self.down_button.setEnabled(selected and row + 1 < len(self._rules))

    def _item_changed(self, item: QListWidgetItem) -> None:
        if self._rendering:
            return
        row = self.rules.row(item)
        if 0 <= row < len(self._rules):
            rule = self._rules[row]
            enabled = item.checkState() == Qt.CheckState.Checked
            if enabled != rule.enabled:
                self._rules[row] = DeletionRule(rule.source_pattern, rule.target_patterns, enabled)
                item.setText(f"{'Enabled' if enabled else 'Disabled'} — {rule.source_pattern} → {', '.join(rule.target_patterns)}")
                item.setToolTip(item.text())
                self._changed()

    def _add(self) -> None:
        dialog = DeletionRuleDialog(parent=self)
        if dialog.exec() == int(QDialog.DialogCode.Accepted):
            self._rules.append(dialog.rule())
            self._render(len(self._rules) - 1)
            self._changed()

    def _edit(self) -> None:
        row = self.rules.currentRow()
        if row < 0:
            return
        dialog = DeletionRuleDialog(self._rules[row], self)
        if dialog.exec() == int(QDialog.DialogCode.Accepted):
            edited = dialog.rule()
            self._rules[row] = DeletionRule(edited.source_pattern, edited.target_patterns, self._rules[row].enabled)
            self._render(row)
            self._changed()

    def _delete(self) -> None:
        row = self.rules.currentRow()
        if row >= 0:
            self._rules.pop(row)
            self._render(row)
            self._changed()

    def _toggle(self) -> None:
        row = self.rules.currentRow()
        if row >= 0:
            rule = self._rules[row]
            self._rules[row] = DeletionRule(rule.source_pattern, rule.target_patterns, not rule.enabled)
            self._render(row)
            self._changed()

    def _move(self, offset: int) -> None:
        row = self.rules.currentRow()
        target = row + offset
        if 0 <= row < len(self._rules) and 0 <= target < len(self._rules):
            self._rules[row], self._rules[target] = self._rules[target], self._rules[row]
            self._render(target)
            self._changed()

    def _restore(self) -> None:
        self._rules = list(DEFAULT_DELETION_RULES)
        self._render(0)
        self._changed()


class ExternalToolsPage(QWidget):
    """Edit one coherent external-tool override draft."""

    draft_changed = Signal()
    validation_requested = Signal()

    def __init__(self, settings: ApplicationSettings, parent: QWidget | None = None) -> None:
        # Declarative widget construction is intentionally kept together.
        # pylint: disable=too-many-statements
        super().__init__(parent)
        self.setObjectName("externalToolsPage")
        self._path_controls: list[QWidget] = []
        self._validator_busy = False
        self._commit_locked = False

        heading = QLabel("External Tools")
        heading.setObjectName("settingsPageHeading")
        explanation = QLabel("Leave an executable blank to resolve it from PATH. Leave the model directory blank to use the models directory beside Real-ESRGAN. Validation includes a small Vulkan inference test.")
        explanation.setWordWrap(True)

        self.ffmpeg = QLineEdit(self._path_text(settings.tools.ffmpeg))
        self.ffmpeg.setObjectName("ffmpegPath")
        self.ffmpeg.setAccessibleName("FFmpeg executable path")
        ffmpeg_row = self._executable_row(self.ffmpeg, "Choose FFmpeg", "usePathFfmpegButton")
        self.ffprobe = QLineEdit(self._path_text(settings.tools.ffprobe))
        self.ffprobe.setObjectName("ffprobePath")
        self.ffprobe.setAccessibleName("FFprobe executable path")
        ffprobe_row = self._executable_row(self.ffprobe, "Choose FFprobe", "usePathFfprobeButton")
        self.realesrgan = QLineEdit(self._path_text(settings.tools.realesrgan))
        self.realesrgan.setObjectName("realesrganPath")
        self.realesrgan.setAccessibleName("Real-ESRGAN executable path")
        realesrgan_row = self._executable_row(self.realesrgan, "Choose Real-ESRGAN", "usePathRealesrganButton")
        self.model_directory = QLineEdit(self._path_text(settings.tools.model_directory))
        self.model_directory.setObjectName("modelDirectoryPath")
        self.model_directory.setAccessibleName("Real-ESRGAN model directory")
        self._fields = (self.ffmpeg, self.ffprobe, self.realesrgan, self.model_directory)
        self._validation_error_field: QLineEdit | None = None
        choose_models = QPushButton("Choose…")
        choose_models.setObjectName("chooseModelDirectoryButton")
        choose_models.clicked.connect(self._choose_model_directory)
        automatic_models = QPushButton("Automatic")
        automatic_models.setObjectName("automaticModelDirectoryButton")
        automatic_models.clicked.connect(self.model_directory.clear)
        self._path_controls.extend((choose_models, automatic_models))
        model_row = QHBoxLayout()
        model_row.setSpacing(SPACE_2)
        model_row.addWidget(self.model_directory, 1)
        model_row.addWidget(choose_models)
        model_row.addWidget(automatic_models)

        form = QFormLayout()
        form.setHorizontalSpacing(SPACE_3)
        form.setVerticalSpacing(SPACE_3)
        form.addRow("FFmpeg", ffmpeg_row)
        form.addRow("FFprobe", ffprobe_row)
        form.addRow("Real-ESRGAN", realesrgan_row)
        form.addRow("Model directory", model_row)

        self.status = QLabel("Saved settings have not been changed.")
        self.status.setObjectName("externalToolsValidationStatus")
        self.status.setWordWrap(True)
        self.validation_progress = QLabel()
        self.validation_progress.setObjectName("externalToolsValidationProgress")
        self.validation_progress.setWordWrap(True)
        self.validate_button = QPushButton("Validate")
        self.validate_button.setObjectName("validateExternalToolsButton")
        self.validate_button.clicked.connect(self.validation_requested)
        validation_row = QHBoxLayout()
        validation_row.addWidget(self.validation_progress, 1)
        validation_row.addWidget(self.validate_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE_4, SPACE_4, SPACE_4, SPACE_4)
        layout.setSpacing(SPACE_3)
        layout.addWidget(heading)
        layout.addWidget(explanation)
        layout.addLayout(form)
        layout.addSpacing(SPACE_2)
        layout.addWidget(self.status)
        layout.addLayout(validation_row)
        layout.addStretch(1)

        for field in self._fields:
            field.textChanged.connect(self._field_changed)

    @staticmethod
    def _path_text(path: Path | None) -> str:
        return str(path) if path is not None else ""

    def overrides(self) -> ToolOverrides:
        """Return the current fields as typed optional paths."""

        def optional_path(field: QLineEdit) -> Path | None:
            value = field.text()
            return Path(value) if value.strip() else None

        return ToolOverrides(optional_path(self.ffmpeg), optional_path(self.ffprobe), optional_path(self.realesrgan), optional_path(self.model_directory))

    def structural_error(self) -> tuple[QLineEdit, str] | None:
        """Return the first cheap path-syntax error without touching the filesystem."""

        names = ("FFmpeg", "FFprobe", "Real-ESRGAN", "Model directory")
        for name, field in zip(names, self._fields):
            value = field.text()
            if not value.strip():
                continue
            if "\0" in value:
                return field, f"{name} contains an invalid null character."
            try:
                Path(value).expanduser()
            except RuntimeError:
                return field, f"{name} uses a home-directory shortcut that cannot be resolved."
        return None

    def show_validation_error(self, message: str, field: QLineEdit | None = None) -> QLineEdit:
        """Highlight and describe the field implicated by one validation error."""

        selected = field or self._field_for_validation_message(message)
        self.clear_validation_error()
        self._validation_error_field = selected
        selected.setProperty("validationError", True)
        selected.setAccessibleDescription(message)
        selected.setToolTip(message)
        selected.style().unpolish(selected)
        selected.style().polish(selected)
        return selected

    def clear_validation_error(self) -> None:
        """Remove the previous field-level validation marker, if any."""

        field = self._validation_error_field
        self._validation_error_field = None
        if field is None:
            return
        field.setProperty("validationError", False)
        field.setAccessibleDescription("")
        field.setToolTip("")
        field.style().unpolish(field)
        field.style().polish(field)

    @property
    def validation_error_field(self) -> QLineEdit | None:
        """Return the currently highlighted validation field, if any."""

        return self._validation_error_field

    def set_validator_busy(self, busy: bool, *, inherited: bool = False) -> None:
        """Reflect validator ownership without hiding the page's readable content."""

        self._validator_busy = busy
        self._refresh_enabled()
        if inherited and busy:
            self.status.setText("A validation started by an earlier Settings window is still finishing. Saved tool settings remain unchanged; this page will unlock automatically.")
            self.validation_progress.setText("External-tool validation is running in the background…")
        elif inherited and not busy:
            self.status.setText("Saved settings have not been changed.")
            self.validation_progress.clear()

    def set_commit_locked(self, locked: bool) -> None:
        """Lock or unlock this page for a whole-dialog commit."""

        self._commit_locked = locked
        self._refresh_enabled()

    def set_validation_message(self, message: str, *, validating: bool = False) -> None:
        """Show one inline validation result and its running state."""

        self.status.setText(message)
        self.validation_progress.setText("Validation is running…" if validating else "")
        self.validate_button.setText("Validating…" if validating else "Validate")

    def _refresh_enabled(self) -> None:
        enabled = not self._validator_busy and not self._commit_locked
        for widget in (*self._fields, self.validate_button, *self._path_controls):
            widget.setEnabled(enabled)

    def _field_changed(self) -> None:
        self.clear_validation_error()
        self.draft_changed.emit()

    def _field_for_validation_message(self, message: str) -> QLineEdit:
        normalized = message.casefold()
        if normalized.startswith("real-esrgan model directory"):
            return self.model_directory
        if normalized.startswith("ffprobe ") or normalized.startswith("could not launch ffprobe"):
            return self.ffprobe
        if normalized.startswith(("real-esrgan ", "realesrgan-")) or normalized.startswith("could not launch realesrgan") or "vulkan smoke test" in normalized:
            return self.realesrgan
        return self.ffmpeg

    def _executable_row(self, field: QLineEdit, caption: str, reset_name: str) -> QHBoxLayout:
        choose = QPushButton("Choose…")
        choose.clicked.connect(lambda: self._choose_executable(field, caption))
        use_path = QPushButton("Use PATH")
        use_path.setObjectName(reset_name)
        use_path.clicked.connect(field.clear)
        self._path_controls.extend((choose, use_path))
        row = QHBoxLayout()
        row.setSpacing(SPACE_2)
        row.addWidget(field, 1)
        row.addWidget(choose)
        row.addWidget(use_path)
        return row

    def _choose_executable(self, field: QLineEdit, caption: str) -> None:
        selected, _filter = QFileDialog.getOpenFileName(self, caption, field.text(), "All files (*)")
        if selected:
            field.setText(selected)

    @Slot()
    def _choose_model_directory(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Choose Real-ESRGAN model directory", self.model_directory.text())
        if selected:
            self.model_directory.setText(selected)


class SettingsValidationState(Enum):
    """Observable validation state for one settings leaf page."""

    SAVED = "Saved"
    NEEDS_VALIDATION = "Needs validation"
    VALIDATING = "Validating"
    VALID = "Valid"
    INVALID = "Invalid"


@dataclass
class SettingsDialogSessionState:
    """Non-persisted geometry and navigation state for one GUI runtime."""

    width: int = 1080
    height: int = 720
    sidebar_width: int = 272
    selected_path: tuple[str, str] = ("Editor", "File")


@dataclass(frozen=True)
class _SettingsPageDescriptor:
    path: tuple[str, str]
    keywords: str
    page: QWidget


class SettingsDialog(QDialog):
    """Search, validate, and atomically save all application settings."""

    settings_saved = Signal(object)

    DEFAULT_SIZE = QSize(1080, 720)
    MINIMUM_SIZE = QSize(960, 600)
    SIDEBAR_MINIMUM_WIDTH = 240
    SIDEBAR_MAXIMUM_WIDTH = 360
    FILE_PATH = ("Editor", "File")
    EXTERNAL_TOOLS_PATH = ("Tools", "External Tools")

    def __init__(self, settings: ApplicationSettings, validator: ExternalToolsValidator, settings_store: SettingsStore, session_state: SettingsDialogSessionState | None = None, parent: QWidget | None = None) -> None:
        # Declarative widget construction is intentionally kept together.
        # pylint: disable=too-many-statements
        super().__init__(parent)
        self.setObjectName("settingsDialog")
        self.setWindowTitle("Settings")
        self.setMinimumSize(self.MINIMUM_SIZE)
        self._settings = settings
        self._validator = validator
        self._settings_store = settings_store
        self._session_state = session_state or SettingsDialogSessionState()
        self._validated_tools: ToolOverrides | None = None
        self._pending_tools: ToolOverrides | None = None
        self._commit_after_validation = False
        self._abandoned = False
        self._positioned = False
        self._search_previous_path: tuple[str, str] | None = None
        self._observing_inherited_validation = validator.busy

        initial_size = self._clamped_size(QSize(self._session_state.width, self._session_state.height))
        self.resize(initial_size)

        self.search = QLineEdit()
        self.search.setObjectName("settingsSearch")
        self.search.setAccessibleName("Search settings")
        self.search.setPlaceholderText("Search settings")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedHeight(CONTROL_HEIGHT)

        self.tree = QTreeWidget()
        self.tree.setObjectName("settingsNavigationTree")
        self.tree.setAccessibleName("Settings categories")
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(SPACE_3)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tree.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.tree.setMinimumWidth(self.SIDEBAR_MINIMUM_WIDTH)
        self.tree.setMaximumWidth(self.SIDEBAR_MAXIMUM_WIDTH)
        self.tree.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

        self.file_page = FileSettingsPage(settings)
        self.external_tools_page = ExternalToolsPage(settings)
        self.no_results_page = QLabel("No settings found")
        self.no_results_page.setObjectName("settingsNoResults")
        self.no_results_page.setAlignment(Qt.AlignmentFlag.AlignCenter)

        descriptors = (
            _SettingsPageDescriptor(self.FILE_PATH, "editor file automatic deletion rules related files trash source target pattern add edit delete enable disable move up down reorder restore built-in defaults changes applied settings saved", self.file_page),
            _SettingsPageDescriptor(self.EXTERNAL_TOOLS_PATH, "tools external ffmpeg ffprobe real esrgan realesrgan executable model directory path choose use automatic blank resolve validation validate small vulkan inference", self.external_tools_page),
        )
        self._descriptors = {descriptor.path: descriptor for descriptor in descriptors}
        self._leaf_items: dict[tuple[str, str], QTreeWidgetItem] = {}
        self._category_items: dict[str, QTreeWidgetItem] = {}
        self._scroll_pages: dict[tuple[str, str], QScrollArea] = {}
        self._page_states = {
            self.FILE_PATH: SettingsValidationState.SAVED,
            self.EXTERNAL_TOOLS_PATH: SettingsValidationState.SAVED,
        }

        self.stack = QStackedWidget()
        self.stack.setObjectName("settingsPageStack")
        for descriptor in descriptors:
            category_name, leaf_name = descriptor.path
            category = self._category_items.get(category_name)
            if category is None:
                category = QTreeWidgetItem([category_name])
                category.setFlags(category.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                self.tree.addTopLevelItem(category)
                self._category_items[category_name] = category
            leaf = QTreeWidgetItem([leaf_name])
            leaf.setData(0, Qt.ItemDataRole.UserRole, descriptor.path)
            category.addChild(leaf)
            self._leaf_items[descriptor.path] = leaf
            scroll = QScrollArea()
            scroll.setObjectName(f"{descriptor.page.objectName()}Scroll")
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setWidget(descriptor.page)
            self._scroll_pages[descriptor.path] = scroll
            self.stack.addWidget(scroll)
        self.stack.addWidget(self.no_results_page)
        self.tree.expandAll()

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setObjectName("settingsBodySplitter")
        self.splitter.setHandleWidth(SPACE_2)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(self.tree)
        self.splitter.addWidget(self.stack)
        sidebar_width = min(self.SIDEBAR_MAXIMUM_WIDTH, max(self.SIDEBAR_MINIMUM_WIDTH, self._session_state.sidebar_width))
        self.splitter.setSizes((sidebar_width, max(1, initial_size.width() - sidebar_width - SPACE_2)))
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)

        self.status = QLabel("Settings are unchanged.")
        self.status.setObjectName("settingsStatus")
        self.status.setAccessibleName("Settings status")
        self.status.setWordWrap(True)
        self.status.setMaximumHeight(72)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        self.buttons.setObjectName("settingsDialogButtons")
        self.ok_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.cancel_button = self.buttons.button(QDialogButtonBox.StandardButton.Cancel)
        self.ok_button.setObjectName("saveSettingsButton")
        self.cancel_button.setObjectName("cancelSettingsButton")
        self.ok_button.setMinimumHeight(CONTROL_HEIGHT)
        self.cancel_button.setMinimumHeight(CONTROL_HEIGHT)
        footer = QHBoxLayout()
        footer.setSpacing(SPACE_3)
        footer.addWidget(self.status, 1)
        footer.addWidget(self.buttons)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE_4, SPACE_4, SPACE_4, SPACE_4)
        layout.setSpacing(SPACE_3)
        layout.addWidget(self.search)
        layout.addWidget(self.splitter, 1)
        layout.addLayout(footer)

        self.search.textChanged.connect(self._filter_pages)
        self.tree.itemSelectionChanged.connect(self._selection_changed)
        self.file_page.draft_changed.connect(self._draft_changed)
        self.external_tools_page.draft_changed.connect(self._external_tools_changed)
        self.external_tools_page.validation_requested.connect(lambda: self._begin_external_tools_validation(commit_after=False))
        self.ok_button.clicked.connect(self._commit)
        self.cancel_button.clicked.connect(self._cancel_explicitly)
        validator.succeeded.connect(self._validation_succeeded)
        validator.failed.connect(self._validation_failed)
        validator.busy_changed.connect(self._validator_busy_changed)

        self._refresh_page_labels()
        initial_path = self._session_state.selected_path if self._session_state.selected_path in self._leaf_items else self.FILE_PATH
        self.tree.setCurrentItem(self._leaf_items[initial_path])
        if validator.busy:
            self.external_tools_page.set_validator_busy(True, inherited=True)

    def draft_settings(self) -> ApplicationSettings:
        """Return the complete immutable settings draft represented by both pages."""

        return replace(self._settings, tools=self.external_tools_page.overrides(), deletion_rules=self.file_page.settings_value())

    @property
    def dirty(self) -> bool:
        """Whether the local draft differs from the loaded settings."""

        return self.draft_settings() != self._settings

    @property
    def current_page_path(self) -> tuple[str, str] | None:
        """Return the selected leaf path, or none for an empty search."""

        item = self.tree.currentItem()
        value = item.data(0, Qt.ItemDataRole.UserRole) if item is not None else None
        return value if isinstance(value, tuple) and len(value) == 2 else None

    def _clamped_size(self, requested: QSize) -> QSize:
        screen = self.parentWidget().screen() if self.parentWidget() is not None else QApplication.primaryScreen()
        if screen is None:
            return QSize(max(self.MINIMUM_SIZE.width(), requested.width()), max(self.MINIMUM_SIZE.height(), requested.height()))
        available = screen.availableGeometry()
        if available.width() < self.MINIMUM_SIZE.width() + (SPACE_4 * 2) or available.height() < self.MINIMUM_SIZE.height() + (SPACE_4 * 2):
            return QSize(max(self.MINIMUM_SIZE.width(), requested.width()), max(self.MINIMUM_SIZE.height(), requested.height()))
        maximum_width = max(self.MINIMUM_SIZE.width(), available.width() - (SPACE_4 * 2))
        maximum_height = max(self.MINIMUM_SIZE.height(), available.height() - (SPACE_4 * 2))
        return QSize(min(maximum_width, max(self.MINIMUM_SIZE.width(), requested.width())), min(maximum_height, max(self.MINIMUM_SIZE.height(), requested.height())))

    def _page_scroll(self, path: tuple[str, str]) -> QScrollArea:
        return self._scroll_pages[path]

    def _selection_changed(self) -> None:
        path = self.current_page_path
        if path is None:
            return
        self.stack.setCurrentWidget(self._page_scroll(path))
        self._session_state.selected_path = path

    def _filter_pages(self, query: str) -> None:
        tokens = tuple(token.casefold() for token in query.split() if token)
        if tokens and self._search_previous_path is None:
            self._search_previous_path = self.current_page_path
        matching: list[tuple[str, str]] = []
        for path, descriptor in self._descriptors.items():
            haystack = " ".join((*path, descriptor.keywords)).casefold()
            visible = all(token in haystack for token in tokens)
            self._leaf_items[path].setHidden(not visible)
            if visible:
                matching.append(path)
        for category_name, category in self._category_items.items():
            category.setHidden(not any(path[0] == category_name for path in matching))
            if not category.isHidden():
                category.setExpanded(True)
        current = self.current_page_path
        if not matching:
            self.tree.clearSelection()
            self.stack.setCurrentWidget(self.no_results_page)
        elif not tokens and self._search_previous_path in matching:
            self.tree.setCurrentItem(self._leaf_items[self._search_previous_path])
        elif current not in matching:
            self.tree.setCurrentItem(self._leaf_items[matching[0]])
        if not tokens:
            self._search_previous_path = None

    def _draft_changed(self) -> None:
        self._page_states[self.FILE_PATH] = SettingsValidationState.VALID if self.file_page.settings_value() != self._settings.deletion_rules else SettingsValidationState.SAVED
        self._refresh_page_labels()
        self._refresh_dialog_status()

    def _external_tools_changed(self) -> None:
        overrides = self.external_tools_page.overrides()
        structural_error = self.external_tools_page.structural_error()
        if structural_error is not None:
            field, message = structural_error
            state = SettingsValidationState.INVALID
            self.external_tools_page.show_validation_error(message, field)
            page_message = f"This path cannot be validated: {message} Correct the highlighted field; saved settings are unchanged."
        elif overrides == self._settings.tools:
            state = SettingsValidationState.SAVED
            page_message = "Saved external-tool settings are unchanged."
        elif overrides == self._validated_tools:
            state = SettingsValidationState.VALID
            page_message = "The current external-tool draft passed validation. Select OK to save it."
        else:
            state = SettingsValidationState.NEEDS_VALIDATION
            page_message = "These external-tool changes need validation before they can be saved."
        self._page_states[self.EXTERNAL_TOOLS_PATH] = state
        self.external_tools_page.set_validation_message(page_message)
        self._refresh_page_labels()
        self._refresh_dialog_status()

    def _refresh_dialog_status(self) -> None:
        if not self.dirty:
            self.status.setText("Settings are unchanged.")
        elif self._page_states[self.EXTERNAL_TOOLS_PATH] is SettingsValidationState.INVALID:
            self.status.setText("External Tools contains a validation error. Correct it and try again; saved settings are unchanged.")
        elif self._page_states[self.EXTERNAL_TOOLS_PATH] is SettingsValidationState.NEEDS_VALIDATION:
            self.status.setText("Unsaved changes include external tools that must be validated.")
        else:
            self.status.setText("Settings contain unsaved changes.")

    def _refresh_page_labels(self) -> None:
        priority = {
            SettingsValidationState.INVALID: 4,
            SettingsValidationState.VALIDATING: 3,
            SettingsValidationState.NEEDS_VALIDATION: 2,
            SettingsValidationState.VALID: 1,
            SettingsValidationState.SAVED: 0,
        }
        for path, item in self._leaf_items.items():
            state = self._page_states[path]
            label = f"{path[1]} · {state.value}"
            item.setText(0, label)
            item.setToolTip(0, f"{' → '.join(path)} — {state.value}")
            item.setData(0, Qt.ItemDataRole.AccessibleTextRole, f"{' '.join(path)}, {state.value}")
        for category_name, category in self._category_items.items():
            descendants = [state for path, state in self._page_states.items() if path[0] == category_name]
            aggregate = max(descendants, key=lambda state: priority[state])
            blocking = aggregate in (SettingsValidationState.INVALID, SettingsValidationState.VALIDATING, SettingsValidationState.NEEDS_VALIDATION)
            category.setText(0, f"{category_name} · {aggregate.value}" if blocking else category_name)
            category.setToolTip(0, f"{category_name} — {aggregate.value}")

    def _begin_external_tools_validation(self, *, commit_after: bool) -> None:
        if self._validator.busy:
            self.status.setText("External-tool validation is already running. Other settings remain available.")
            return
        structural_error = self.external_tools_page.structural_error()
        if structural_error is not None:
            field, message = structural_error
            self._pending_tools = None
            self._commit_after_validation = False
            self._page_states[self.EXTERNAL_TOOLS_PATH] = SettingsValidationState.INVALID
            focus = self.external_tools_page.show_validation_error(message, field)
            self.external_tools_page.set_validation_message(f"This path cannot be validated: {message} Correct the highlighted field; saved settings are unchanged.")
            self.status.setText("External Tools contains an invalid path. Saved settings are unchanged.")
            self._refresh_page_labels()
            self._reveal_page(self.EXTERNAL_TOOLS_PATH, focus)
            return
        overrides = self.external_tools_page.overrides()
        self._pending_tools = overrides
        self._commit_after_validation = commit_after
        if commit_after:
            self.file_page.setEnabled(False)
            self.external_tools_page.set_commit_locked(True)
            self.search.setEnabled(False)
            self.ok_button.setEnabled(False)
        self._page_states[self.EXTERNAL_TOOLS_PATH] = SettingsValidationState.VALIDATING
        self.external_tools_page.set_validation_message("Checking executable launchability, model files, and Vulkan inference. Saved settings remain unchanged until every check succeeds.", validating=True)
        self.status.setText("Validating External Tools…")
        self._refresh_page_labels()
        if not self._validator.begin_validation(overrides):
            self._pending_tools = None
            self._commit_after_validation = False
            self._unlock_after_commit()
            self._external_tools_changed()
            self.status.setText("External-tool validation could not start because another validation is running.")

    def _commit(self) -> None:
        draft = self.draft_settings()
        if draft == self._settings:
            self._accept_saved()
            return
        if draft.tools not in (self._settings.tools, self._validated_tools):
            if self._validator.busy and self._pending_tools == draft.tools:
                self._commit_after_validation = True
                self.file_page.setEnabled(False)
                self.external_tools_page.set_commit_locked(True)
                self.search.setEnabled(False)
                self.ok_button.setEnabled(False)
                self.status.setText("Finishing External Tools validation before saving all settings…")
                return
            self._begin_external_tools_validation(commit_after=True)
            return
        self._persist_draft(draft)

    def _persist_draft(self, draft: ApplicationSettings) -> None:
        try:
            self._settings_store.save(draft)
        except SettingsError as error:
            logger.warning("Application settings could not be saved: {}", error)
            self._unlock_after_commit()
            self.status.setText(f"Settings could not be saved. Existing saved settings remain unchanged. Correct the storage problem and try again: {error}")
            return
        self._settings = draft
        self.settings_saved.emit(draft)
        self._accept_saved()

    def _accept_saved(self) -> None:
        self._remember_session()
        super().accept()

    def _unlock_after_commit(self) -> None:
        self.file_page.setEnabled(True)
        self.external_tools_page.set_commit_locked(False)
        self.search.setEnabled(True)
        self.ok_button.setEnabled(True)

    @Slot(object, object)
    def _validation_succeeded(self, value: object, resolved: object) -> None:
        if self._abandoned or not isinstance(value, ToolOverrides) or value != self._pending_tools:
            return
        self._pending_tools = None
        summary = _toolchain_summary(resolved)
        if summary is None and self._validated_tools == value:
            self._validated_tools = None
        if value != self.external_tools_page.overrides():
            self._commit_after_validation = False
            self._unlock_after_commit()
            self._external_tools_changed()
            self.status.setText("The External Tools draft changed during validation. The stale result was ignored; validate the current draft.")
            return
        if summary is None:
            self._commit_after_validation = False
            self._page_states[self.EXTERNAL_TOOLS_PATH] = SettingsValidationState.INVALID
            self._unlock_after_commit()
            self.external_tools_page.clear_validation_error()
            self.external_tools_page.set_validation_message("Validation returned an invalid result. Nothing was saved. Try validation again; if the problem continues, reopen Settings.")
            self.status.setText("External Tools validation returned an invalid result. Saved settings are unchanged.")
            self._refresh_page_labels()
            self._reveal_page(self.EXTERNAL_TOOLS_PATH, self.external_tools_page.validate_button)
            return
        self._validated_tools = value
        self._page_states[self.EXTERNAL_TOOLS_PATH] = SettingsValidationState.VALID if value != self._settings.tools else SettingsValidationState.SAVED
        self.external_tools_page.clear_validation_error()
        self.external_tools_page.set_validation_message(f"Validation succeeded. {summary}")
        self._refresh_page_labels()
        if self._commit_after_validation:
            self._commit_after_validation = False
            self._persist_draft(self.draft_settings())
        elif self.dirty:
            self.status.setText("External Tools is valid. Changes remain unsaved until OK is selected.")
        else:
            self.status.setText("External Tools is valid. Settings are unchanged.")

    @Slot(object, str)
    def _validation_failed(self, value: object, message: str) -> None:
        if self._abandoned or not isinstance(value, ToolOverrides) or value != self._pending_tools:
            return
        self._pending_tools = None
        if self._validated_tools == value:
            self._validated_tools = None
        if value != self.external_tools_page.overrides():
            self._commit_after_validation = False
            self._unlock_after_commit()
            self._external_tools_changed()
            self.status.setText("The External Tools draft changed during validation. The stale failure was ignored; validate the current draft.")
            return
        self._commit_after_validation = False
        self._page_states[self.EXTERNAL_TOOLS_PATH] = SettingsValidationState.INVALID
        self._unlock_after_commit()
        focus = self.external_tools_page.show_validation_error(message)
        self.external_tools_page.set_validation_message(f"Validation failed: {message} Correct the highlighted field or restore automatic discovery, then validate again. Saved settings remain unchanged.")
        self.status.setText("External Tools could not be validated. Saved settings remain unchanged.")
        self._reveal_page(self.EXTERNAL_TOOLS_PATH, focus)
        self._refresh_page_labels()

    @Slot(bool)
    def _validator_busy_changed(self, busy: bool) -> None:
        self.external_tools_page.set_validator_busy(busy)
        if not busy and self._observing_inherited_validation and self._pending_tools is None:
            self._observing_inherited_validation = False
            self.external_tools_page.set_validator_busy(False, inherited=True)
            self._external_tools_changed()
        elif not busy and self._page_states[self.EXTERNAL_TOOLS_PATH] is SettingsValidationState.INVALID:
            field = self.external_tools_page.validation_error_field
            self._reveal_page(self.EXTERNAL_TOOLS_PATH, field or self.external_tools_page.validate_button)

    def _reveal_page(self, path: tuple[str, str], field: QWidget) -> None:
        if self.search.text():
            self.search.clear()
        self.tree.setCurrentItem(self._leaf_items[path])
        self._page_scroll(path).ensureWidgetVisible(field)
        field.setFocus(Qt.FocusReason.OtherFocusReason)

    def _cancel_explicitly(self) -> None:
        self._abandoned = True
        self._remember_session()
        super().reject()

    def _confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        answer = QMessageBox.question(self, "Discard settings changes?", "Discard all unsaved settings changes?", QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)
        return answer == QMessageBox.StandardButton.Discard

    def reject(self) -> None:
        """Treat Escape as a potentially accidental dirty close."""

        if not self._confirm_discard():
            return
        self._abandoned = True
        self._remember_session()
        super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:  # pylint: disable=invalid-name
        """Confirm a dirty title-bar close before discarding the draft."""

        if not self._confirm_discard():
            event.ignore()
            return
        self._abandoned = True
        self._remember_session()
        event.accept()

    def showEvent(self, event: QShowEvent) -> None:  # pylint: disable=invalid-name
        """Center the first presentation and keep supported-screen clearance."""

        super().showEvent(event)
        if self._positioned:
            return
        self._positioned = True
        parent = self.parentWidget()
        screen = parent.screen() if parent is not None else QApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        center = parent.frameGeometry().center() if parent is not None and parent.isVisible() else available.center()
        x_pos = center.x() - (self.width() // 2)
        y_pos = center.y() - (self.height() // 2)
        if available.width() >= self.width() + (SPACE_4 * 2):
            x_pos = min(max(x_pos, available.left() + SPACE_4), available.right() - self.width() - SPACE_4 + 1)
        if available.height() >= self.height() + (SPACE_4 * 2):
            y_pos = min(max(y_pos, available.top() + SPACE_4), available.bottom() - self.height() - SPACE_4 + 1)
        self.move(x_pos, y_pos)

    def _remember_session(self) -> None:
        self._session_state.width = self.width()
        self._session_state.height = self.height()
        self._session_state.sidebar_width = min(self.SIDEBAR_MAXIMUM_WIDTH, max(self.SIDEBAR_MINIMUM_WIDTH, self.tree.width()))
        path = self.current_page_path
        if path is not None:
            self._session_state.selected_path = path


def configure_settings_action(action: QAction) -> None:
    """Keep Settings in Preferences and expose macOS's standard shortcut."""

    action.setMenuRole(QAction.MenuRole.NoRole)
    # Portable syntax renders as Command-, on macOS.
    action.setShortcut(QKeySequence("Meta+,"))
