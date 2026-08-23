"""Headless tests for Qt queue bridging, model roles, and the window shell."""

# Pytest injects fixtures through same-named function parameters.
# pylint: disable=redefined-outer-name

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QLockFile, QModelIndex, Qt  # noqa: E402  # pylint: disable=wrong-import-position,no-name-in-module
from PySide6.QtGui import QPalette  # noqa: E402  # pylint: disable=wrong-import-position,no-name-in-module
from PySide6.QtMultimedia import QMediaPlayer  # noqa: E402  # pylint: disable=wrong-import-position,no-name-in-module
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QSplitter  # noqa: E402  # pylint: disable=wrong-import-position,no-name-in-module

from ai_video_tools.core.models import JobRequest, JobState, PipelineStage, ProgressEvent  # noqa: E402  # pylint: disable=wrong-import-position
from ai_video_tools.gui.application import create_gui_runtime  # noqa: E402  # pylint: disable=wrong-import-position
from ai_video_tools.gui.jobs import JobListModel, JobRole, QueueSnapshotBridge  # noqa: E402  # pylint: disable=wrong-import-position
from ai_video_tools.gui.messages import MessageEvent, MessageHistory, MessageWidget  # noqa: E402  # pylint: disable=wrong-import-position
from ai_video_tools.gui.preview import VOLUME_ICON_COLOR, VOLUME_ICON_OPTICAL_OFFSET, SourcePreviewPane  # noqa: E402  # pylint: disable=wrong-import-position
from ai_video_tools.gui.theme import apply_dark_theme  # noqa: E402  # pylint: disable=wrong-import-position
from ai_video_tools.gui.window import MainWindow  # noqa: E402  # pylint: disable=wrong-import-position
from ai_video_tools.services.pipeline import PipelineCancelled  # noqa: E402  # pylint: disable=wrong-import-position
from ai_video_tools.services.queue import QueueJobOutcome, QueueJobSnapshot  # noqa: E402  # pylint: disable=wrong-import-position
from ai_video_tools.system.settings import ApplicationSettings, SettingsStore  # noqa: E402  # pylint: disable=wrong-import-position


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

    assert qt_app.style().objectName().lower() == "fusion"
    assert qt_app.palette().color(QPalette.ColorRole.Window).name() == "#202124"
    assert qt_app.palette().color(QPalette.ColorRole.Text).name() == "#f1f3f4"


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

    def run(self, *_args: object, **_kwargs: object) -> object:
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


def test_main_window_tracks_selection_progress_and_controls(qt_app: QApplication, tmp_path: Path) -> None:
    """The native shell renders measured progress and delegates user actions."""

    first = _snapshot(tmp_path, "first", JobState.RUNNING, None, revision=2, progress=ProgressEvent(PipelineStage.ENCODE, 3, 8, "Encoding output"))
    second = _snapshot(tmp_path, "second", JobState.QUEUED, 0, revision=0)
    queue = FakeQueue((first, second))
    bridge = QueueSnapshotBridge()
    model = JobListModel(queue, bridge)  # type: ignore[arg-type]
    window = MainWindow(model, ApplicationSettings(target_height=2160), tmp_path / "application.log")
    window.show()
    qt_app.processEvents()
    assert window.minimumWidth() == 1400
    assert window.minimumHeight() == 880
    assert window.job_list.height() == 240

    window.job_list.setCurrentIndex(model.index(0, 0))
    qt_app.processEvents()
    assert window.status_label.text() == "Encoding output"
    assert window.job_name_value.text() == "first.mov"
    assert window.job_state_value.text() == "Running"
    assert window.job_stage_value.text() == "encode"
    assert window.progress.maximum() == 8
    assert window.progress.value() == 3
    assert window.progress.format() == "Stage: 3/8"
    assert window.overall_progress.value() > 0
    assert window.overall_progress.format().startswith("Whole job:")
    assert window.cancel_button.isEnabled()
    assert "Cancel Job" in window.action_summary.text()
    window.cancel_button.click()
    assert queue.cancelled == ["first"]

    window.job_list.setCurrentIndex(model.index(1, 0))
    qt_app.processEvents()
    assert not window.move_up_button.isEnabled()
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
        window._queue_snapshot_changed(_snapshot(tmp_path, "upscale", JobState.RUNNING, None, revision=revision, progress=progress))  # pylint: disable=protected-access

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
    window.job_list.setCurrentIndex(model.index(0, 0))
    assert window.message_tabs.currentIndex() == 1
    window.message_tabs.setCurrentIndex(0)
    window._refresh_selection()  # pylint: disable=protected-access
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
    assert window.findChild(QSplitter, "mainContentSplitter") is not None
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
    assert "border: none" in window.job_creation_button.styleSheet()
    assert "#ff3b30" in window.job_creation_button.styleSheet()
    assert "QToolButton:checked" in window.job_creation_button.styleSheet()
    assert "background: transparent" in window.job_creation_button.styleSheet()
    assert window.queue_monitoring_button.minimumWidth() == 64
    assert window.queue_monitoring_button.minimumHeight() == 64
    left_gap = window.job_creation_button.geometry().left()
    right_gap = window.navigation_rail.width() - window.job_creation_button.geometry().right() - 1
    assert left_gap == 8
    assert right_gap == 9
    assert window.view_stack.geometry().left() - window.navigation_rail.geometry().right() - 1 == 0
    assert window.view_stack.geometry().left() - window.job_creation_button.geometry().right() - 1 == right_gap
    window.queue_monitoring_button.click()
    assert window.view_stack.currentIndex() == 1
    assert not window.job_creation_button.isChecked()
    window.job_creation_button.click()
    assert window.view_stack.currentIndex() == 0
    assert window.queue_monitoring_button.isEnabled()
    assert window.editor.findChild(QLabel, "sourceClipsLabel").text() == "Source Clips"
    assert window.source_preview.preview_label.text() == "Preview"
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
    assert audio_controls.itemAt(0).widget() is window.source_preview.volume_row
    volume_controls = window.source_preview.volume_row.layout()
    assert [volume_controls.itemAt(index).widget() for index in range(4)] == [window.source_preview.volume_label, window.source_preview.minimum_volume_icon, window.source_preview.volume_slider, window.source_preview.maximum_volume_icon]
    volume_widgets = [window.source_preview.volume_label, window.source_preview.minimum_volume_icon, window.source_preview.volume_slider, window.source_preview.maximum_volume_icon]
    assert len({widget.geometry().center().y() for widget in volume_widgets}) == 1
    assert window.source_preview.volume_row.height() == 24
    assert {widget.height() for widget in volume_widgets} == {24}
    mute_controls = audio_controls.itemAt(1).layout()
    assert mute_controls.itemAt(0).spacerItem() is not None
    mute_group = mute_controls.itemAt(1).layout()
    assert [mute_group.itemAt(index).widget() for index in range(2)] == [window.source_preview.mute_toggle, window.source_preview.mute_label]
    window.editor.add_inputs((tmp_path / "first.mov",))
    assert window.findChild(QLabel, "sourcePreviewSource") is None
    assert window.source_preview.minimumWidth() == 600
    assert window.editor.inputs.width() <= 673
    window.source_preview.preview_error.emit("Preview unavailable; preflight can still inspect this clip.")
    assert "Preview unavailable; preflight can still inspect this clip." in window.global_messages.toPlainText()
    assert window.source_preview.heightForWidth(300) == 400
    assert window.source_preview.play_pause_button.isEnabled()
    assert window.source_preview.previous_button.text() == "⏪"
    assert window.source_preview.next_button.text() == "⏩"
    assert window.source_preview.play_pause_button.text() == "▶"
    controls = window.source_preview.layout().itemAt(3).layout()
    assert controls.itemAt(0).layout() is not None
    assert [controls.itemAt(0).layout().itemAt(index).widget() for index in range(3)] == [window.source_preview.play_pause_button, window.source_preview.first_frame_button, window.source_preview.last_frame_button]
    assert controls.itemAt(1).spacerItem() is not None
    assert controls.itemAt(2).layout() is not None
    assert [controls.itemAt(2).layout().itemAt(index).widget() for index in range(2)] == [window.source_preview.previous_button, window.source_preview.next_button]
    for button in (window.source_preview.play_pause_button, window.source_preview.first_frame_button, window.source_preview.last_frame_button, window.source_preview.previous_button, window.source_preview.next_button):
        assert button.size().width() == 32
        assert button.size().height() == 32
        assert button.font().pointSizeF() == pytest.approx(QApplication.font().pointSizeF() * 2)
        assert button.toolTip() == button.accessibleName()
        assert "background: transparent" in button.styleSheet()
        assert "border: none" in button.styleSheet()
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
    window.close()


def test_source_preview_resize_preserves_pane_ratio_and_native_aspect_mode(qt_app: QApplication) -> None:
    """The preview pane follows 3:4 geometry without changing native video aspect handling."""

    pane = SourcePreviewPane()
    pane.setMinimumWidth(0)
    pane.resize(300, pane.heightForWidth(300))
    pane.show()
    qt_app.processEvents()

    assert pane.hasHeightForWidth()
    assert pane.width() == 300
    assert pane.height() == 400
    assert pane.video.aspectRatioMode() == Qt.AspectRatioMode.KeepAspectRatio
    assert not pane.progress_slider.isEnabled()

    pane.resize(450, pane.heightForWidth(450))
    qt_app.processEvents()
    assert pane.width() == 450
    assert pane.height() == 600
    pane.shutdown()
    assert pane.player.videoOutput() is None
    assert pane.player.audioOutput() is None
    pane.close()


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
    frozen = window.editor.build_request()

    window.source_preview.previous_button.click()

    assert window.editor.inputs.currentRow() == 1
    assert window.source_preview.player.source().toLocalFile() == str(paths[1])
    assert window.editor.input_paths() == paths
    assert window.editor.build_request().inputs == frozen.inputs
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
    frozen = window.editor.build_request()

    window.source_preview.volume_slider.setValue(37)
    window.source_preview.mute_toggle.setChecked(False)
    window.source_preview.mute_toggle.setChecked(True)

    saved = store.load()
    assert saved.preview_muted is True
    assert saved.preview_volume == 37
    assert frozen.inputs == (tmp_path / "clip.mov",)
    assert frozen.target_height == settings.target_height
    window.close()


def test_preview_pauses_when_processing_starts_without_automatic_resume(qt_app: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Processing start pauses preview once and completion never resumes it."""

    del qt_app
    queue = FakeQueue()
    bridge = QueueSnapshotBridge()
    model = JobListModel(queue, bridge)  # type: ignore[arg-type]
    window = MainWindow(model, ApplicationSettings())
    pause_calls: list[str] = []
    monkeypatch.setattr(window.source_preview, "pause_for_processing", lambda: pause_calls.append("paused"))

    window._queue_snapshot_changed(_snapshot(tmp_path, "preview-job", JobState.QUEUED, 0, revision=0))  # pylint: disable=protected-access
    window._queue_snapshot_changed(_snapshot(tmp_path, "preview-job", JobState.VALIDATING, None, revision=1))  # pylint: disable=protected-access
    window._queue_snapshot_changed(_snapshot(tmp_path, "preview-job", JobState.RUNNING, None, revision=2))  # pylint: disable=protected-access
    window._queue_snapshot_changed(_snapshot(tmp_path, "preview-job", JobState.RUNNING, None, revision=3))  # pylint: disable=protected-access
    window._queue_snapshot_changed(_snapshot(tmp_path, "preview-job", JobState.COMPLETED, None, revision=4))  # pylint: disable=protected-access

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


def test_single_instance_lock_rejects_second_owner(tmp_path: Path) -> None:
    """The application lock permits one owner and rejects a second owner."""

    first = QLockFile(str(tmp_path / "gui.lock"))
    second = QLockFile(str(tmp_path / "gui.lock"))
    assert first.tryLock(0)
    assert not second.tryLock(0)
    first.unlock()
    assert second.tryLock(0)
    second.unlock()
