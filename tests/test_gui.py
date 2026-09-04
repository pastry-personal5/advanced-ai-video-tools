"""Headless tests for Qt queue bridging, model roles, and the window shell."""

# Pytest injects fixtures through same-named function parameters.
# pylint: disable=redefined-outer-name,too-many-lines

from __future__ import annotations

import os
import signal
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QLockFile, QModelIndex, QObject, Qt, Signal  # noqa: E402  # pylint: disable=wrong-import-position,no-name-in-module
from PySide6.QtGui import QImage, QKeyEvent, QPainter, QPalette, QPixmap  # noqa: E402  # pylint: disable=wrong-import-position,no-name-in-module
from PySide6.QtMultimedia import QMediaPlayer  # noqa: E402  # pylint: disable=wrong-import-position,no-name-in-module
from PySide6.QtTest import QTest  # noqa: E402  # pylint: disable=wrong-import-position,no-name-in-module
from PySide6.QtWidgets import QApplication, QGroupBox, QLabel, QPushButton, QSlider, QSplitter, QStyle, QStyleOptionViewItem, QToolButton, QWidget  # noqa: E402  # pylint: disable=wrong-import-position,no-name-in-module

from advanced_ai_video_tools.core.models import JobRequest, JobState, PipelineStage, ProgressEvent  # noqa: E402  # pylint: disable=wrong-import-position
from advanced_ai_video_tools.gui.application import _GuiSigintBridge, create_gui_runtime  # noqa: E402  # pylint: disable=wrong-import-position
from advanced_ai_video_tools.gui.editor import SOURCE_CLIP_LIST_WIDTH  # noqa: E402  # pylint: disable=wrong-import-position
from advanced_ai_video_tools.gui.jobs import JobListModel, JobRole, QueueSnapshotBridge  # noqa: E402  # pylint: disable=wrong-import-position
from advanced_ai_video_tools.gui.messages import MessageEvent, MessageHistory, MessageWidget  # noqa: E402  # pylint: disable=wrong-import-position
from advanced_ai_video_tools.gui.preview import FULLSCREEN_HELP_MARGIN, FULLSCREEN_SHORTCUTS, PREVIEW_PANE_MINIMUM_WIDTH, SHORTCUT_HELP, VOLUME_ICON_COLOR, VOLUME_ICON_OPTICAL_OFFSET, FullscreenCommand, QueuePreviewPane, SourcePreviewPane, resolve_fullscreen_shortcut  # noqa: E402  # pylint: disable=wrong-import-position
from advanced_ai_video_tools.gui.theme import CONTROL_HEIGHT, CONTROL_RADIUS, MAJOR_REGION_GAP, SPACE_2, SPACE_3, apply_dark_theme  # noqa: E402  # pylint: disable=wrong-import-position
from advanced_ai_video_tools.gui.window import JOB_NAME_COLUMN_WIDTH, MainWindow  # noqa: E402  # pylint: disable=wrong-import-position
from advanced_ai_video_tools.services.pipeline import PipelineCancelled  # noqa: E402  # pylint: disable=wrong-import-position
from advanced_ai_video_tools.services.queue import QueueJobOutcome, QueueJobSnapshot  # noqa: E402  # pylint: disable=wrong-import-position
from advanced_ai_video_tools.system.settings import ApplicationSettings, SettingsStore  # noqa: E402  # pylint: disable=wrong-import-position


@pytest.fixture(scope="module")
def qt_app() -> QApplication:
    """Provide one offscreen Qt application for model and widget tests."""

    existing = QCoreApplication.instance()
    if existing is not None and not isinstance(existing, QApplication):
        raise RuntimeError("a non-GUI Qt application already exists")
    return existing or QApplication(["ai-video-tools-tests"])


def _process_until(qt_app: QApplication, predicate: Callable[[], bool], timeout: float = 1.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qt_app.processEvents()
        if predicate():
            return True
        time.sleep(0.001)
    qt_app.processEvents()
    return predicate()


def test_gui_theme_is_always_dark(qt_app: QApplication) -> None:
    """The application-owned palette does not follow the system appearance."""

    apply_dark_theme(qt_app)

    assert qt_app.palette().color(QPalette.ColorRole.Window).name() == "#202124"
    assert qt_app.palette().color(QPalette.ColorRole.Text).name() == "#f1f3f4"
    assert f"border-radius: {CONTROL_RADIUS}px" in qt_app.styleSheet()
    assert "QProgressBar::chunk" in qt_app.styleSheet()
    assert "border-radius: 0px;" in qt_app.styleSheet()
    assert "QSplitter#contentMessageSplitter" in qt_app.styleSheet()
    assert "QSplitter::handle:hover" not in qt_app.styleSheet()
    assert "QHeaderView::section:last" in qt_app.styleSheet()
    assert "QHeaderView::section:first" not in qt_app.styleSheet()
    assert "text-align: center;" in qt_app.styleSheet()
    assert "QHeaderView {\n    background: #2a2b2e;\n    border: none;\n    border-bottom: 1px solid #5f6368;\n    border-radius: 0px;\n}" in qt_app.styleSheet()
    assert "border-right: 1px solid #45474b;" in qt_app.styleSheet()
    assert "QTableView#queueActiveView QHeaderView::section" in qt_app.styleSheet()
    assert "background: #2a2b2e;" in qt_app.styleSheet()
    assert "QTableView#queueActiveView:focus" in qt_app.styleSheet()
    assert "QTableView#queueActiveView,\nQTableView#queueUpNextView,\nQTableView#queueHistoryView {\n    padding: 0;\n    background: #17181a;\n    font-size: 10pt;\n    border: 1px solid #45474b;\n    border-radius: 0px;\n}" in qt_app.styleSheet()
    assert "QDialog#fullscreenPreviewHelpPanel" in qt_app.styleSheet()
    assert "background: rgba(37, 38, 41, 128);" in qt_app.styleSheet()
    assert f"min-height: {CONTROL_HEIGHT - 2}px" in qt_app.styleSheet()


def test_gui_theme_text_contrast_and_scaled_control_inventory(qt_app: QApplication) -> None:
    """Headless checks cover contrast-safe palette roles and fixed high-DPI hit areas."""

    apply_dark_theme(qt_app)
    palette = qt_app.palette()
    window_color = palette.color(QPalette.ColorRole.Window)
    text_color = palette.color(QPalette.ColorRole.Text)
    disabled_color = palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text)

    def luminance(color: object) -> float:
        red, green, blue = color.redF(), color.greenF(), color.blueF()  # type: ignore[attr-defined]
        channels = [component / 12.92 if component <= 0.04045 else ((component + 0.055) / 1.055) ** 2.4 for component in (red, green, blue)]
        return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]

    assert (luminance(text_color) + 0.05) / (luminance(window_color) + 0.05) > 8.0
    assert (luminance(disabled_color) + 0.05) / (luminance(window_color) + 0.05) > 3.0
    assert CONTROL_HEIGHT == 32


def _snapshot(tmp_path: Path, job_id: str, state: JobState, position: int | None, *, revision: int, progress: ProgressEvent | None = None) -> QueueJobSnapshot:
    created = datetime(2026, 8, 21, tzinfo=timezone.utc)
    request = JobRequest((tmp_path / f"{job_id}.mov",), tmp_path, explicit_output_path=tmp_path / f"{job_id}.mp4", created_at=created)
    return QueueJobSnapshot(job_id, request, state, position, progress, revision)


class FakeQueue:
    """Small queue surface used to isolate Qt presentation behavior."""

    def __init__(self, snapshots: tuple[QueueJobSnapshot, ...] = ()) -> None:
        self.initial = snapshots
        self.cancelled: list[str] = []
        self.moves: list[tuple[str, int]] = []
        self.outcomes: dict[str, QueueJobOutcome] = {}

    def snapshots(self) -> tuple[QueueJobSnapshot, ...]:
        """Return the configured initial model records."""

        return self.initial

    def cancel(self, job_id: str) -> bool:
        """Record one model cancellation request."""

        self.cancelled.append(job_id)
        return True

    def move(self, job_id: str, position: int) -> None:
        """Record one pending reorder request."""

        self.moves.append((job_id, position))

    def wait(self, job_id: str, timeout: float | None = None) -> QueueJobOutcome | None:
        """Return a configured nonblocking terminal outcome."""

        del timeout
        return self.outcomes.get(job_id)


class UnusedRunner:
    """A runtime dependency that must remain idle until job creation exists."""

    def execute_pipeline(self, *_args: object, **_kwargs: object) -> object:
        """Fail if the empty initial shell unexpectedly starts processing."""

        raise AssertionError("the initial GUI shell must not submit work by itself")


def test_bridge_mutates_model_on_qt_thread_and_rejects_stale_revisions(qt_app: QApplication, tmp_path: Path) -> None:
    """Cross-thread callbacks arrive safely and cannot regress newer state."""

    queue = FakeQueue()
    bridge = QueueSnapshotBridge()
    model = JobListModel(queue, bridge)  # type: ignore[arg-type]
    progress = ProgressEvent(PipelineStage.EXTRACT, 4, 10, "Extracting frames")
    running = _snapshot(tmp_path, "alpha", JobState.RUNNING, None, revision=4, progress=progress)

    worker = threading.Thread(target=bridge.forward, args=(running,))
    worker.start()
    worker.join()

    assert _process_until(qt_app, lambda: model.rowCount() == 1)
    index = model.index(0, 0)
    assert model.data(index, int(JobRole.JOB_ID)) == "alpha"
    assert model.data(index, int(JobRole.STATE)) == "running"
    assert model.data(index, int(JobRole.PROGRESS_COMPLETED)) == 4
    assert model.data(index, int(JobRole.PROGRESS_TOTAL)) == 10
    assert model.data(index, int(JobRole.OUTPUT_PATH)) == str(tmp_path / "alpha.mp4")
    assert model.headerData(0, Qt.Orientation.Horizontal) == "Status"
    assert model.headerData(1, Qt.Orientation.Horizontal) == "Job Name"
    assert model.headerData(0, Qt.Orientation.Horizontal, Qt.ItemDataRole.TextAlignmentRole) == Qt.AlignmentFlag.AlignCenter
    assert model.headerData(2, Qt.Orientation.Horizontal) == "Remove"
    assert "Status: Running" in str(model.data(index, int(Qt.ItemDataRole.AccessibleTextRole)))
    assert model.data(model.index(0, 1), int(Qt.ItemDataRole.ToolTipRole)) == "Job name: alpha.mov"

    bridge.forward(_snapshot(tmp_path, "alpha", JobState.QUEUED, 0, revision=1))
    qt_app.processEvents()
    assert model.data(index, int(JobRole.STATE)) == "running"


def test_model_exposes_pending_order_actions_and_terminal_error(qt_app: QApplication, tmp_path: Path) -> None:
    """The typed model maps queue control and failure facts without media logic."""

    first = _snapshot(tmp_path, "first", JobState.QUEUED, 0, revision=0)
    second = _snapshot(tmp_path, "second", JobState.QUEUED, 1, revision=0)
    queue = FakeQueue((first, second))
    bridge = QueueSnapshotBridge()
    model = JobListModel(queue, bridge)  # type: ignore[arg-type]
    second_index = model.index(1, 0)

    assert model.pending_count == 2
    assert model.move_pending(second_index, -1)
    assert queue.moves == [("second", 0)]
    assert model.cancel(second_index)
    assert queue.cancelled == ["second"]

    cancelled = _snapshot(tmp_path, "second", JobState.CANCELLED, None, revision=2)
    queue.outcomes["second"] = QueueJobOutcome("second", JobState.CANCELLED, error=PipelineCancelled("Cancelled by user", PipelineStage.VALIDATE))
    bridge.forward(cancelled)
    assert _process_until(qt_app, lambda: model.data(model.index(1, 0), int(JobRole.ERROR)) == "Cancelled by user")
    assert model.data(model.index(1, 0), int(JobRole.MESSAGE)) == "Cancelled"

    failed = _snapshot(tmp_path, "failed", JobState.FAILED, None, revision=1)
    bridge.forward(failed)
    assert _process_until(qt_app, lambda: model.rowCount() == 3)
    assert model.data(model.index(2, 2), int(Qt.ItemDataRole.DisplayRole)) == "Remove"
    assert all("Retry" not in str(model.data(model.index(row, column), int(Qt.ItemDataRole.DisplayRole))) for row in range(model.rowCount()) for column in range(model.columnCount()))


def test_main_window_tracks_selection_progress_and_controls(qt_app: QApplication, tmp_path: Path) -> None:  # pylint: disable=too-many-statements
    """The native shell renders measured progress and delegates user actions."""

    first = _snapshot(tmp_path, "first", JobState.RUNNING, None, revision=2, progress=ProgressEvent(PipelineStage.ENCODE, 3, 8, "Encoding output"))
    second = _snapshot(tmp_path, "second", JobState.QUEUED, 0, revision=0)
    queue = FakeQueue((first, second))
    bridge = QueueSnapshotBridge()
    model = JobListModel(queue, bridge)  # type: ignore[arg-type]
    window = MainWindow(model, ApplicationSettings(target_height=2160), tmp_path / "application.log")
    window.show()
    qt_app.processEvents()
    assert window.windowTitle() == "Advanced AI Video Tools"
    assert not window.job_creation_button.icon().isNull()
    assert not window.queue_monitoring_button.icon().isNull()
    assert window.minimumWidth() == 1400
    assert window.minimumHeight() == 880
    assert window.queue_table.height() == 240
    margins = window.queue_table.contentsMargins()
    assert (margins.left(), margins.top(), margins.right(), margins.bottom()) == (1, 1, 1, 1)
    assert not window.queue_table.verticalHeader().isVisible()
    assert not window.queue_table.showGrid()
    assert window.queue_table.horizontalHeader().sectionResizeMode(1).name == "Fixed"
    assert window.queue_table.horizontalHeader().sectionResizeMode(2).name == "Fixed"
    assert window.move_job_up_button.font().pointSize() == 9
    assert window.move_job_down_button.font().pointSize() == 9
    assert window.move_job_up_button.height() == 28
    assert window.move_job_down_button.height() == 28
    job_queue_group = window.findChild(QGroupBox, "queueGroup")
    assert job_queue_group is not None
    assert job_queue_group.title() == "Job Queue"
    assert job_queue_group.layout().contentsMargins().left() == 16

    window.queue_table.setCurrentIndex(model.index(0, 0))
    qt_app.processEvents()
    assert window.selected_job_message.text() == "Encoding output"
    assert window.job_name_value.text() == "first.mov"
    assert window.job_state_value.text() == "Running"
    assert window.job_stage_value.text() == "encode"
    assert window.selected_job_stage_progress.maximum() == 8
    assert window.selected_job_stage_progress.value() == 3
    assert window.selected_job_stage_progress.format() == "Stage: 3/8"
    assert window.selected_job_overall_progress.value() > 0
    assert window.selected_job_overall_progress.format().startswith("Whole job:")
    assert window.findChild(QPushButton, "cancelSelectedJobButton") is None
    active_view = window.region_views["active"]
    assert active_view.isColumnHidden(2) is False
    assert active_view.horizontalHeader().sectionResizeMode(0).name == "Fixed"
    assert active_view.horizontalHeader().sectionResizeMode(1).name == "Fixed"
    assert active_view.horizontalHeader().sectionResizeMode(2).name == "Fixed"
    assert active_view.horizontalHeader().defaultAlignment() == Qt.AlignmentFlag.AlignCenter
    assert active_view.textElideMode().name == "ElideRight"
    assert active_view.model().data(active_view.model().index(0, 2), Qt.ItemDataRole.DisplayRole) == "Cancel"
    action_pixmap = QPixmap(64, 36)
    action_option = QStyleOptionViewItem()
    action_option.rect = action_pixmap.rect()
    action_option.state = QStyle.StateFlag.State_Enabled | QStyle.StateFlag.State_Selected
    action_painter = QPainter(action_pixmap)
    active_view.itemDelegateForColumn(2).paint(action_painter, action_option, active_view.model().index(0, 2))
    action_painter.end()
    assert window.findChild(QLabel, "jobActionSummary") is None
    assert window.findChild(QLabel, "logPathLabel") is None
    selected_details = window.findChild(QGroupBox, "selectedJobDetails")
    assert selected_details is not None
    assert selected_details.layout().contentsMargins().left() == SPACE_2
    assert selected_details.layout().verticalSpacing() == 4
    window._handle_region_cell_click("active", active_view.model().index(0, 2))  # pylint: disable=protected-access
    assert queue.cancelled == ["first"]

    window.queue_table.setCurrentIndex(model.index(1, 0))
    qt_app.processEvents()
    assert not window.move_job_up_button.isEnabled()
    window.close()


def test_queue_monitoring_groups_active_pending_and_history_regions(qt_app: QApplication, tmp_path: Path) -> None:  # pylint: disable=too-many-statements
    """Visible queue regions share one model and preserve canonical selection."""

    active = _snapshot(tmp_path, "active", JobState.RUNNING, None, revision=1)
    pending = _snapshot(tmp_path, "pending", JobState.QUEUED, 0, revision=1)
    failed = _snapshot(tmp_path, "failed", JobState.FAILED, None, revision=1)
    model = JobListModel(FakeQueue((active, pending, failed)), QueueSnapshotBridge())  # type: ignore[arg-type]
    window = MainWindow(model, ApplicationSettings())
    window.show()
    window.queue_monitoring_button.click()
    qt_app.processEvents()

    assert window.region_proxies["active"].rowCount() == 1
    assert window.region_proxies["up_next"].rowCount() == 1
    assert window.region_proxies["history"].rowCount() == 1
    assert all(view.horizontalHeader().sectionResizeMode(0).name == "Fixed" for view in window.region_views.values())
    assert all(view.horizontalHeader().sectionResizeMode(1).name == "Fixed" for view in window.region_views.values())
    assert all(view.horizontalHeader().sectionResizeMode(2).name == "Fixed" for view in window.region_views.values())
    assert all(view.horizontalHeader().sectionSize(1) >= JOB_NAME_COLUMN_WIDTH for view in window.region_views.values())
    assert all(view.horizontalHeader().defaultAlignment() == Qt.AlignmentFlag.AlignCenter for view in window.region_views.values())
    assert window.findChild(QLabel, "queueHistoryEmpty") is None
    active_group = window.region_groups["active"]
    up_next_group = window.region_groups["up_next"]
    history_group = window.region_groups["history"]
    assert "QGroupBox#queueActiveGroup,\nQGroupBox#queueUpNextGroup,\nQGroupBox#queueHistoryGroup" in qt_app.styleSheet()
    assert "background: #252629;" in qt_app.styleSheet()
    assert "border-radius: 8px;" in qt_app.styleSheet()
    assert "QGroupBox#queueActiveGroup::title" in qt_app.styleSheet()
    active_origin = active_group.mapTo(window.queue_region_workspace, active_group.rect().topLeft())
    up_next_origin = up_next_group.mapTo(window.queue_region_workspace, up_next_group.rect().topLeft())
    history_origin = history_group.mapTo(window.queue_region_workspace, history_group.rect().topLeft())
    assert active_origin.x() == up_next_origin.x() < history_origin.x()
    assert active_origin.y() < up_next_origin.y()
    assert history_origin.y() == active_origin.y()
    assert abs(history_group.height() - window.queue_region_workspace.height()) <= 1
    assert abs((active_group.height() + up_next_group.height() + SPACE_3) - window.queue_region_workspace.height()) <= 1
    pending_proxy = window.region_proxies["up_next"]
    window.region_views["up_next"].setCurrentIndex(pending_proxy.index(0, 0))
    qt_app.processEvents()
    assert model.data(window.queue_table.currentIndex(), int(JobRole.JOB_ID)) == "pending"
    assert window.job_name_value.text() == "pending.mov"
    assert window.region_views["history"].verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded

    active_view = window.region_views["active"]
    history_view = window.region_views["history"]
    active_view.setFocus()
    active_view.setCurrentIndex(window.region_proxies["active"].index(0, 0))
    QTest.keyClick(active_view, Qt.Key.Key_Down)
    qt_app.processEvents()
    assert window.queue_table.currentIndex().data(int(JobRole.JOB_ID)) == "pending"
    assert window.region_views["up_next"].hasFocus()
    QTest.keyClick(window.region_views["up_next"], Qt.Key.Key_Down)
    qt_app.processEvents()
    assert window.queue_table.currentIndex().data(int(JobRole.JOB_ID)) == "failed"
    assert history_view.hasFocus()
    QTest.keyClick(history_view, Qt.Key.Key_Up)
    qt_app.processEvents()
    assert window.queue_table.currentIndex().data(int(JobRole.JOB_ID)) == "pending"

    window.region_views["active"].setFocus()
    window.region_views["active"].setCurrentIndex(window.region_proxies["active"].index(0, 0))
    QTest.keyClick(window.region_views["active"], Qt.Key.Key_Return)
    QTest.keyClick(window.region_views["active"], Qt.Key.Key_Space)
    assert model.data(window.queue_table.currentIndex(), int(JobRole.JOB_ID)) == "active"
    assert isinstance(model.data(window.queue_table.currentIndex(), int(JobRole.STATE)), str)
    window.close()


def test_main_window_does_not_show_stale_progress_after_cancellation(qt_app: QApplication, tmp_path: Path) -> None:
    """Cancellation states replace retained pipeline progress with clear status."""

    running = _snapshot(tmp_path, "cancel", JobState.RUNNING, None, revision=2, progress=ProgressEvent(PipelineStage.ENCODE, 8, 8, "Encoding output"))
    queue = FakeQueue((running,))
    bridge = QueueSnapshotBridge()
    model = JobListModel(queue, bridge)  # type: ignore[arg-type]
    window = MainWindow(model, ApplicationSettings(target_height=2160), tmp_path / "application.log")
    window.queue_table.setCurrentIndex(model.index(0, 0))
    qt_app.processEvents()

    bridge.forward(_snapshot(tmp_path, "cancel", JobState.CANCELLING, None, revision=3, progress=running.last_progress))
    assert _process_until(qt_app, lambda: window.job_state_value.text() == "Cancelling")
    assert window.selected_job_overall_progress.maximum() == 0
    assert window.selected_job_overall_progress.format() == "Whole job: Cancelling…"
    assert window.selected_job_stage_progress.maximum() == 0

    bridge.forward(_snapshot(tmp_path, "cancel", JobState.CANCELLED, None, revision=4, progress=ProgressEvent(PipelineStage.CLEANUP, 1, 1, "Cleaning up")))
    assert _process_until(qt_app, lambda: window.job_state_value.text() == "Cancelled")
    assert window.selected_job_overall_progress.maximum() == 100
    assert window.selected_job_overall_progress.value() == 0
    assert window.selected_job_overall_progress.format() == "Whole job: Cancelled"
    assert window.selected_job_stage_progress.maximum() == 1
    assert window.selected_job_stage_progress.value() == 0
    assert window.selected_job_stage_progress.format() == "Stage: Cancelled"
    window.close()


def test_gui_preferences_target_height_and_native_preview_boundaries(qt_app: QApplication, tmp_path: Path) -> None:
    """The revised creation surface keeps Preferences, custom height, and native preview boundaries."""

    del qt_app

    class FakeToolValidator(QObject):
        """Signal-compatible validator double for Preferences-menu availability."""

        succeeded = Signal(object)
        failed = Signal(object, str)

    queue = FakeQueue()
    bridge = QueueSnapshotBridge()
    model = JobListModel(queue, bridge)  # type: ignore[arg-type]
    settings_store = SettingsStore(tmp_path / "settings.yaml")
    window = MainWindow(
        model,
        ApplicationSettings(target_height=2160),
        settings_store=settings_store,
        tool_validator=FakeToolValidator(),  # type: ignore[arg-type]
    )

    assert window.preferences_action.text() == "Preferences"
    assert window.preferences_action.isEnabled()
    assert window.findChild(QPushButton, "externalToolsButton") is None
    window.editor.target_height.setValue(1440)
    assert window.editor.target_height.value() == 1440
    assert window.source_preview.player.videoOutput() is window.source_preview.video
    assert window.source_preview.video.aspectRatioMode() == Qt.AspectRatioMode.KeepAspectRatio
    window.close()


def test_upscale_messages_are_throttled_to_progress_summaries(qt_app: QApplication, tmp_path: Path) -> None:
    """Upscale progress is summarized without flooding the job history."""

    queue = FakeQueue()
    bridge = QueueSnapshotBridge()
    model = JobListModel(queue, bridge)  # type: ignore[arg-type]
    window = MainWindow(model, ApplicationSettings(target_height=2160))
    window.show()
    qt_app.processEvents()
    for revision, completed in enumerate((0, 1, 9, 10, 11, 20, 100), start=1):
        progress = ProgressEvent(PipelineStage.UPSCALE, completed, 100, f"Processed {completed} frames")
        window._handle_queue_snapshot(_snapshot(tmp_path, "upscale", JobState.RUNNING, None, revision=revision, progress=progress))  # pylint: disable=protected-access

    lines = window.message_widget.history.job_lines("upscale")
    progress_lines = [line for line in lines if "Upscale progress:" in line]
    assert len(progress_lines) == 4
    assert progress_lines[0].endswith("0% (0/100 frames).")
    assert progress_lines[1].endswith("10% (10/100 frames).")
    assert progress_lines[2].endswith("20% (20/100 frames).")
    assert progress_lines[3].endswith("100% (100/100 frames).")
    window.close()


def test_background_queue_refresh_preserves_active_message_tab(qt_app: QApplication, tmp_path: Path) -> None:
    """Queue updates do not switch away from the tab chosen by the user."""

    snapshot = _snapshot(tmp_path, "running", JobState.RUNNING, None, revision=1, progress=ProgressEvent(PipelineStage.ENCODE, 1, 2, "Encoding"))
    queue = FakeQueue((snapshot,))
    bridge = QueueSnapshotBridge()
    model = JobListModel(queue, bridge)  # type: ignore[arg-type]
    window = MainWindow(model, ApplicationSettings(target_height=2160))
    window.show()
    qt_app.processEvents()
    assert window.message_tabs.currentIndex() == 0
    window.queue_table.setCurrentIndex(model.index(0, 0))
    assert window.message_tabs.currentIndex() == 1
    window.message_tabs.setCurrentIndex(0)
    window._refresh_selected_job()  # pylint: disable=protected-access
    assert window.message_tabs.currentIndex() == 0
    window.close()


def test_message_history_keeps_timestamped_lines_and_job_selection(qt_app: QApplication) -> None:
    """Message presentation is session-only, unbounded, and selection-driven."""

    del qt_app
    history = MessageHistory(clock=lambda: datetime(2026, 8, 22, 12, 34, 56))
    widget = MessageWidget(history)
    for number in range(6):
        widget.append(MessageEvent(f"Global {number}"))
    for number in range(6):
        widget.append(MessageEvent(f"Job {number}", "job-1"))
    assert widget.global_messages.toPlainText().splitlines() == [
        "[2026-08-22 12:34:56] Global 0",
        "[2026-08-22 12:34:56] Global 1",
        "[2026-08-22 12:34:56] Global 2",
        "[2026-08-22 12:34:56] Global 3",
        "[2026-08-22 12:34:56] Global 4",
        "[2026-08-22 12:34:56] Global 5",
    ]
    assert widget.global_messages.minimumHeight() >= widget.global_messages.fontMetrics().lineSpacing() * 5
    assert widget.global_messages.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOn
    assert widget.minimumHeight() >= widget.global_messages.minimumHeight() + widget.tabs.tabBar().sizeHint().height()
    widget.select_job("job-1")
    assert widget.tabs.currentIndex() == 1
    assert widget.job_messages.toPlainText().splitlines()[-1].endswith("Job 5")
    widget.select_job(None)
    assert widget.job_messages.toPlainText() == "No job is selected."
    assert widget.global_messages.isReadOnly()


def test_main_window_message_area_is_splitter_resizable_and_logs_completion(qt_app: QApplication, tmp_path: Path) -> None:  # pylint: disable=too-many-statements
    """The integrated panel stays in the window and consumes queue snapshots."""

    queue = FakeQueue()
    bridge = QueueSnapshotBridge()
    model = JobListModel(queue, bridge)  # type: ignore[arg-type]
    window = MainWindow(model, ApplicationSettings(target_height=2160))
    window.show()
    qt_app.processEvents()
    assert window.findChild(QSplitter, "contentMessageSplitter") is not None
    assert window.content_message_splitter.handleWidth() == 12
    assert window.content_message_splitter.handle(1).height() == 12
    assert window.findChild(QPushButton, "externalToolsButton") is None
    assert window.preferences_action.text() == "Preferences"
    assert [window.message_tabs.tabText(index) for index in range(2)] == ["Global Messages", "Job Messages"]
    assert "Application started." in window.global_messages.toPlainText()
    assert "Add clips in order they should be concatenated." in window.global_messages.toPlainText()
    assert window.message_tabs.currentIndex() == 0
    assert window.view_stack.currentIndex() == 0
    assert window.job_creation_button.minimumWidth() == 64
    assert window.job_creation_button.minimumHeight() == 64
    assert window.job_creation_button.width() == 64
    assert window.job_creation_button.height() == 64
    assert f"border-radius: {CONTROL_RADIUS}px" in window.job_creation_button.styleSheet()
    assert "#39485f" in window.job_creation_button.styleSheet()
    assert "QToolButton:checked" in window.job_creation_button.styleSheet()
    assert "background: #303134" in window.job_creation_button.styleSheet()
    assert window.queue_monitoring_button.minimumWidth() == 64
    assert window.queue_monitoring_button.minimumHeight() == 64
    left_gap = window.job_creation_button.geometry().left()
    right_gap = window.navigation_rail.width() - window.job_creation_button.geometry().right() - 1
    basic_settings = window.editor.findChild(QGroupBox, "basicSettings")
    assert basic_settings is not None
    rail_origin = window.navigation_rail.mapTo(window, window.navigation_rail.rect().topLeft())
    basic_origin = basic_settings.mapTo(window, basic_settings.rect().topLeft())
    assert basic_origin.x() - (rail_origin.x() + window.navigation_rail.width()) == 0
    button_origin = window.job_creation_button.mapTo(window, window.job_creation_button.rect().topLeft())
    assert basic_origin.x() - (button_origin.x() + window.job_creation_button.width()) == SPACE_2
    assert left_gap == right_gap == SPACE_2
    assert left_gap == 8
    assert right_gap == 8
    splitter_origin = window.content_message_splitter.mapTo(window, window.content_message_splitter.rect().topLeft())
    assert splitter_origin.x() - (rail_origin.x() + window.navigation_rail.width()) == 0
    assert splitter_origin.x() - (button_origin.x() + window.job_creation_button.width()) == right_gap
    window.queue_monitoring_button.click()
    assert window.view_stack.currentIndex() == 1
    assert window.preview_stack.currentIndex() == 1
    assert not window.job_creation_button.isChecked()
    window.job_creation_button.click()
    assert window.view_stack.currentIndex() == 0
    assert window.preview_stack.currentIndex() == 0
    assert window.queue_monitoring_button.isEnabled()
    assert window.editor.findChild(QGroupBox, "sourceClipListGroup").title() == "Source Clips"
    assert window.source_preview.title() == "Preview"
    assert not window.source_preview.preview_label.isVisible()
    assert window.source_preview.progress_slider.accessibleName() == "Preview progress"
    assert window.source_preview.progress_slider.toolTip() == "Seek preview"
    assert not window.source_preview.progress_slider.isEnabled()
    window.source_preview._duration_changed(125000)  # pylint: disable=protected-access
    window.source_preview._position_changed(61500)  # pylint: disable=protected-access
    assert window.source_preview.progress_slider.maximum() == 125000
    assert window.source_preview.progress_slider.value() == 61500
    assert window.source_preview.preview_time_label.text() == "1:01 / 2:05"
    assert window.source_preview.volume_label.text() == "Output volume"
    assert window.source_preview.volume_label.contentsMargins().right() == 16
    assert window.source_preview.mute_label.text() == "Mute"
    assert window.source_preview.mute_label.buddy() is window.source_preview.mute_toggle
    progress_row = window.source_preview.layout().itemAt(2).layout()
    assert progress_row.itemAt(0).widget() is window.source_preview.progress_slider
    assert progress_row.itemAt(1).widget() is window.source_preview.preview_time_label
    audio_controls = window.source_preview.layout().itemAt(4).layout()
    assert audio_controls.itemAt(0).widget() is window.source_preview.dimension_info_and_volume_control_row
    volume_controls = window.source_preview.dimension_info_and_volume_control_row.layout()
    assert [volume_controls.itemAt(index).widget() for index in range(5)] == [window.source_preview.dimension_label, window.source_preview.volume_label, window.source_preview.minimum_volume_icon, window.source_preview.volume_slider, window.source_preview.maximum_volume_icon]
    volume_widgets = [window.source_preview.volume_label, window.source_preview.minimum_volume_icon, window.source_preview.volume_slider, window.source_preview.maximum_volume_icon]
    assert len({widget.geometry().center().y() for widget in volume_widgets}) == 1
    assert window.source_preview.dimension_info_and_volume_control_row.height() == 24
    assert {widget.height() for widget in volume_widgets} == {24}
    mute_controls = audio_controls.itemAt(1).layout()
    assert mute_controls.itemAt(0).spacerItem() is not None
    mute_group = mute_controls.itemAt(1).layout()
    assert [mute_group.itemAt(index).widget() for index in range(2)] == [window.source_preview.mute_toggle, window.source_preview.mute_label]
    window.editor.add_inputs((tmp_path / "first.mov",))
    assert window.findChild(QLabel, "sourcePreviewSource") is None
    assert window.source_preview.minimumWidth() == PREVIEW_PANE_MINIMUM_WIDTH
    assert window.editor.inputs.width() <= SOURCE_CLIP_LIST_WIDTH
    window.source_preview._preview_error(QMediaPlayer.Error.ResourceError, "Unsupported preview media")  # pylint: disable=protected-access
    assert "Preview unavailable; preflight can still inspect this clip." in window.global_messages.toPlainText()
    assert window.source_preview.preview_label.text() == "Preview unavailable; preflight can still inspect this clip."
    assert window.source_preview.preview_label.isVisible()
    window.editor.output_directory.setText(str(tmp_path))
    assert window.editor.create_job_request().inputs == (tmp_path / "first.mov",)
    assert window.source_preview.play_pause_button.isEnabled()
    assert window.source_preview.previous_button.text() == "←"
    assert window.source_preview.next_button.text() == "→"
    assert window.source_preview.fullscreen_button.text() == "⛶"
    assert window.source_preview.play_pause_button.text() == "▶"
    controls = window.source_preview.layout().itemAt(3).layout()
    assert controls.itemAt(0).layout() is not None
    assert [controls.itemAt(0).layout().itemAt(index).widget() for index in range(3)] == [window.source_preview.play_pause_button, window.source_preview.first_frame_button, window.source_preview.last_frame_button]
    assert controls.itemAt(1).spacerItem() is not None
    assert controls.itemAt(2).layout() is not None
    assert [controls.itemAt(2).layout().itemAt(index).widget() for index in range(3)] == [window.source_preview.previous_button, window.source_preview.next_button, window.source_preview.fullscreen_button]
    for button in (window.source_preview.play_pause_button, window.source_preview.first_frame_button, window.source_preview.last_frame_button, window.source_preview.previous_button, window.source_preview.next_button, window.source_preview.fullscreen_button):
        assert button.size().width() == 32
        assert button.size().height() == 32
        assert button.font().pointSizeF() == pytest.approx(QApplication.font().pointSizeF() * 2)
        assert button.toolTip() == button.accessibleName()
        assert "padding: 0px" in button.styleSheet()
    assert "color: #b8bcc2" in window.source_preview.previous_button.styleSheet()
    assert "color: #b8bcc2" in window.source_preview.next_button.styleSheet()
    assert "background:" not in window.source_preview.previous_button.styleSheet()
    assert "border:" not in window.source_preview.previous_button.styleSheet()
    for icon in (window.source_preview.minimum_volume_icon, window.source_preview.maximum_volume_icon):
        image = icon.pixmap().toImage()
        assert any(image.pixelColor(x, y).name() == VOLUME_ICON_COLOR for x in range(image.width()) for y in range(image.height()))
        ink_rows = [y for y in range(image.height()) if any(image.pixelColor(x, y).alpha() > 0 for x in range(image.width()))]
        assert min(ink_rows) == 5 + VOLUME_ICON_OPTICAL_OFFSET
    assert window.source_preview.play_pause_button.accessibleName() == "Play preview"
    window.source_preview._playback_state_changed(QMediaPlayer.PlaybackState.PlayingState)  # pylint: disable=protected-access
    assert window.source_preview.play_pause_button.accessibleName() == "Pause preview"
    assert window.source_preview.play_pause_button.toolTip() == "Pause preview"
    window.source_preview._playback_state_changed(QMediaPlayer.PlaybackState.PausedState)  # pylint: disable=protected-access
    assert window.source_preview.play_pause_button.accessibleName() == "Play preview"
    assert window.source_preview.audio.isMuted()
    assert window.source_preview.video.aspectRatioMode() == Qt.AspectRatioMode.KeepAspectRatio
    assert window.source_preview.video.sizePolicy().verticalPolicy().name == "Expanding"
    window.source_preview._media_status_changed(QMediaPlayer.MediaStatus.EndOfMedia)  # pylint: disable=protected-access
    assert not window.source_preview.previous_button.isEnabled()
    window.editor.add_inputs((tmp_path / "second.mov",))
    assert window.editor.inputs.currentRow() == 1
    assert window.source_preview.player.source().toLocalFile() == str(tmp_path / "second.mov")
    assert window.source_preview.previous_button.isEnabled()
    assert not window.source_preview.next_button.isEnabled()
    window.source_preview.previous_button.click()
    assert window.editor.inputs.currentRow() == 0
    assert window.source_preview.title() == "Preview"
    assert not window.source_preview.preview_label.isVisible()
    window.close()


def test_job_creation_major_region_gaps_are_equal(qt_app: QApplication) -> None:
    """Editor columns and the tall preview boundary use one gap token."""

    window = MainWindow(JobListModel(FakeQueue(), QueueSnapshotBridge()), ApplicationSettings(target_height=2160))  # type: ignore[arg-type]
    window.resize(1400, 880)
    window.show()
    qt_app.processEvents()

    editor_columns = window.editor.layout().itemAt(0).layout()
    workspace_layout = window.findChild(QWidget, "mainWorkspace").layout()
    assert editor_columns.spacing() == MAJOR_REGION_GAP
    assert workspace_layout.spacing() == MAJOR_REGION_GAP

    basic_settings = window.editor.findChild(QGroupBox, "basicSettings")
    source_group = window.editor.findChild(QGroupBox, "sourceClipListGroup")
    assert basic_settings is not None
    assert source_group is not None
    editor_origin = window.editor.mapTo(window, window.editor.rect().topLeft())
    left_workspace_origin = window.content_message_splitter.mapTo(window, window.content_message_splitter.rect().topLeft())
    source_origin = source_group.mapTo(window, source_group.rect().topLeft())
    basic_origin = basic_settings.mapTo(window, basic_settings.rect().topLeft())
    preview_origin = window.source_preview.mapTo(window, window.source_preview.rect().topLeft())
    basic_right = basic_origin.x() + basic_settings.width()
    left_workspace_right = left_workspace_origin.x() + window.content_message_splitter.width()
    assert source_origin.x() - basic_right == preview_origin.x() - left_workspace_right == MAJOR_REGION_GAP
    assert editor_origin.x() <= basic_origin.x()
    assert preview_origin.y() == left_workspace_origin.y()
    assert window.source_preview.height() == window.content_message_splitter.height()
    window.close()


def test_main_views_share_a_narrow_message_column_and_tall_preview_stack(qt_app: QApplication) -> None:
    """Both views keep one message size while their right preview fills height."""

    window = MainWindow(JobListModel(FakeQueue(), QueueSnapshotBridge()), ApplicationSettings(target_height=2160))  # type: ignore[arg-type]
    window.resize(1400, 880)
    window.show()
    qt_app.processEvents()

    message_size = window.message_widget.size()
    assert window.editor.inputs.maximumWidth() == SOURCE_CLIP_LIST_WIDTH
    assert window.message_widget.width() == window.content_message_splitter.width()
    assert window.message_widget.width() < window.centralWidget().width()
    assert window.source_preview.isVisible()
    assert not window.queue_preview.isVisible()
    assert window.source_preview.height() >= window.centralWidget().height() - (SPACE_2 * 6)

    window.queue_monitoring_button.click()
    qt_app.processEvents()
    assert not window.source_preview.isVisible()
    assert window.queue_preview.isVisible()
    assert window.queue_preview.height() == window.source_preview.height()
    assert window.message_widget.size() == message_size
    window.close()


def test_source_preview_expands_without_forcing_a_pane_ratio(qt_app: QApplication) -> None:
    """The tall pane can follow window height while video keeps native aspect."""

    pane = SourcePreviewPane()
    pane.setMinimumWidth(0)
    pane.resize(520, 760)
    pane.show()
    qt_app.processEvents()

    assert not pane.hasHeightForWidth()
    assert pane.width() == 520
    assert pane.height() == 760
    assert pane.video.aspectRatioMode() == Qt.AspectRatioMode.KeepAspectRatio
    assert not pane.progress_slider.isEnabled()
    pane.shutdown()
    assert pane.player.videoOutput() is None
    assert pane.player.audioOutput() is None
    pane.close()


def test_queue_preview_switches_from_paired_samples_to_looping_final_video(qt_app: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # pylint: disable=too-many-statements
    """Queue preview exposes Original, Upscaled, then an autoplaying final video."""

    del qt_app
    output = tmp_path / "running.mp4"
    output.touch()
    original_frame = tmp_path / "original-frame-000000016.png"
    upscaled_frame = tmp_path / "upscaled-frame-000000016.png"
    original_frame.touch()
    upscaled_frame.touch()
    running = _snapshot(
        tmp_path,
        "running",
        JobState.RUNNING,
        None,
        revision=1,
        progress=ProgressEvent(
            PipelineStage.UPSCALE,
            16,
            48,
            "Upscaling frame 16 of 48",
            original_frame,
            upscaled_frame,
        ),
    )
    model = JobListModel(FakeQueue((running,)), QueueSnapshotBridge())  # type: ignore[arg-type]
    window = MainWindow(model, ApplicationSettings(preview_muted=False, preview_volume=42))
    window.queue_table.setCurrentIndex(model.index(0, 0))
    preview = window.queue_preview

    assert isinstance(preview, QueuePreviewPane)
    assert [preview.tabs.tabText(index) for index in range(preview.tabs.count())] == ["Original", "Upscaled", "Final Video"]
    assert preview.tabs.currentWidget() is preview.original_tab
    assert preview.player.source().isEmpty()
    assert not preview.controls.isVisible()
    preview._frame_loaded(QImage(4, 3, QImage.Format.Format_RGB32), "original", preview._frame_generations["original"])  # pylint: disable=protected-access
    assert preview.original_frame_preview.pixmap() is not None
    preview.tabs.setCurrentWidget(preview.upscaled_tab)
    preview._frame_loaded(QImage(4, 3, QImage.Format.Format_RGB32), "upscaled", preview._frame_generations["upscaled"])  # pylint: disable=protected-access
    assert preview.upscaled_frame_preview.pixmap() is not None
    preview.tabs.setCurrentWidget(preview.final_video_tab)
    assert preview.player.source().isEmpty()

    completed = _snapshot(tmp_path, "running", JobState.COMPLETED, None, revision=2)
    model._apply_snapshot(completed)  # pylint: disable=protected-access
    assert [button.objectName() for button in preview.findChildren(QToolButton) if button.objectName().startswith("queuePreview")] == [
        "queuePreviewPlayPauseButton",
        "queuePreviewFirstFrameButton",
        "queuePreviewLastFrameButton",
    ]
    assert preview.tabs.currentWidget() is preview.final_video_tab
    assert preview.player.source().toLocalFile() == str(output)
    assert preview.player.loops() == QMediaPlayer.Loops.Infinite
    assert preview._playback_requested  # pylint: disable=protected-access
    assert preview.audio.isMuted() is False
    assert preview.audio.volume() == pytest.approx(0.42)
    preview._duration_changed(10_000)  # pylint: disable=protected-access
    preview._position_changed(2_500)  # pylint: disable=protected-access
    assert preview.progress_slider.value() == 2_500
    assert preview.time_label.text() == "0:02 / 0:10"
    seek_positions: list[int] = []
    monkeypatch.setattr(preview.player, "setPosition", seek_positions.append)
    preview.progress_slider.setValue(7_500)
    assert seek_positions == [7_500]
    monkeypatch.setattr(preview.player, "duration", lambda: 10_000)
    preview.go_to_first_frame()
    assert seek_positions == [7_500, 0]
    assert preview.last_frame_wait.indicator.text() == "⌛\nLoading first frame…"
    assert not preview.last_frame_wait.isHidden()
    preview._position_changed(0)  # pylint: disable=protected-access
    assert preview.last_frame_wait.isHidden()
    preview.go_to_last_frame()
    assert seek_positions == [7_500, 0, 9_999]
    assert not preview.last_frame_wait.isHidden()
    preview._position_changed(9_999)  # pylint: disable=protected-access
    assert preview.last_frame_wait.isHidden()

    window.close()


def test_source_preview_keeps_native_rotation_behavior(qt_app: QApplication) -> None:
    """The preview uses the native video output without an application rotation layer."""

    del qt_app
    pane = SourcePreviewPane()
    assert pane.player.videoOutput() is pane.video
    assert pane.video.aspectRatioMode() == Qt.AspectRatioMode.KeepAspectRatio
    assert not hasattr(pane, "rotation_button")
    pane.shutdown()
    pane.close()


def test_source_preview_exposes_playback_controls_only(qt_app: QApplication) -> None:
    """Preview controls cannot introduce editing or processing-boundary actions."""

    del qt_app
    pane = SourcePreviewPane()
    assert {button.objectName() for button in pane.findChildren(QToolButton)} == {
        "previewPreviousButton",
        "previewPlayPauseButton",
        "previewFirstFrameButton",
        "previewLastFrameButton",
        "previewNextButton",
        "previewFullscreenButton",
    }
    assert not hasattr(pane, "trim_start")
    assert not hasattr(pane, "trim_end")
    assert not hasattr(pane, "filter_controls")
    assert not hasattr(pane, "frame_export_button")
    pane.shutdown()
    pane.close()


@pytest.mark.parametrize(("shortcut", "binding"), [(shortcut, binding) for shortcut in FULLSCREEN_SHORTCUTS for binding in shortcut.bindings])
def test_fullscreen_shortcut_registry_resolves_every_documented_binding(shortcut: object, binding: tuple[Qt.Key, Qt.KeyboardModifier]) -> None:
    """Every help entry resolves through the same authoritative registry."""

    key, modifiers = binding
    assert resolve_fullscreen_shortcut(key, modifiers) is shortcut.command  # type: ignore[attr-defined]


def test_fullscreen_shortcut_registry_is_unique_complete_and_layout_tolerant() -> None:
    """Bindings cannot conflict, drift from help, or lose common question-key forms."""

    bindings = [binding for shortcut in FULLSCREEN_SHORTCUTS for binding in shortcut.bindings]
    assert len(bindings) == len(set(bindings))
    assert {shortcut.command for shortcut in FULLSCREEN_SHORTCUTS} == set(FullscreenCommand)
    assert SHORTCUT_HELP.splitlines() == [f"{shortcut.display:<12} {shortcut.description}" for shortcut in FULLSCREEN_SHORTCUTS]
    assert resolve_fullscreen_shortcut(Qt.Key.Key_Slash, Qt.KeyboardModifier.ShiftModifier, "?") is FullscreenCommand.TOGGLE_HELP
    assert resolve_fullscreen_shortcut(Qt.Key.Key_Question, Qt.KeyboardModifier.NoModifier, "?") is FullscreenCommand.TOGGLE_HELP
    assert resolve_fullscreen_shortcut(Qt.Key.Key_0, Qt.KeyboardModifier.KeypadModifier) is FullscreenCommand.FIRST_FRAME
    assert resolve_fullscreen_shortcut(Qt.Key.Key_K, Qt.KeyboardModifier.ShiftModifier, "K") is None
    assert resolve_fullscreen_shortcut(Qt.Key.Key_G, Qt.KeyboardModifier.NoModifier, "g") is None


# pylint: disable=too-many-statements
def test_fullscreen_preview_entry_points_and_keyboard_help(qt_app: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fullscreen preview supports row/pane entry, navigation, help, and exit."""

    window = MainWindow(JobListModel(FakeQueue(), QueueSnapshotBridge()), ApplicationSettings())  # type: ignore[arg-type]
    paths = (tmp_path / "first.mov", tmp_path / "second.mov", tmp_path / "third.mov")
    window.editor.add_inputs(paths)
    window.editor.inputs.setCurrentRow(1)
    window.show()
    qt_app.processEvents()
    frozen_paths = window.editor.input_paths()

    playback_calls: list[str] = []
    monkeypatch.setattr(window.source_preview, "_toggle_playback", lambda: playback_calls.append("toggle"))
    row = window.editor.inputs.itemWidget(window.editor.inputs.item(2))
    assert row is not None
    fullscreen_button = row.findChild(QToolButton, "sourceClipFullscreenButton")
    assert fullscreen_button is not None
    QTest.mouseClick(fullscreen_button, Qt.MouseButton.LeftButton)
    qt_app.processEvents()
    dialog = window.source_preview._fullscreen  # pylint: disable=protected-access
    assert dialog is not None
    assert window.editor.inputs.currentRow() == 2
    assert window.source_preview.player.source().toLocalFile() == str(paths[2])
    assert window.editor.input_paths() == frozen_paths
    assert dialog.findChildren(QToolButton) == []
    assert dialog.findChildren(QSlider) == []
    assert any(label.text() == SHORTCUT_HELP for label in dialog.help_panel.findChildren(QLabel))
    dialog.video.setFocus()
    QTest.keyClick(dialog.video, Qt.Key.Key_K)
    assert playback_calls == ["toggle"]
    dialog.setFocus()
    QTest.keyClick(dialog, Qt.Key.Key_Space)
    assert playback_calls == ["toggle", "toggle"]

    previous: list[str] = []
    next_clip: list[str] = []
    window.source_preview.previous_requested.connect(lambda: previous.append("previous"))
    window.source_preview.next_requested.connect(lambda: next_clip.append("next"))
    dialog.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_J, Qt.KeyboardModifier.NoModifier, "j"))
    dialog.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_L, Qt.KeyboardModifier.NoModifier, "l"))
    assert previous == ["previous"]
    assert next_clip == ["next"]
    dialog.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_X, Qt.KeyboardModifier.NoModifier, "x"))
    assert dialog.findChildren(QToolButton) == []
    dialog.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Shift, Qt.KeyboardModifier.ShiftModifier, ""))
    dialog.keyReleaseEvent(QKeyEvent(QKeyEvent.Type.KeyRelease, Qt.Key.Key_Shift, Qt.KeyboardModifier.NoModifier, ""))
    QTest.keyClick(dialog.video, Qt.Key.Key_Slash, Qt.KeyboardModifier.ShiftModifier)
    assert dialog.help_panel.isVisible()
    QApplication.processEvents()
    assert dialog.help_panel.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert dialog.help_panel.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus
    assert dialog.help_panel.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    title = dialog.help_panel.findChild(QLabel, "fullscreenPreviewHelpTitle")
    help_text = dialog.help_panel.findChild(QLabel, "fullscreenPreviewHelpText")
    assert title is not None and help_text is not None
    help_position = dialog._help_panel_local_position()  # pylint: disable=protected-access
    assert dialog.width() - help_position.x() - dialog.help_panel.width() == FULLSCREEN_HELP_MARGIN
    assert abs(dialog.height() // 2 - (help_position.y() + dialog.help_panel.height() // 2)) <= 1
    QTest.keyClick(dialog.video, Qt.Key.Key_Question)
    assert not dialog.help_panel.isVisible()
    QTest.keyClick(dialog, Qt.Key.Key_G)
    QTest.keyClick(dialog.video, Qt.Key.Key_K)
    assert playback_calls == ["toggle", "toggle", "toggle"]
    for _ in range(10):
        QTest.keyClick(dialog, Qt.Key.Key_G)
        QTest.keyClick(dialog.video, Qt.Key.Key_K)
    assert len(playback_calls) == 13
    assert playback_calls[-10:] == ["toggle"] * 10

    frame_actions: list[str] = []
    monkeypatch.setattr(window.source_preview, "go_to_first_frame", lambda: frame_actions.append("first"))
    monkeypatch.setattr(window.source_preview, "go_to_last_frame", lambda: frame_actions.append("last"))
    dialog.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_0, Qt.KeyboardModifier.NoModifier, "0"))
    dialog.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_9, Qt.KeyboardModifier.NoModifier, "9"))
    assert frame_actions == ["first", "last"]

    window.editor.inputs.setCurrentRow(1)
    dialog.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_P, Qt.KeyboardModifier.ShiftModifier, "P"))
    assert window.editor.inputs.currentRow() == 0
    dialog.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_N, Qt.KeyboardModifier.ShiftModifier, "N"))
    assert window.editor.inputs.currentRow() == 1

    dialog.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Question, Qt.KeyboardModifier.NoModifier, "?"))
    assert dialog.help_panel.isVisible()
    dialog.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier, ""))
    assert not dialog.help_panel.isVisible()
    dialog.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier, ""))
    assert window.source_preview._fullscreen is None  # pylint: disable=protected-access

    window.source_preview.open_fullscreen()
    assert window.source_preview._fullscreen is not None  # pylint: disable=protected-access
    window.source_preview._fullscreen.close()  # pylint: disable=protected-access
    window.close()


def test_source_preview_progress_tracks_duration_and_user_seek(qt_app: QApplication, monkeypatch: pytest.MonkeyPatch) -> None:
    """The timeline mirrors playback and sends user movement to QMediaPlayer."""

    del qt_app
    pane = SourcePreviewPane()
    pane.set_sources((Path("clip.mov"),), 0)
    pane._duration_changed(10_000)  # pylint: disable=protected-access
    pane._position_changed(2_500)  # pylint: disable=protected-access

    seek_positions: list[int] = []
    monkeypatch.setattr(pane.player, "setPosition", seek_positions.append)
    pane.progress_slider.setValue(7_500)

    assert pane.progress_slider.value() == 7_500
    assert seek_positions == [7_500]
    assert pane.preview_time_label.text() == "0:02 / 0:10"
    pane.shutdown()
    pane.close()


def test_source_preview_rapid_playback_toggle_tracks_requested_state(qt_app: QApplication, monkeypatch: pytest.MonkeyPatch) -> None:
    """Rapid input alternates commands without waiting for Qt state signals."""

    del qt_app
    pane = SourcePreviewPane()
    commands: list[str] = []
    monkeypatch.setattr(pane.player, "play", lambda: commands.append("play"))
    monkeypatch.setattr(pane.player, "pause", lambda: commands.append("pause"))

    for _ in range(10):
        pane._toggle_playback()  # pylint: disable=protected-access
        pane._toggle_playback()  # pylint: disable=protected-access

    assert commands == ["play", "pause"] * 10
    assert not pane._playback_requested  # pylint: disable=protected-access
    pane.shutdown()
    pane.close()


def test_preview_failure_does_not_replace_source_or_create_proxy_media(qt_app: QApplication, tmp_path: Path) -> None:
    """Native preview failure stops at the status message without a fallback source."""

    del qt_app
    source = tmp_path / "clip.mov"
    source.touch()
    pane = SourcePreviewPane()
    pane.set_sources((source,), 0)
    original_source = pane.player.source().toLocalFile()
    files_before = set(tmp_path.iterdir())

    pane._preview_error(QMediaPlayer.Error.ResourceError, "Unsupported preview media")  # pylint: disable=protected-access

    assert pane.player.source().toLocalFile() == original_source
    assert set(tmp_path.iterdir()) == files_before
    assert pane.preview_label.text() == "Preview unavailable; preflight can still inspect this clip."
    pane.shutdown()
    pane.close()


def test_source_preview_selection_does_not_change_processing_intent(qt_app: QApplication, tmp_path: Path) -> None:
    """Preview navigation changes selection only, never the ordered request inputs."""

    del qt_app
    queue = FakeQueue()
    bridge = QueueSnapshotBridge()
    model = JobListModel(queue, bridge)  # type: ignore[arg-type]
    window = MainWindow(model, ApplicationSettings())
    paths = (tmp_path / "first.mov", tmp_path / "second.mov", tmp_path / "third.mov")
    window.editor.output_directory.setText(str(tmp_path))
    window.editor.add_inputs(paths)
    window.editor.inputs.setCurrentRow(2)
    frozen = window.editor.create_job_request()

    window.source_preview.previous_button.click()

    assert window.editor.inputs.currentRow() == 1
    assert window.source_preview.player.source().toLocalFile() == str(paths[1])
    assert window.editor.input_paths() == paths
    assert window.editor.create_job_request().inputs == frozen.inputs
    window.source_preview._duration_changed(12_000)  # pylint: disable=protected-access
    window.source_preview._position_changed(4_000)  # pylint: disable=protected-access
    window.source_preview._preview_error(QMediaPlayer.Error.ResourceError, "Preview-only failure")  # pylint: disable=protected-access
    preview_affected_request = window.editor.create_job_request()
    assert preview_affected_request.inputs == frozen.inputs
    assert preview_affected_request.output_directory == frozen.output_directory
    assert preview_affected_request.target_height == frozen.target_height
    window.close()


def test_preview_audio_preferences_restore_and_persist_without_job_impact(qt_app: QApplication, tmp_path: Path) -> None:
    """Mute and volume persist atomically while remaining outside processing intent."""

    del qt_app
    store = SettingsStore(tmp_path / "settings.yaml")
    settings = ApplicationSettings(preview_muted=False, preview_volume=42)
    store.save(settings)
    queue = FakeQueue()
    bridge = QueueSnapshotBridge()
    model = JobListModel(queue, bridge)  # type: ignore[arg-type]
    window = MainWindow(model, settings, settings_store=store)

    assert not window.source_preview.audio.isMuted()
    assert window.source_preview.volume_slider.value() == 42
    window.editor.output_directory.setText(str(tmp_path))
    window.editor.add_inputs((tmp_path / "clip.mov",))
    frozen = window.editor.create_job_request()

    window.source_preview.volume_slider.setValue(37)
    window.source_preview.mute_toggle.setChecked(False)
    window.source_preview.mute_toggle.setChecked(True)

    saved = store.load()
    assert saved.preview_muted is True
    assert saved.preview_volume == 37
    assert frozen.inputs == (tmp_path / "clip.mov",)
    assert frozen.target_height == settings.target_height
    window.close()


def test_output_directory_preference_persists_when_draft_is_closed(qt_app: QApplication, tmp_path: Path) -> None:
    """A changed output directory survives closing without queuing a job."""

    del qt_app
    store = SettingsStore(tmp_path / "settings.yaml")
    window = MainWindow(JobListModel(FakeQueue(), QueueSnapshotBridge()), ApplicationSettings(), settings_store=store)
    selected = tmp_path / "exports"
    window.editor.output_directory.setText(str(selected))
    window.close()

    assert store.load().recent_output_directory == selected


def test_preview_pauses_when_processing_starts_without_automatic_resume(qt_app: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Processing start pauses preview once and completion never resumes it."""

    del qt_app
    queue = FakeQueue()
    bridge = QueueSnapshotBridge()
    model = JobListModel(queue, bridge)  # type: ignore[arg-type]
    window = MainWindow(model, ApplicationSettings())
    pause_calls: list[str] = []
    monkeypatch.setattr(window.source_preview, "pause_for_processing", lambda: pause_calls.append("paused"))

    window._handle_queue_snapshot(_snapshot(tmp_path, "preview-job", JobState.QUEUED, 0, revision=0))  # pylint: disable=protected-access
    window._handle_queue_snapshot(_snapshot(tmp_path, "preview-job", JobState.VALIDATING, None, revision=1))  # pylint: disable=protected-access
    window._handle_queue_snapshot(_snapshot(tmp_path, "preview-job", JobState.RUNNING, None, revision=2))  # pylint: disable=protected-access
    window._handle_queue_snapshot(_snapshot(tmp_path, "preview-job", JobState.RUNNING, None, revision=3))  # pylint: disable=protected-access
    window._handle_queue_snapshot(_snapshot(tmp_path, "preview-job", JobState.COMPLETED, None, revision=4))  # pylint: disable=protected-access

    assert pause_calls == ["paused"]
    assert window._preview_processing_job_id is None  # pylint: disable=protected-access
    window.close()


def test_runtime_loads_settings_and_owns_clean_queue_shutdown(qt_app: QApplication, tmp_path: Path) -> None:
    """Bootstrap composes real settings, queue, model, and window lifetimes."""

    store = SettingsStore(tmp_path / "settings.yaml")
    store.save(ApplicationSettings(target_height=1080))
    assert QCoreApplication.instance() is qt_app
    runtime = create_gui_runtime(runner=UnusedRunner(), settings_store=store)  # type: ignore[arg-type]

    assert runtime.settings.target_height == 1080
    assert runtime.model.rowCount(QModelIndex()) == 0
    assert runtime.window.findChild(QLabel, "titleLabel") is None
    assert runtime.window.findChild(QLabel, "subtitleLabel") is None
    runtime.window.close()
    runtime.shutdown()


def test_gui_sigint_bridge_closes_through_the_normal_window_lifecycle(qt_app: QApplication) -> None:
    """Terminal Ctrl+C closes the main window from Qt rather than interrupting it."""

    model = JobListModel(FakeQueue(), QueueSnapshotBridge())  # type: ignore[arg-type]
    window = MainWindow(model, ApplicationSettings())
    window.show()
    bridge = _GuiSigintBridge(qt_app, window)
    previous_handler = signal.getsignal(signal.SIGINT)
    bridge.install()
    try:
        os.kill(os.getpid(), signal.SIGINT)

        assert _process_until(qt_app, lambda: bridge._shutdown_started)  # pylint: disable=protected-access
        assert not window.isVisible()
        assert bridge._shutdown_started  # pylint: disable=protected-access
        os.kill(os.getpid(), signal.SIGINT)
        assert bridge._shutdown_requested  # pylint: disable=protected-access
    finally:
        bridge.uninstall()
        assert signal.getsignal(signal.SIGINT) == previous_handler
        window.close()


def test_single_instance_lock_rejects_second_owner(tmp_path: Path) -> None:
    """The application lock permits one owner and rejects a second owner."""

    first = QLockFile(str(tmp_path / "gui.lock"))
    second = QLockFile(str(tmp_path / "gui.lock"))
    assert first.tryLock(0)
    assert not second.tryLock(0)
    first.unlock()
    assert second.tryLock(0)
    second.unlock()
