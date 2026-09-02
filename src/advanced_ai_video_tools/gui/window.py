"""Native window for observing and controlling queued jobs."""

# PySide6 exposes Qt types dynamically, which Pylint cannot introspect.
# pylint: disable=no-name-in-module

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QEvent, QModelIndex, QRect, QSignalBlocker, Qt, Slot
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QKeyEvent, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QAbstractItemView, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QMainWindow, QProgressBar, QPushButton, QSplitter, QSplitterHandle, QStackedWidget, QStyledItemDelegate, QStyle, QStyleOptionHeader, QStyleOptionViewItem, QTableView, QToolButton, QVBoxLayout, QWidget

from advanced_ai_video_tools.core.models import JobState, PipelineStage, Toolchain
from advanced_ai_video_tools.gui.editor import JobEditor
from advanced_ai_video_tools.gui.jobs import JobListModel, JobRole, QueueRegionProxyModel
from advanced_ai_video_tools.gui.identity import GUI_DISPLAY_NAME
from advanced_ai_video_tools.gui.messages import MessageEvent, MessageWidget
from advanced_ai_video_tools.gui.preview import QueuePreviewPane, SourcePreviewPane
from advanced_ai_video_tools.gui.submission import JobSubmissionController
from advanced_ai_video_tools.gui.theme import CONTROL_RADIUS, MAJOR_REGION_GAP, SPACE_1, SPACE_2, SPACE_3, SPACE_4
from advanced_ai_video_tools.gui.tool_settings import ToolSettingsDialog, ToolSettingsValidator
from advanced_ai_video_tools.system.settings import ApplicationSettings, SettingsError, SettingsStore

JOB_NAME_COLUMN_WIDTH = 200
QUEUE_STATUS_COLUMN_WIDTH = 96
QUEUE_ACTION_COLUMN_WIDTH = 56
QUEUE_HEADER_OPTICAL_OFFSETS = {0: -4, 2: 5}


class _ModernSplitterHandle(QSplitterHandle):
    """Paint a quiet divider with a discoverable, hover-only grabber."""

    def __init__(self, orientation: Qt.Orientation, parent: QSplitter) -> None:
        super().__init__(orientation, parent)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.SplitVCursor)

    def paintEvent(self, _event: object) -> None:  # pylint: disable=invalid-name
        """Draw the divider line and its compact interactive grabber."""

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center_y = self.height() // 2
        painter.setPen(QColor("#303134"))
        painter.drawLine(0, center_y, self.width(), center_y)
        grabber_color = QColor("#5f6368" if self.underMouse() else "#45474b")
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(grabber_color)
        grabber_width = min(56, max(32, self.width() // 4))
        painter.drawRoundedRect((self.width() - grabber_width) // 2, center_y - 2, grabber_width, 4, 2, 2)


class _ModernContentMessageSplitter(QSplitter):
    """Content/message splitter using the application's lightweight handle."""

    def createHandle(self) -> QSplitterHandle:  # pylint: disable=invalid-name
        """Create the custom handle used between content and messages."""

        return _ModernSplitterHandle(self.orientation(), self)


class _QueueHeaderView(QHeaderView):
    """Keep the Job Name section readable when Qt reapportions stretch space."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._enforcing_minimum = False

    def resizeEvent(self, event: object) -> None:  # pylint: disable=invalid-name
        """Restore the minimum name width after a table/window resize."""

        super().resizeEvent(event)
        if self._enforcing_minimum:
            return
        parent = self.parentWidget()
        viewport_width = parent.viewport().width() if isinstance(parent, QTableView) else 0
        desired_width = max(JOB_NAME_COLUMN_WIDTH, viewport_width - QUEUE_STATUS_COLUMN_WIDTH - QUEUE_ACTION_COLUMN_WIDTH)
        if self.sectionSize(1) == desired_width:
            return
        self._enforcing_minimum = True
        try:
            self.resizeSection(1, desired_width)
        finally:
            self._enforcing_minimum = False

    def paintSection(self, painter: QPainter, rect: QRect, logical_index: int) -> None:  # pylint: disable=invalid-name
        """Paint header chrome normally and optically center short labels."""

        if not rect.isValid():
            return
        option = QStyleOptionHeader()
        self.initStyleOptionForIndex(option, logical_index)
        option.rect = rect
        painter.save()
        painter.setClipRect(rect)
        self.style().drawControl(QStyle.ControlElement.CE_HeaderSection, option, painter, self)
        option.rect = rect.translated(QUEUE_HEADER_OPTICAL_OFFSETS.get(logical_index, 0), 0)
        self.style().drawControl(QStyle.ControlElement.CE_HeaderLabel, option, painter, self)
        painter.restore()


class _QueueActionDelegate(QStyledItemDelegate):
    """Render compact, high-contrast icons in the queue action column."""

    def __init__(self, cancel_icon: QIcon, remove_icon: QIcon, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cancel_icon = cancel_icon
        self._remove_icon = remove_icon

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:  # pylint: disable=invalid-name
        """Paint only the contextual action icon for this cell."""

        action = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        if not action:
            return
        icon = self._cancel_icon if action == "Cancel" else self._remove_icon
        icon_size = min(20, max(16, option.rect.height() - 12))
        rect = option.rect
        icon_rect = rect.adjusted((rect.width() - icon_size) // 2, (rect.height() - icon_size) // 2, -(rect.width() - icon_size) // 2, -(rect.height() - icon_size) // 2)
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(rect, option.palette.highlight())
        icon.paint(painter, icon_rect, Qt.AlignmentFlag.AlignCenter, QIcon.Mode.Normal if option.state & QStyle.StateFlag.State_Enabled else QIcon.Mode.Disabled)


class MainWindow(QMainWindow):
    """Desktop shell centered on the shared processing queue."""

    def __init__(self, model: JobListModel, settings: ApplicationSettings, log_path: Path | None = None, *, submission: JobSubmissionController | None = None, tool_validator: ToolSettingsValidator | None = None, settings_store: SettingsStore | None = None) -> None:
        # Declarative widget construction is intentionally kept together.
        # pylint: disable=too-many-statements
        super().__init__()
        del log_path
        self._model = model
        self._settings = settings
        self._submission = submission
        self._tool_validator = tool_validator
        self._settings_store = settings_store
        self._last_snapshots: dict[str, object] = {}
        self._last_upscale_message_percent: dict[str, int] = {}
        self._preview_processing_job_id: str | None = None
        self._queue_preview_job_id: str | None = None
        self._global_shutdown_recorded = False
        self.setWindowTitle(GUI_DISPLAY_NAME)
        self.setMinimumSize(1400, 880)

        self.editor = JobEditor(settings, queued_inputs=self._queued_source_paths)
        self.source_preview = SourcePreviewPane(muted=settings.preview_muted, volume=settings.preview_volume)
        self.queue_preview = QueuePreviewPane(muted=settings.preview_muted, volume=settings.preview_volume)
        edit_menu = self.menuBar().addMenu("Edit")
        self.preferences_action = QAction("Preferences", self)
        self.preferences_action.setObjectName("preferencesAction")
        self.preferences_action.setEnabled(tool_validator is not None and settings_store is not None)
        edit_menu.addAction(self.preferences_action)
        self.queue_table = QTableView()
        self.queue_table.setObjectName("queueTable")
        self.queue_table.setModel(model)
        self.queue_table.setFixedHeight(240)
        self.queue_table.setContentsMargins(0, 0, 0, 0)
        self.queue_table.setShowGrid(False)
        self.queue_table.verticalHeader().setVisible(False)
        self.queue_table.verticalHeader().setDefaultSectionSize(40)
        self.queue_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.queue_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.queue_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.queue_table.setTextElideMode(Qt.TextElideMode.ElideRight)
        header = _QueueHeaderView(self.queue_table)
        self.queue_table.setHorizontalHeader(header)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(0, QUEUE_STATUS_COLUMN_WIDTH)
        header.resizeSection(1, JOB_NAME_COLUMN_WIDTH)
        header.resizeSection(2, QUEUE_ACTION_COLUMN_WIDTH)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        header.setStretchLastSection(False)
        self.queue_table.setAlternatingRowColors(True)
        self.queue_table.setAccessibleName("Processing queue")
        job_queue_group = QGroupBox("Job Queue")
        job_queue_group.setObjectName("queueGroup")
        job_queue_layout = QVBoxLayout(job_queue_group)
        job_queue_layout.setContentsMargins(SPACE_3, SPACE_4, SPACE_3, SPACE_3)
        job_queue_layout.setSpacing(SPACE_2)
        job_queue_layout.addWidget(self.queue_table)
        # Retain the original flat table as a compatibility selection surface;
        # the visible monitoring layout below presents filtered regions.
        job_queue_group.setVisible(False)
        self.selected_job_message = QLabel("No jobs have been submitted.")
        self.selected_job_message.setObjectName("selectedJobMessage")
        self.selected_job_message.setWordWrap(True)
        self.selected_job_output = QLabel()
        self.selected_job_output.setObjectName("selectedJobOutput")
        self.selected_job_output.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.selected_job_output.setWordWrap(True)
        self.selected_job_stage_progress = QProgressBar()
        self.selected_job_stage_progress.setObjectName("selectedJobStageProgress")
        self.selected_job_stage_progress.setAccessibleName("Stage progress")
        self.selected_job_stage_progress.setRange(0, 1)
        self.selected_job_stage_progress.setTextVisible(True)
        self.selected_job_overall_progress = QProgressBar()
        self.selected_job_overall_progress.setObjectName("selectedJobOverallProgress")
        self.selected_job_overall_progress.setAccessibleName("Whole job progress")
        self.selected_job_overall_progress.setRange(0, 100)
        self.selected_job_overall_progress.setValue(0)
        self.selected_job_overall_progress.setFormat("Whole job: 0%")
        self.move_job_up_button = QPushButton("Move Up")
        self.move_job_up_button.setObjectName("moveJobUpButton")
        self.move_job_down_button = QPushButton("Move Down")
        self.move_job_down_button.setObjectName("moveJobDownButton")
        for reorder_button in (self.move_job_up_button, self.move_job_down_button):
            reorder_button.setFixedHeight(26)
        details = QGroupBox("Selected Job")
        details.setObjectName("selectedJobDetails")
        details_layout = QFormLayout(details)
        details_layout.setContentsMargins(SPACE_2, SPACE_2, SPACE_2, SPACE_2)
        details_layout.setHorizontalSpacing(SPACE_2)
        details_layout.setVerticalSpacing(SPACE_1)
        self.job_name_value = QLabel("No job selected")
        self.job_name_value.setObjectName("selectedJobName")
        self.job_state_value = QLabel("No job selected")
        self.job_state_value.setObjectName("selectedJobStatus")
        self.job_stage_value = QLabel("No job selected")
        self.job_stage_value.setObjectName("selectedJobStage")
        details_layout.addRow("Job Name", self.job_name_value)
        details_layout.addRow("Status", self.job_state_value)
        details_layout.addRow("Stage", self.job_stage_value)
        details_layout.addRow("Message", self.selected_job_message)
        details_layout.addRow("Output", self.selected_job_output)

        self.region_views: dict[str, QTableView] = {}
        self.region_proxies: dict[str, QueueRegionProxyModel] = {}
        region_groups: dict[str, QGroupBox] = {}
        for region, title in (
            ("active", "Active"),
            ("up_next", "Up Next"),
            ("history", "History"),
        ):
            proxy = QueueRegionProxyModel(region, self)
            proxy.setSourceModel(model)
            view = QTableView()
            if region == "active":
                view.setMaximumHeight(88)
            view.setModel(proxy)
            self._configure_region_view(view, f"queue{title.replace(' ', '')}View", f"{title} jobs")
            view.setItemDelegateForColumn(2, _QueueActionDelegate(self._cancel_icon(), self._remove_icon(), view))
            self.region_views[region] = view
            self.region_proxies[region] = proxy
            group = QGroupBox(title)
            group.setObjectName(f"queue{title.replace(' ', '')}Group")
            group_layout = QVBoxLayout(group)
            group_layout.setContentsMargins(SPACE_2, SPACE_2, SPACE_2, SPACE_2)
            group_layout.setSpacing(SPACE_1)
            group_layout.addWidget(view)
            region_groups[region] = group

        self.region_groups = region_groups
        self.setTabOrder(self.region_views["active"], self.region_views["up_next"])
        self.setTabOrder(self.region_views["up_next"], self.region_views["history"])

        creation_page = QWidget()
        creation_layout = QVBoxLayout(creation_page)
        creation_layout.setContentsMargins(0, 0, 0, 0)
        creation_layout.addWidget(self.editor, 1)
        monitoring_page = QWidget()
        monitoring_layout = QVBoxLayout(monitoring_page)
        monitoring_layout.setContentsMargins(0, 0, 0, 0)
        monitoring_layout.setSpacing(SPACE_3)
        monitoring_layout.addWidget(job_queue_group)
        self.queue_region_workspace = QWidget()
        self.queue_region_workspace.setObjectName("queueRegionWorkspace")
        region_workspace_layout = QHBoxLayout(self.queue_region_workspace)
        region_workspace_layout.setContentsMargins(0, 0, 0, 0)
        region_workspace_layout.setSpacing(SPACE_3)
        left_region_column = QWidget()
        left_region_column.setObjectName("queueLeftRegionColumn")
        left_region_layout = QVBoxLayout(left_region_column)
        left_region_layout.setContentsMargins(0, 0, 0, 0)
        left_region_layout.setSpacing(SPACE_3)
        left_region_layout.addWidget(region_groups["active"])
        up_next_header = QHBoxLayout()
        up_next_header.setContentsMargins(0, 0, 0, 0)
        up_next_header.addStretch(1)
        up_next_header.addWidget(self.move_job_up_button)
        up_next_header.addWidget(self.move_job_down_button)
        up_next_layout = region_groups["up_next"].layout()
        up_next_layout.insertLayout(0, up_next_header)
        left_region_layout.addWidget(region_groups["up_next"], 1)
        region_workspace_layout.addWidget(left_region_column, 1)
        region_workspace_layout.addWidget(region_groups["history"], 1)
        monitoring_layout.addWidget(self.queue_region_workspace, 1)
        monitoring_layout.addWidget(details)
        monitoring_layout.addWidget(self.selected_job_overall_progress)
        monitoring_layout.addWidget(self.selected_job_stage_progress)

        self.view_stack = QStackedWidget()
        self.view_stack.setObjectName("contentViewStack")
        self.view_stack.addWidget(creation_page)
        self.view_stack.addWidget(monitoring_page)
        self.navigation_rail = QWidget()
        self.navigation_rail.setObjectName("viewNavigationRail")
        rail_layout = QVBoxLayout(self.navigation_rail)
        rail_layout.setSpacing(SPACE_2)
        self.job_creation_button = self._navigation_button("create", "Job Creation", "jobCreationButton")
        self.queue_monitoring_button = self._navigation_button("queue", "Queue Monitoring", "queueMonitoringButton")
        rail_layout.setContentsMargins(SPACE_2, SPACE_4, SPACE_2, SPACE_4)
        rail_width = self.job_creation_button.minimumWidth() + (SPACE_2 * 2)
        self.navigation_rail.setFixedWidth(rail_width)
        rail_layout.addWidget(self.job_creation_button, alignment=Qt.AlignmentFlag.AlignHCenter)
        rail_layout.addWidget(self.queue_monitoring_button, alignment=Qt.AlignmentFlag.AlignHCenter)
        rail_layout.addStretch(1)
        self.job_creation_button.clicked.connect(lambda: self._switch_view(0))
        self.queue_monitoring_button.clicked.connect(lambda: self._switch_view(1))
        self.job_creation_button.setChecked(True)

        self.message_widget = MessageWidget()
        self.message_widget.setObjectName("sessionMessageWidget")
        self.message_tabs = self.message_widget.tabs
        self.global_messages = self.message_widget.global_messages
        self.job_messages = self.message_widget.job_messages
        self.content_message_splitter = _ModernContentMessageSplitter(Qt.Orientation.Vertical)
        self.content_message_splitter.setObjectName("contentMessageSplitter")
        self.content_message_splitter.setHandleWidth(12)
        self.content_message_splitter.setChildrenCollapsible(False)
        self.content_message_splitter.addWidget(self.view_stack)
        self.content_message_splitter.addWidget(self.message_widget)
        self.content_message_splitter.setStretchFactor(0, 1)
        self.content_message_splitter.setStretchFactor(1, 0)
        self.preview_stack = QStackedWidget()
        self.preview_stack.setObjectName("previewViewStack")
        self.preview_stack.addWidget(self.source_preview)
        self.preview_stack.addWidget(self.queue_preview)
        workspace = QWidget()
        workspace.setObjectName("mainWorkspace")
        workspace_layout = QHBoxLayout(workspace)
        workspace_layout.setContentsMargins(0, SPACE_4, SPACE_4, SPACE_4)
        workspace_layout.setSpacing(MAJOR_REGION_GAP)
        workspace_layout.addWidget(self.content_message_splitter, 1)
        workspace_layout.addWidget(self.preview_stack, 1)
        content = QWidget()
        content_layout = QHBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        content_layout.addWidget(self.navigation_rail)
        content_layout.addWidget(workspace, 1)
        self.setCentralWidget(content)

        self.queue_table.selectionModel().currentChanged.connect(self._selection_changed)
        self.queue_table.clicked.connect(self._handle_queue_cell_click)
        for region, view in self.region_views.items():
            view.installEventFilter(self)
            view.selectionModel().currentChanged.connect(lambda current, previous, selected_view=view: self._region_selection_changed(selected_view, current, previous))
            view.clicked.connect(lambda index, selected_region=region: self._handle_region_cell_click(selected_region, index))
        model.dataChanged.connect(self._refresh_after_model_change)
        model.rowsInserted.connect(self._select_first_inserted_job)
        model.rowsRemoved.connect(self._rows_removed)
        model.modelReset.connect(self._refresh_selected_job)
        model.snapshot_changed.connect(self._handle_queue_snapshot)
        self.move_job_up_button.clicked.connect(lambda: self._move_selected_job(-1))
        self.move_job_down_button.clicked.connect(lambda: self._move_selected_job(1))
        self.preferences_action.triggered.connect(self._open_preferences)
        self.editor.inputs.currentRowChanged.connect(self._update_preview_for_source_selection)
        self.editor.inputs.model().rowsInserted.connect(lambda *_: self._update_preview_for_source_selection(self.editor.inputs.currentRow()))
        self.editor.inputs.model().rowsRemoved.connect(lambda *_: self._update_preview_for_source_selection(self.editor.inputs.currentRow()))
        self.editor.output_directory.editingFinished.connect(self._persist_output_directory_preference)
        self.source_preview.previous_requested.connect(lambda: self._move_source_selection(-1))
        self.source_preview.next_requested.connect(lambda: self._move_source_selection(1))
        self.source_preview.first_frame_requested.connect(self.source_preview.go_to_first_frame)
        self.source_preview.last_frame_requested.connect(self.source_preview.go_to_last_frame)
        self.source_preview.preview_error.connect(self._append_global_message)
        self.source_preview.audio_preferences_changed.connect(self._audio_preferences_changed)
        self.source_preview.fullscreen_requested.connect(self.source_preview.open_fullscreen)
        self.editor.fullscreen_requested.connect(self._open_source_fullscreen)
        self.editor.message.connect(self._append_global_message)
        self._append_global_message("Application started.")
        self._append_global_message("Add clips in order they should be concatenated.")
        if submission is not None:
            self.editor.request_ready.connect(submission.begin_submission)
            submission.busy_changed.connect(self.editor.set_busy)
            submission.status_changed.connect(self._append_global_message)
            submission.queued.connect(lambda job_id: self._append_job_message(job_id, "Job queued."))
            submission.queued.connect(self.editor.job_queued)
            submission.settings_changed.connect(self._apply_settings)
            submission.busy_changed.connect(lambda busy: self._append_global_message("Preflight started." if busy else "Preflight finished."))
        if tool_validator is not None:
            tool_validator.succeeded.connect(self._report_validated_tools)
            tool_validator.failed.connect(lambda _overrides, message: self._append_global_message(f"External-tool validation failed: {message}"))
        self._refresh_selected_job()

    @staticmethod
    def _configure_region_view(view: QTableView, object_name: str, accessible_name: str) -> None:
        """Apply the compact, text-first table treatment to one queue region."""

        view.setObjectName(object_name)
        view.setAccessibleName(accessible_name)
        view.setShowGrid(False)
        view.verticalHeader().setVisible(False)
        view.verticalHeader().setDefaultSectionSize(36)
        view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        view.setTextElideMode(Qt.TextElideMode.ElideRight)
        view.setAlternatingRowColors(True)
        header = _QueueHeaderView(view)
        view.setHorizontalHeader(header)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(0, QUEUE_STATUS_COLUMN_WIDTH)
        header.resizeSection(1, JOB_NAME_COLUMN_WIDTH)
        header.resizeSection(2, QUEUE_ACTION_COLUMN_WIDTH)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        header.setStretchLastSection(False)

    @staticmethod
    def _cancel_icon() -> QIcon:
        """Create the distinguished stop icon used for active cancellation."""

        pixmap = QPixmap(20, 20)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#ffb4ab"), 1.8))
        painter.drawEllipse(2, 2, 16, 16)
        painter.setBrush(QColor("#ffb4ab"))
        painter.drawRoundedRect(7, 7, 6, 6, 1, 1)
        painter.end()
        return QIcon(pixmap)

    @staticmethod
    def _remove_icon() -> QIcon:
        """Create the remove icon used for terminal history rows."""

        pixmap = QPixmap(20, 20)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#d4d7dc"), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawEllipse(2, 2, 16, 16)
        painter.drawLine(7, 10, 13, 10)
        painter.end()
        return QIcon(pixmap)

    @staticmethod
    def _navigation_button(glyph: str, label: str, object_name: str) -> QToolButton:
        """Create one accessible, mutually exclusive view-rail control."""

        button = QToolButton()
        icon = QPixmap(18, 18)
        icon.fill(Qt.GlobalColor.transparent)
        painter = QPainter(icon)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#e8eaed"), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        if glyph == "create":
            painter.drawRoundedRect(3, 2, 10, 14, 1.5, 1.5)
            painter.drawLine(6, 6, 10, 6)
            painter.drawLine(6, 9, 10, 9)
            painter.drawLine(13, 11, 13, 16)
            painter.drawLine(10.5, 13.5, 15.5, 13.5)
        else:
            for y in (3, 8, 13):
                painter.drawLine(3, y, 5, y)
                painter.drawLine(7, y, 15, y)
        painter.end()
        button.setIcon(QIcon(icon))
        button.setIconSize(icon.size())
        button.setText("")
        button.setObjectName(object_name)
        button.setAccessibleName(label)
        button.setToolTip(label)
        button.setCheckable(True)
        button.setAutoRaise(True)
        button.setMinimumSize(64, 64)
        button.setFixedSize(64, 64)
        font = QFont(button.font())
        font.setPointSize(max(1, font.pointSize() * 2))
        button.setFont(font)
        button.setStyleSheet("QToolButton { " f"border: 1px solid transparent; border-radius: {CONTROL_RADIUS}px; " "min-width: 62px; max-width: 62px; min-height: 62px; max-height: 62px; " "outline: none; background: #303134; color: #e8eaed; padding: 0px; }" "QToolButton:checked { color: #ffffff; background: #39485f; border-color: #8ab4f8; }" "QToolButton:hover { background: #3c4043; border-color: #8ab4f8; }" "QToolButton:pressed { background: #474a4f; }")
        return button

    @Slot(int)
    def _switch_view(self, index: int) -> None:
        """Switch visible presentation surface without changing job state."""

        self.view_stack.setCurrentIndex(index)
        self.preview_stack.setCurrentIndex(index)
        self.job_creation_button.setChecked(index == 0)
        self.queue_monitoring_button.setChecked(index == 1)

    @Slot(int)
    def _update_preview_for_source_selection(self, row: int) -> None:
        """Bind preview identity to editor selection only."""

        paths = self.editor.input_paths()
        self.source_preview.set_sources(paths, row)

    @Slot(int)
    def _open_source_fullscreen(self, row: int) -> None:
        """Synchronize one source row before opening its fullscreen preview."""

        if 0 <= row < self.editor.inputs.count():
            self.editor.inputs.setCurrentRow(row)
            # A clip-row accessory button can request fullscreen without a new
            # list-selection signal. Bind the selected source synchronously so
            # opening never relies on that separate signal's delivery timing.
            self._update_preview_for_source_selection(row)
            self.source_preview.open_fullscreen()

    def _queued_source_paths(self) -> tuple[Path, ...]:
        """Return source paths referenced by jobs that still occupy the queue."""

        active_states = {JobState.QUEUED, JobState.VALIDATING, JobState.RUNNING, JobState.CANCELLING}
        paths: list[Path] = []
        for row in range(self._model.rowCount()):
            snapshot = self._model.snapshot_at(self._model.index(row, 0))
            if snapshot is not None and snapshot.state in active_states:
                paths.extend(snapshot.request.inputs)
        return tuple(paths)

    def _move_source_selection(self, offset: int) -> None:
        """Navigate source selection without changing concat order."""

        self._select_source_row(self.editor.inputs.currentRow() + offset)

    def _select_source_row(self, row: int) -> None:
        """Select one existing source row and leave the ordered list intact."""

        if 0 <= row < self.editor.inputs.count():
            self.editor.inputs.setCurrentRow(row)

    def _append_global_message(self, text: str) -> None:
        self.message_widget.append(MessageEvent(text))

    def _append_job_message(self, job_id: str, text: str) -> None:
        self.message_widget.append(MessageEvent(text, job_id))

    @Slot(object, object)
    def _report_validated_tools(self, _overrides: object, toolchain: object) -> None:
        """Publish resolved tool paths without exposing command lines."""

        if not isinstance(toolchain, Toolchain):
            self._append_global_message("External tools validated, but no resolved toolchain was returned.")
            return
        self._append_global_message("External tools validated: " f"FFmpeg {toolchain.ffmpeg.path}; FFprobe {toolchain.ffprobe.path}; " f"Real-ESRGAN {toolchain.realesrgan.path}; models {toolchain.model_directory}.")

    def _append_upscale_progress_summary(self, job_id: str, progress: object) -> None:
        """Append a concise upscale summary at 10-percent intervals."""

        total = getattr(progress, "total", None)
        completed = max(0, int(getattr(progress, "completed", 0)))
        if total is None or int(total) <= 0:
            return
        total = int(total)
        percent = min(100, completed * 100 // total)
        previous_percent = self._last_upscale_message_percent.get(job_id, -10)
        if percent < previous_percent:
            previous_percent = -10
        if percent == 100 or percent >= previous_percent + 10:
            self._append_job_message(job_id, f"Upscale progress: {percent}% ({completed}/{total} frames).")
            self._last_upscale_message_percent[job_id] = percent

    @Slot(object)
    def _handle_queue_snapshot(self, snapshot: object) -> None:
        job_id = getattr(snapshot, "job_id", None)
        if not job_id:
            return
        previous = self._last_snapshots.get(job_id)
        state = getattr(snapshot, "state", None)
        progress = getattr(snapshot, "last_progress", None)
        previous_state = getattr(previous, "state", None)
        if state is JobState.RUNNING and previous_state is not JobState.RUNNING:
            self.source_preview.pause_for_processing()
            self._preview_processing_job_id = job_id
        elif self._preview_processing_job_id == job_id and state in {JobState.CANCELLED, JobState.FAILED, JobState.COMPLETED}:
            self._preview_processing_job_id = None
        if previous is None:
            name = snapshot.request.generated_output_basename or snapshot.request.explicit_output_path or "output"
            self._append_job_message(job_id, f"Job started: {name}." if state is JobState.RUNNING else "Job queued.")
        elif previous_state is not state:
            self._append_job_message(job_id, f"Job {state.value.replace('_', ' ')}.")
        previous_progress = getattr(previous, "last_progress", None)
        if progress is not None and (previous_progress is None or (progress.stage, progress.message) != (previous_progress.stage, previous_progress.message)):
            if progress.stage is PipelineStage.UPSCALE:
                self._append_upscale_progress_summary(job_id, progress)
            else:
                self._append_job_message(job_id, f"{progress.stage.value}: {progress.message}")
        if state is JobState.COMPLETED and getattr(previous, "state", None) is not JobState.COMPLETED:
            name = snapshot.request.generated_output_basename or snapshot.request.explicit_output_path or job_id
            self._append_global_message(f"Job completed: {name}.")
        self._last_snapshots[job_id] = snapshot

    @Slot(QModelIndex, QModelIndex)
    def _selection_changed(self, _current: QModelIndex, _previous: QModelIndex) -> None:
        self._sync_region_selection()
        self._refresh_selected_job(activate_job_tab=True)

    @Slot(QTableView, QModelIndex, QModelIndex)
    def _region_selection_changed(self, view: QTableView, current: QModelIndex, _previous: QModelIndex) -> None:
        """Map a visible region selection back to the authoritative table."""

        if not current.isValid():
            return
        proxy = view.model()
        if not isinstance(proxy, QueueRegionProxyModel):
            return
        source_index = proxy.mapToSource(current)
        if source_index.isValid():
            self.queue_table.setCurrentIndex(source_index)

    def eventFilter(self, watched: object, event: object) -> bool:  # pylint: disable=invalid-name
        """Keep keyboard navigation in the visible queue order."""

        if not isinstance(watched, QTableView) or not isinstance(event, QKeyEvent) or event.type() != QEvent.Type.KeyPress:
            return super().eventFilter(watched, event)
        if event.modifiers() != Qt.KeyboardModifier.NoModifier:
            return super().eventFilter(watched, event)
        if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space}:
            if watched.currentIndex().isValid():
                watched.setCurrentIndex(watched.currentIndex())
            return True
        if event.key() not in {Qt.Key.Key_Up, Qt.Key.Key_Down}:
            return super().eventFilter(watched, event)
        targets: list[tuple[QTableView, QModelIndex]] = []
        for region in ("active", "up_next", "history"):
            view = self.region_views[region]
            proxy = self.region_proxies[region]
            targets.extend((view, proxy.index(row, 0)) for row in range(proxy.rowCount()))
        if not targets:
            return True
        current_id = self._model.data(self.queue_table.currentIndex(), int(JobRole.JOB_ID))
        current_position = next((position for position, (_view, index) in enumerate(targets) if targets[position][1].data(int(JobRole.JOB_ID)) == current_id), None)
        if current_position is None:
            target_position = 0 if event.key() == Qt.Key.Key_Down else len(targets) - 1
        else:
            delta = -1 if event.key() == Qt.Key.Key_Up else 1
            target_position = max(0, min(len(targets) - 1, current_position + delta))
        target_view, target_index = targets[target_position]
        target_view.setCurrentIndex(target_index)
        target_view.setFocus(Qt.FocusReason.OtherFocusReason)
        target_view.scrollTo(target_index, QAbstractItemView.ScrollHint.EnsureVisible)
        return True

    def _sync_region_selection(self) -> None:
        """Reflect the canonical selection in whichever region owns it."""

        current = self.queue_table.currentIndex()
        if not current.isValid():
            return
        job_id = self._model.data(current, int(JobRole.JOB_ID))
        for view in self.region_views.values():
            proxy = view.model()
            if not isinstance(proxy, QueueRegionProxyModel):
                continue
            target = QModelIndex()
            for row in range(proxy.rowCount()):
                candidate = proxy.index(row, 0)
                if proxy.data(candidate, int(JobRole.JOB_ID)) == job_id:
                    target = candidate
                    break
            blocker = QSignalBlocker(view.selectionModel())
            view.setCurrentIndex(target)
            del blocker

    @Slot(str, QModelIndex)
    def _handle_region_cell_click(self, region: str, index: QModelIndex) -> None:
        """Handle the region's inline cancel or remove action."""

        if index.column() != 2:
            return
        view = self.region_views[region]
        proxy = view.model()
        if isinstance(proxy, QueueRegionProxyModel):
            source_index = proxy.mapToSource(index)
            if region == "history":
                self._model.remove(source_index)
            else:
                self._model.cancel(source_index)

    @Slot(QModelIndex)
    def _handle_queue_cell_click(self, index: QModelIndex) -> None:
        """Handle the compatibility table's inline queue action."""

        if index.column() == 2:
            state = self._model.data(index, int(JobRole.STATE))
            if state in {JobState.QUEUED.value, JobState.VALIDATING.value, JobState.RUNNING.value}:
                self._model.cancel(index)
            else:
                self._model.remove(index)

    @Slot(QModelIndex, QModelIndex, list)
    def _refresh_after_model_change(self, _first: QModelIndex, _last: QModelIndex, _roles: list[int]) -> None:
        self._sync_region_selection()
        self._refresh_selected_job()

    @Slot(QModelIndex, int, int)
    def _rows_removed(self, _parent: QModelIndex, _first: int, _last: int) -> None:
        self._sync_region_selection()
        self._refresh_selected_job()

    @Slot(QModelIndex, int, int)
    def _select_first_inserted_job(self, _parent: QModelIndex, first: int, _last: int) -> None:
        if not self.queue_table.currentIndex().isValid():
            self.queue_table.setCurrentIndex(self._model.index(first, 0))
        self._sync_region_selection()
        self._refresh_selected_job()

    def _clear_selection_details(self) -> None:
        """Render the empty queue-selection state and disable job actions."""

        self.selected_job_message.setText("No jobs have been submitted.")
        self.selected_job_output.clear()
        self.selected_job_stage_progress.setRange(0, 1)
        self.selected_job_stage_progress.setValue(0)
        self.selected_job_stage_progress.setFormat("Stage: no job selected")
        self.selected_job_overall_progress.setValue(0)
        self.selected_job_overall_progress.setFormat("Whole job: 0%")
        self.move_job_up_button.setEnabled(False)
        self.move_job_down_button.setEnabled(False)
        self.job_name_value.setText("No job selected")
        self.job_state_value.setText("No job selected")
        self.job_stage_value.setText("No job selected")
        self._queue_preview_job_id = None
        self.queue_preview.clear("Select a running or completed job to preview its output.")
        self.message_widget.select_job(None)

    def _update_progress_details(self, state: object, stage: object, completed: int, total: object) -> None:
        """Render stage and whole-job progress from typed queue roles."""

        # A cancellation snapshot can retain the last pipeline progress event.
        # That value describes work before cancellation, not cancellation or
        # cleanup itself, so do not present it as current job progress.
        if state == JobState.CANCELLING.value:
            self.selected_job_overall_progress.setRange(0, 0)
            self.selected_job_overall_progress.setFormat("Whole job: Cancelling…")
            self.selected_job_stage_progress.setRange(0, 0)
            self.selected_job_stage_progress.setFormat("Stage: Cancelling and cleaning up…")
            return
        if state == JobState.CANCELLED.value:
            self.selected_job_overall_progress.setRange(0, 100)
            self.selected_job_overall_progress.setValue(0)
            self.selected_job_overall_progress.setFormat("Whole job: Cancelled")
            self.selected_job_stage_progress.setRange(0, 1)
            self.selected_job_stage_progress.setValue(0)
            self.selected_job_stage_progress.setFormat("Stage: Cancelled")
            return

        if state == JobState.COMPLETED.value:
            whole_percent = 100
        elif stage is None:
            whole_percent = 0
        else:
            stage_index = tuple(item.value for item in PipelineStage).index(str(stage))
            stage_fraction = completed / max(1, int(total)) if total is not None else 0.0
            whole_percent = min(99, int(((stage_index + stage_fraction) / len(PipelineStage)) * 100))
        self.selected_job_overall_progress.setValue(whole_percent)
        self.selected_job_overall_progress.setFormat(f"Whole job: {whole_percent}%")
        if total is None:
            self.selected_job_stage_progress.setRange(0, 0)
            self.selected_job_stage_progress.setFormat(f"Stage: {stage or 'Working'} (measuring…)")
        else:
            self.selected_job_stage_progress.setRange(0, max(1, int(total)))
            self.selected_job_stage_progress.setValue(completed)
            self.selected_job_stage_progress.setFormat(f"Stage: {completed}/{total}")

    def _render_selection_details(self, index: QModelIndex, *, activate_job_tab: bool) -> None:
        """Render labels, progress, actions, and messages for one selected row."""

        message = self._model.data(index, int(JobRole.ERROR)) or self._model.data(index, int(JobRole.MESSAGE))
        self.selected_job_message.setText(str(message))
        output_path = str(self._model.data(index, int(JobRole.OUTPUT_PATH)))
        self.selected_job_output.setText(output_path)
        self.job_name_value.setText(str(self._model.data(self._model.index(index.row(), 1), int(Qt.ItemDataRole.DisplayRole))))
        state = self._model.data(index, int(JobRole.STATE))
        stage = self._model.data(index, int(JobRole.STAGE))
        self.job_state_value.setText(str(state).replace("_", " ").title())
        self.job_stage_value.setText(str(stage or "Waiting"))
        snapshot = self._model.snapshot_at(index)
        progress = snapshot.last_progress if snapshot is not None else None
        job_id = str(self._model.data(index, int(JobRole.JOB_ID)))
        if state == JobState.COMPLETED.value:
            self._queue_preview_job_id = job_id
            self.queue_preview.show_final_output(Path(output_path))
        elif state == JobState.RUNNING.value and progress is not None and progress.stage is PipelineStage.UPSCALE:
            original_preview_path = progress.original_preview_image_path
            upscaled_preview_path = progress.upscaled_preview_image_path
            if original_preview_path is None and upscaled_preview_path is None:
                self._queue_preview_job_id = None
                self.queue_preview.clear("Live samples appear every 16 frames.")
            else:
                self._queue_preview_job_id = job_id
                self.queue_preview.show_sampled_frames(original_preview_path, upscaled_preview_path)
        elif state == JobState.RUNNING.value:
            if self._queue_preview_job_id != job_id or not self.queue_preview.has_live_samples:
                self._queue_preview_job_id = None
                self.queue_preview.clear("Live samples appear during the upscaling stage.")
        else:
            self._queue_preview_job_id = None
            self.queue_preview.clear("Select a running or completed job to preview its output.")
        completed = int(self._model.data(index, int(JobRole.PROGRESS_COMPLETED)) or 0)
        total = self._model.data(index, int(JobRole.PROGRESS_TOTAL))
        self._update_progress_details(state, stage, completed, total)
        position = self._model.data(index, int(JobRole.QUEUE_POSITION))
        self.move_job_up_button.setEnabled(position is not None and int(position) > 0)
        self.move_job_down_button.setEnabled(position is not None and int(position) + 1 < self._model.pending_count)
        self.message_widget.select_job(str(self._model.data(index, int(JobRole.JOB_ID))), activate=activate_job_tab)

    @Slot()
    def _refresh_selected_job(self, *, activate_job_tab: bool = False) -> None:
        index = self.queue_table.currentIndex()
        if not index.isValid():
            self._clear_selection_details()
            return
        self._render_selection_details(index, activate_job_tab=activate_job_tab)

    def _move_selected_job(self, offset: int) -> None:
        self._model.move_pending(self.queue_table.currentIndex(), offset)

    @Slot()
    def _open_preferences(self) -> None:
        if self._tool_validator is None or self._settings_store is None:
            return
        dialog = ToolSettingsDialog(self._settings, self._tool_validator, self._settings_store, self)
        dialog.settings_saved.connect(self._apply_settings)
        dialog.exec()

    @Slot(object)
    def _apply_settings(self, value: object) -> None:
        if isinstance(value, ApplicationSettings):
            self._settings = value
            self.editor.apply_settings(value)
            self.source_preview.set_audio_preferences(value.preview_muted, value.preview_volume)
            self.queue_preview.set_audio_preferences(value.preview_muted, value.preview_volume)
            if self._submission is not None:
                self._submission.apply_settings(value)
            self._append_global_message("Application settings updated.")

    @Slot(bool, int)
    def _audio_preferences_changed(self, muted: bool, volume: int) -> None:
        """Persist only non-safety preview audio preferences."""

        updated = replace(self._settings, preview_muted=muted, preview_volume=volume)
        if self._settings_store is not None:
            try:
                self._settings_store.save(updated)
            except SettingsError as error:
                self._append_global_message(f"Preview audio preferences could not be saved: {error}")
                return
        self._settings = updated
        self.queue_preview.set_audio_preferences(muted, volume)

    @Slot()
    def _persist_output_directory_preference(self) -> None:
        """Persist the output directory when the draft field is committed."""

        if self._settings_store is None:
            return
        raw_output = self.editor.output_directory.text().strip()
        output_directory = Path(raw_output) if raw_output else None
        if output_directory == self._settings.recent_output_directory:
            return
        updated = replace(self._settings, recent_output_directory=output_directory)
        try:
            self._settings_store.save(updated)
        except SettingsError as error:
            self._append_global_message(f"Output directory preference could not be saved: {error}")
            return
        self._settings = updated
        if self._submission is not None:
            self._submission.apply_settings(updated)

    def closeEvent(self, event: object) -> None:  # pylint: disable=invalid-name
        """Record session shutdown before Qt releases the window."""
        self._persist_output_directory_preference()
        self.source_preview.shutdown()
        self.queue_preview.shutdown()
        if not self._global_shutdown_recorded:
            self._append_global_message("Application shutting down.")
            self._global_shutdown_recorded = True
        super().closeEvent(event)  # type: ignore[arg-type]
