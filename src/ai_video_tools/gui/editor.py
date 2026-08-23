"""Native ordered-input editor for one immutable processing request."""

# PySide6 exposes Qt types dynamically, which Pylint cannot introspect.
# pylint: disable=no-name-in-module

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QFile, QSize, Qt, Signal, Slot
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent, QIcon, QPainter, QPixmap, QShowEvent
from PySide6.QtWidgets import QFileDialog, QGroupBox, QHBoxLayout, QLabel, QListWidget, QLineEdit, QListWidgetItem, QPushButton, QScrollArea, QSizePolicy, QSpinBox, QStyle, QToolButton, QVBoxLayout, QWidget

from ai_video_tools.core.models import JobRequest
from ai_video_tools.storage.naming import automatic_output_basename
from ai_video_tools.system.settings import ApplicationSettings

_VIDEO_SUFFIXES = frozenset({".mov", ".mp4", ".mkv", ".m4v"})
SOURCE_CLIP_LIST_WIDTH = 673
SOURCE_CLIP_FILENAME_MAX_DISPLAY_WIDTH = 320
OUTPUT_DIRECTORY_ICON_COLOR = "#b8bcc2"
# Keep the chooser glyph half the size of its 32 px button.
OUTPUT_DIRECTORY_ICON_SIZE = 16


def _local_now() -> datetime:
    return datetime.now().astimezone()


def _light_gray_standard_icon(style: QStyle, standard_pixmap: QStyle.StandardPixmap) -> QIcon:
    """Return one native standard icon tinted for the dark GUI palette."""

    source = style.standardIcon(standard_pixmap).pixmap(QSize(OUTPUT_DIRECTORY_ICON_SIZE, OUTPUT_DIRECTORY_ICON_SIZE))
    source = _vertically_center_pixmap_ink(source)
    tinted = QPixmap(source.size())
    tinted.setDevicePixelRatio(source.devicePixelRatio())
    tinted.fill(Qt.GlobalColor.transparent)
    painter = QPainter(tinted)
    painter.drawPixmap(0, 0, source)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(tinted.rect(), QColor(OUTPUT_DIRECTORY_ICON_COLOR))
    painter.end()
    return QIcon(tinted)


def _vertically_center_pixmap_ink(source: QPixmap) -> QPixmap:
    """Center a native pixmap's visible pixels on its existing canvas."""

    image = source.toImage()
    occupied_rows = [row for row in range(image.height()) if any(image.pixelColor(column, row).alpha() > 0 for column in range(image.width()))]
    if not occupied_rows:
        return source

    ink_height = occupied_rows[-1] - occupied_rows[0] + 1
    target_top = (image.height() - ink_height) // 2
    vertical_offset = target_top - occupied_rows[0]
    if vertical_offset == 0:
        return source

    centered = QPixmap(source.size())
    centered.setDevicePixelRatio(source.devicePixelRatio())
    centered.fill(Qt.GlobalColor.transparent)
    painter = QPainter(centered)
    painter.drawPixmap(0, vertical_offset, source)
    painter.end()
    return centered


class _ElidedFilenameLabel(QLabel):
    """Show a filename compactly while retaining its full tooltip."""

    def __init__(self, filename: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full_text = " ".join(filename.splitlines())
        self.setWordWrap(False)
        self.setText(self._full_text)

    def resizeEvent(self, event: object) -> None:  # pylint: disable=invalid-name
        """Recalculate middle elision when the row width changes."""

        super().resizeEvent(event)  # type: ignore[arg-type]
        self.refresh_elision()

    def showEvent(self, event: QShowEvent) -> None:  # pylint: disable=invalid-name
        """Calculate the initial elision after the row receives its layout width."""

        super().showEvent(event)
        self.refresh_elision()

    def refresh_elision(self) -> None:
        """Recalculate the displayed filename for the current label width."""

        display_width = min(self.contentsRect().width(), SOURCE_CLIP_FILENAME_MAX_DISPLAY_WIDTH)
        self.setText(self.fontMetrics().elidedText(self._full_text, Qt.TextElideMode.ElideMiddle, max(0, display_width)))


class JobEditor(QWidget):
    """Collect supported v1 job intent without performing media inspection."""

    request_ready = Signal(object)
    message = Signal(str)

    def __init__(self, settings: ApplicationSettings, *, clock: Callable[[], datetime] = _local_now, trash_mover: Callable[[str], bool] | None = None, parent: QWidget | None = None) -> None:
        # Declarative widget construction is intentionally kept together.
        # pylint: disable=too-many-statements
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._settings = settings
        self._clock = clock
        self._trash_mover = trash_mover or QFile.moveToTrash
        self._paths: list[Path] = []

        self.inputs = QListWidget()
        self.inputs.setObjectName("inputClips")
        self.inputs.setAccessibleName("Ordered input clips")
        self.inputs.setAccessibleDescription("Clips are processed in the order shown.")
        self.inputs.setMinimumHeight(100)
        self.inputs.setMaximumWidth(SOURCE_CLIP_LIST_WIDTH)
        self.inputs.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.inputs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.add_button = QPushButton("Add Clips…")
        self.add_button.setObjectName("addClipsButton")
        self.remove_button = QPushButton("Remove")
        self.remove_button.setObjectName("removeClipButton")
        self.input_up_button = QPushButton("Move Up")
        self.input_up_button.setObjectName("inputUpButton")
        self.input_down_button = QPushButton("Move Down")
        self.input_down_button.setObjectName("inputDownButton")

        self.source_clip_move_controls = QWidget()
        self.source_clip_move_controls.setObjectName("sourceClipMoveControls")
        self.source_clip_move_controls.setAccessibleName("Source clip reorder controls")
        self.source_clip_move_controls.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        move_controls_layout = QHBoxLayout(self.source_clip_move_controls)
        move_controls_layout.setContentsMargins(0, 0, 0, 0)
        move_controls_layout.addWidget(self.input_up_button)
        move_controls_layout.addWidget(self.input_down_button)

        input_controls = QHBoxLayout()
        input_controls.addWidget(self.add_button)
        input_controls.addWidget(self.remove_button)
        input_controls.addStretch(1)
        input_controls.addWidget(self.source_clip_move_controls, alignment=Qt.AlignmentFlag.AlignRight)

        self.output_directory = QLineEdit(str(settings.recent_output_directory or ""))
        self.output_directory.setObjectName("outputDirectory")
        self.output_directory.setPlaceholderText("Choose an output directory")
        self.output_directory.setFixedHeight(32)
        self.output_button = QToolButton()
        self.output_button.setObjectName("chooseOutputButton")
        self.output_button.setIcon(_light_gray_standard_icon(self.style(), QStyle.StandardPixmap.SP_DirOpenIcon))
        self.output_button.setIconSize(QSize(OUTPUT_DIRECTORY_ICON_SIZE, OUTPUT_DIRECTORY_ICON_SIZE))
        self.output_button.setAccessibleName("Choose output directory")
        self.output_button.setToolTip("Choose output directory")
        self.output_button.setFixedSize(32, 32)
        self.output_button.setAutoRaise(True)
        self.output_button.setStyleSheet("QToolButton { border: none; background: transparent; padding: 0px; }")
        output_row = QHBoxLayout()
        output_row.setContentsMargins(0, 0, 0, 0)
        output_row.addWidget(self.output_directory, 1, alignment=Qt.AlignmentFlag.AlignVCenter)
        output_row.addWidget(self.output_button, alignment=Qt.AlignmentFlag.AlignVCenter)

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
        self._emphasize_group_title(output_group)
        output_group_layout = QVBoxLayout(output_group)
        output_explanation = QLabel("Choose where completed videos are saved.")
        output_explanation.setObjectName("outputDirectoryExplanation")
        output_explanation.setWordWrap(True)
        output_explanation.setStyleSheet("font-size: 10px; color: #a8aaad;")
        output_group_layout.addWidget(output_explanation)
        output_group_layout.addLayout(output_row)
        target_group = QGroupBox("Target Height")
        target_group.setObjectName("targetHeightGroup")
        self._emphasize_group_title(target_group)
        target_group_layout = QVBoxLayout(target_group)
        target_explanation = QLabel("Sets the final video height; width is calculated to preserve aspect ratio.")
        target_explanation.setObjectName("targetHeightExplanation")
        target_explanation.setWordWrap(True)
        target_explanation.setStyleSheet("font-size: 10px; color: #a8aaad;")
        target_group_layout.addWidget(target_explanation)
        target_group_layout.addWidget(self.target_height)
        model_group = QGroupBox("AI Upscaler")
        model_group.setObjectName("aiUpscalerGroup")
        self._emphasize_group_title(model_group)
        model_group_layout = QVBoxLayout(model_group)
        upscaler_explanation = QLabel("Enhances video detail after clips are prepared and combined.")
        upscaler_explanation.setObjectName("aiUpscalerExplanation")
        upscaler_explanation.setWordWrap(True)
        upscaler_explanation.setStyleSheet("font-size: 10px; color: #a8aaad;")
        model_group_layout.addWidget(upscaler_explanation)
        model_group_layout.addWidget(model_label)

        basic_settings = QGroupBox("Basic Settings")
        basic_settings.setObjectName("basicSettings")
        self._emphasize_group_title(basic_settings, 4)
        basic_settings.setFixedWidth(290)
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
        source_group = QGroupBox()
        source_group.setObjectName("sourceClipListGroup")
        group_layout = QVBoxLayout(source_group)
        group_layout.setContentsMargins(2, 9, 9, 9)
        source_clips_label = QLabel("Source Clips")
        source_clips_label.setObjectName("sourceClipsLabel")
        group_layout.addWidget(source_clips_label)
        group_layout.addWidget(self.inputs)
        group_layout.addLayout(input_controls)
        submit_row = QHBoxLayout()
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

    @staticmethod
    def _emphasize_group_title(group: QGroupBox, extra_points: int = 0) -> None:
        """Emphasize a group-box title without changing its child controls."""

        title_size = max(1, group.font().pointSize() + extra_points)
        group.setStyleSheet(f"QGroupBox::title {{ font-size: {title_size}pt; font-weight: 700; }}")

    def input_paths(self) -> tuple[Path, ...]:
        """Return clip paths in their visible concat order."""

        return tuple(self._paths)

    def add_inputs(self, paths: Sequence[Path]) -> None:
        """Append selected paths without silently sorting or deduplicating them."""

        new_paths = tuple(paths)
        for path in new_paths:
            self._paths.append(path)
        if new_paths:
            self._rebuild_input_rows(len(self._paths) - 1)
        self._update_input_controls()

    def _rebuild_input_rows(self, selected_row: int) -> None:
        """Render filename rows with a right-aligned per-row Trash action."""

        self.inputs.clear()
        for path in self._paths:
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 28))
            self.inputs.addItem(item)
            row = QWidget()
            row.setMinimumWidth(0)
            row.setFixedHeight(28)
            row.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(8, 0, 4, 0)
            filename = _ElidedFilenameLabel(path.name)
            filename.setObjectName("sourceClipFilename")
            filename.setMinimumWidth(0)
            filename.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            filename.setToolTip(str(path))
            row_layout.addWidget(filename, 1)
            trash_button = QToolButton()
            trash_button.setObjectName("sourceClipTrashButton")
            trash_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon))
            trash_button.setAccessibleName(f"Move {path.name} to Trash")
            trash_button.setToolTip(f"Move {path.name} to Trash")
            trash_button.setIconSize(QSize(10, 10))
            trash_button.setFixedSize(20, 20)
            trash_button.setStyleSheet("QToolButton { padding: 0px; margin: 0px; }")
            trash_button.clicked.connect(lambda _checked=False, current_item=item: self._move_item_to_trash(current_item))
            row_layout.addWidget(trash_button)
            self.inputs.setItemWidget(item, row)
        if self._paths:
            self.inputs.setCurrentRow(max(0, min(selected_row, len(self._paths) - 1)))

    @Slot()
    def _move_item_to_trash(self, item: QListWidgetItem) -> None:
        """Move one source file to the OS Trash before removing its row."""

        row = self.inputs.row(item)
        if row < 0 or row >= len(self._paths):
            return
        path = self._paths[row]
        if not self._trash_mover(str(path)):
            self.message.emit(f"Could not move source clip to Trash: {path.name}")
            return
        self._paths.pop(row)
        self._rebuild_input_rows(min(row, len(self._paths) - 1))
        self._update_input_controls()
        self.message.emit(f"Moved source clip to Trash: {path.name}")

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
            self._paths.pop(row)
            self._rebuild_input_rows(min(row, len(self._paths) - 1))
        self._update_input_controls()

    def move_selected(self, offset: int) -> bool:
        """Move the selected clip while preserving every other relative order."""

        row = self.inputs.currentRow()
        destination = row + offset
        if row < 0 or destination < 0 or destination >= self.inputs.count():
            return False
        path = self._paths.pop(row)
        self._paths.insert(destination, path)
        self._rebuild_input_rows(destination)
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
            self.message.emit(str(error))
            return
        self.request_ready.emit(request)

    @Slot()
    def _update_input_controls(self) -> None:
        row = self.inputs.currentRow()
        count = self.inputs.count()
        self.remove_button.setEnabled(row >= 0)
        self.input_up_button.setEnabled(row > 0)
        self.input_down_button.setEnabled(0 <= row < count - 1)
