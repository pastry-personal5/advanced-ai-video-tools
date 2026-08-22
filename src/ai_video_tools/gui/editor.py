"""Native ordered-input editor for one immutable processing request."""

# PySide6 exposes Qt types dynamically, which Pylint cannot introspect.
# pylint: disable=no-name-in-module

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QFileDialog, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QPushButton, QScrollArea, QSizePolicy, QSpinBox, QVBoxLayout, QWidget

from ai_video_tools.core.models import JobRequest
from ai_video_tools.storage.naming import automatic_output_basename
from ai_video_tools.system.settings import ApplicationSettings

_VIDEO_SUFFIXES = frozenset({".mov", ".mp4", ".mkv", ".m4v"})
SOURCE_CLIP_LIST_WIDTH = 623


def _local_now() -> datetime:
    return datetime.now().astimezone()


class JobEditor(QWidget):
    """Collect supported v1 job intent without performing media inspection."""

    request_ready = Signal(object)

    def __init__(self, settings: ApplicationSettings, *, clock: Callable[[], datetime] = _local_now, parent: QWidget | None = None) -> None:
        # Declarative widget construction is intentionally kept together.
        # pylint: disable=too-many-statements
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._settings = settings
        self._clock = clock
        self._paths: list[Path] = []

        self.inputs = QListWidget()
        self.inputs.setObjectName("inputClips")
        self.inputs.setAccessibleName("Ordered input clips")
        self.inputs.setMinimumHeight(100)
        self.inputs.setMaximumWidth(SOURCE_CLIP_LIST_WIDTH)
        self.inputs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.add_button = QPushButton("Add Clips…")
        self.add_button.setObjectName("addClipsButton")
        self.remove_button = QPushButton("Remove")
        self.remove_button.setObjectName("removeClipButton")
        self.input_up_button = QPushButton("Move Up")
        self.input_up_button.setObjectName("inputUpButton")
        self.input_down_button = QPushButton("Move Down")
        self.input_down_button.setObjectName("inputDownButton")

        input_controls = QHBoxLayout()
        input_controls.addWidget(self.add_button)
        input_controls.addWidget(self.remove_button)
        input_controls.addWidget(self.input_up_button)
        input_controls.addWidget(self.input_down_button)
        input_controls.addStretch(1)

        self.output_directory = QLineEdit(str(settings.recent_output_directory or ""))
        self.output_directory.setObjectName("outputDirectory")
        self.output_directory.setPlaceholderText("Choose an output directory")
        self.output_button = QPushButton("Choose…")
        self.output_button.setObjectName("chooseOutputButton")
        output_row = QHBoxLayout()
        output_row.addWidget(self.output_directory, 1)
        output_row.addWidget(self.output_button)

        self.target_height = QSpinBox()
        self.target_height.setObjectName("targetHeight")
        self.target_height.setRange(2, 16384)
        self.target_height.setSingleStep(2)
        self.target_height.setSuffix(" px")
        self.target_height.setValue(settings.target_height)

        model_label = QLabel("realesrgan-x4plus — photographic and live-action images")
        model_label.setObjectName("modelLabel")
        model_label.setWordWrap(True)

        output_group = QGroupBox("Output Directory")
        output_group.setObjectName("outputDirectoryGroup")
        output_group_layout = QVBoxLayout(output_group)
        output_group_layout.addLayout(output_row)
        target_group = QGroupBox("Target Height")
        target_group.setObjectName("targetHeightGroup")
        target_group_layout = QVBoxLayout(target_group)
        target_group_layout.addWidget(self.target_height)
        model_group = QGroupBox("AI Model")
        model_group.setObjectName("aiModelGroup")
        model_group_layout = QVBoxLayout(model_group)
        model_group_layout.addWidget(model_label)

        basic_settings = QGroupBox("Basic Settings")
        basic_settings.setObjectName("basicSettings")
        basic_settings.setFixedWidth(240)
        basic_settings_layout = QVBoxLayout(basic_settings)
        settings_scroll = QScrollArea()
        settings_scroll.setObjectName("basicSettingsScroll")
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        settings_content = QWidget()
        settings_content_layout = QVBoxLayout(settings_content)
        settings_content_layout.addWidget(output_group)
        settings_content_layout.addWidget(target_group)
        settings_content_layout.addWidget(model_group)
        settings_content_layout.addStretch(1)
        settings_scroll.setWidget(settings_content)
        basic_settings_layout.addWidget(settings_scroll)

        self.submit_button = QPushButton("Preflight & Queue")
        self.submit_button.setObjectName("submitJobButton")
        self.submit_button.setDefault(True)
        self.editor_status = QLabel()
        self.editor_status.setObjectName("editorStatus")
        self.editor_status.setWordWrap(True)

        source_group = QGroupBox()
        source_group.setObjectName("sourceClipListGroup")
        group_layout = QVBoxLayout(source_group)
        group_layout.setContentsMargins(2, 9, 9, 9)
        group_layout.addWidget(self.inputs)
        group_layout.addLayout(input_controls)
        submit_row = QHBoxLayout()
        submit_row.addWidget(self.editor_status, 1)
        submit_row.addWidget(self.submit_button)
        group_layout.addLayout(submit_row)
        outer = QVBoxLayout()
        outer.setContentsMargins(0, 0, 0, 0)
        columns = QHBoxLayout()
        columns.setContentsMargins(0, 0, 0, 0)
        columns.addWidget(basic_settings)
        columns.addWidget(source_group)
        outer.addLayout(columns)
        self.setLayout(outer)

        self.add_button.clicked.connect(self._choose_inputs)
        self.remove_button.clicked.connect(self.remove_selected)
        self.input_up_button.clicked.connect(lambda: self.move_selected(-1))
        self.input_down_button.clicked.connect(lambda: self.move_selected(1))
        self.output_button.clicked.connect(self._choose_output_directory)
        self.submit_button.clicked.connect(self._request_submission)
        self.inputs.currentRowChanged.connect(self._update_input_controls)
        self._update_input_controls()

    def input_paths(self) -> tuple[Path, ...]:
        """Return clip paths in their visible concat order."""

        return tuple(self._paths)

    def add_inputs(self, paths: Sequence[Path]) -> None:
        """Append selected paths without silently sorting or deduplicating them."""

        new_paths = tuple(paths)
        first_added_row = len(self._paths)
        for path in new_paths:
            self._paths.append(path)
            self.inputs.addItem(path.name)
        if new_paths:
            self.inputs.setCurrentRow(first_added_row + len(new_paths) - 1)
        self._update_input_controls()

    @staticmethod
    def _local_drop_paths(event: QDragEnterEvent | QDropEvent) -> tuple[Path, ...]:
        """Return only existing local files from one file-manager event."""

        mime = event.mimeData()
        if not mime.hasUrls():
            return ()
        urls = tuple(mime.urls())
        if not urls or any(not url.isLocalFile() for url in urls):
            return ()
        paths = tuple(Path(url.toLocalFile()) for url in urls)
        return tuple(path for path in paths if path.is_file() and path.suffix.lower() in _VIDEO_SUFFIXES)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # pylint: disable=invalid-name
        """Accept only local-file drags; reject URLs and remote sources."""

        if self._local_drop_paths(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:  # pylint: disable=invalid-name
        """Append local files in the operating-system drop order."""

        paths = self._local_drop_paths(event)
        if paths:
            self.add_inputs(paths)
            event.acceptProposedAction()
        else:
            event.ignore()

    @Slot()
    def remove_selected(self) -> None:
        """Remove only the selected input row."""

        row = self.inputs.currentRow()
        if row >= 0:
            self.inputs.takeItem(row)
            self._paths.pop(row)
            self.inputs.setCurrentRow(min(row, self.inputs.count() - 1))
        self._update_input_controls()

    def move_selected(self, offset: int) -> bool:
        """Move the selected clip while preserving every other relative order."""

        row = self.inputs.currentRow()
        destination = row + offset
        if row < 0 or destination < 0 or destination >= self.inputs.count():
            return False
        item = self.inputs.takeItem(row)
        self.inputs.insertItem(destination, item)
        path = self._paths.pop(row)
        self._paths.insert(destination, path)
        self.inputs.setCurrentRow(destination)
        return True

    def build_request(self) -> JobRequest:
        """Freeze one generated-output request for asynchronous preview."""

        inputs = self.input_paths()
        if not inputs:
            raise ValueError("Add at least one input clip.")
        raw_output = self.output_directory.text().strip()
        if not raw_output:
            raise ValueError("Choose an output directory.")
        if self.target_height.value() % 2:
            raise ValueError("Target height must be an even number of pixels.")
        created_at = self._clock()
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError("The system clock must provide a timezone-aware creation time.")
        return JobRequest(
            inputs=inputs,
            output_directory=Path(raw_output),
            target_height=self.target_height.value(),
            acknowledge_dropped_streams=False,
            overwrite_mode=self._settings.overwrite_mode,
            tools=self._settings.tools,
            created_at=created_at,
            generated_output_basename=automatic_output_basename(created_at),
        )

    @Slot(bool)
    def set_busy(self, busy: bool) -> None:
        """Prevent overlapping previews while keeping current intent visible."""

        for widget in (self.inputs, self.add_button, self.remove_button, self.input_up_button, self.input_down_button, self.output_directory, self.output_button, self.target_height, self.submit_button):
            widget.setEnabled(not busy)
        if not busy:
            self._update_input_controls()

    @Slot(str)
    def set_status(self, message: str) -> None:
        """Present concise submission status beside the action button."""

        self.editor_status.setText(message)

    @Slot(object)
    def apply_settings(self, value: object) -> None:
        """Adopt newly persisted non-safety preferences for later drafts."""

        if isinstance(value, ApplicationSettings):
            self._settings = value

    @Slot(str)
    def job_queued(self, _job_id: str) -> None:
        """Clear consumed clip intent while retaining useful output preferences."""

        self.inputs.clear()
        self._paths.clear()
        self._update_input_controls()

    @Slot()
    def _choose_inputs(self) -> None:
        start = str(self._settings.recent_input_directory or "")
        selected, _filter = QFileDialog.getOpenFileNames(self, "Choose input clips in concat order", start, "Video files (*.mov *.mp4 *.mkv *.m4v);;All files (*)")
        self.add_inputs(tuple(Path(path) for path in selected))

    @Slot()
    def _choose_output_directory(self) -> None:
        start = self.output_directory.text().strip() or str(self._settings.recent_output_directory or "")
        selected = QFileDialog.getExistingDirectory(self, "Choose output directory", start)
        if selected:
            self.output_directory.setText(selected)

    @Slot()
    def _request_submission(self) -> None:
        try:
            request = self.build_request()
        except ValueError as error:
            self.set_status(str(error))
            return
        self.request_ready.emit(request)

    @Slot()
    def _update_input_controls(self) -> None:
        row = self.inputs.currentRow()
        count = self.inputs.count()
        self.remove_button.setEnabled(row >= 0)
        self.input_up_button.setEnabled(row > 0)
        self.input_down_button.setEnabled(0 <= row < count - 1)
