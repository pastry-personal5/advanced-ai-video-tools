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

from PySide6.QtCore import QCoreApplication, QModelIndex, Qt  # noqa: E402  # pylint: disable=wrong-import-position,no-name-in-module
from PySide6.QtMultimedia import QMediaPlayer  # noqa: E402  # pylint: disable=wrong-import-position,no-name-in-module
from PySide6.QtWidgets import QApplication, QLabel, QSplitter  # noqa: E402  # pylint: disable=wrong-import-position,no-name-in-module

from ai_video_tools.core.models import JobRequest, JobState, PipelineStage, ProgressEvent  # noqa: E402  # pylint: disable=wrong-import-position
from ai_video_tools.gui.application import create_gui_runtime  # noqa: E402  # pylint: disable=wrong-import-position
from ai_video_tools.gui.jobs import JobListModel, JobRole, QueueSnapshotBridge  # noqa: E402  # pylint: disable=wrong-import-position
from ai_video_tools.gui.messages import MessageEvent, MessageHistory, MessageWidget  # noqa: E402  # pylint: disable=wrong-import-position
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
    assert window.minimumWidth() == 1536
    assert window.minimumHeight() == 1024

    window.job_list.setCurrentIndex(model.index(0, 0))
    qt_app.processEvents()
    assert window.status_label.text() == "Encoding output"
    assert window.progress.maximum() == 8
    assert window.progress.value() == 3
    assert window.cancel_button.isEnabled()
    window.cancel_button.click()
    assert queue.cancelled == ["first"]

    window.job_list.setCurrentIndex(model.index(1, 0))
    qt_app.processEvents()
    assert not window.move_up_button.isEnabled()
    window.close()


def test_message_history_keeps_five_timestamped_lines_and_job_selection(qt_app: QApplication) -> None:
    """Message presentation is session-only, bounded, and selection-driven."""

    del qt_app
    history = MessageHistory(clock=lambda: datetime(2026, 8, 22, 12, 34, 56))
    widget = MessageWidget(history)
    for number in range(6):
        widget.append(MessageEvent(f"Global {number}"))
    for number in range(6):
        widget.append(MessageEvent(f"Job {number}", "job-1"))
    assert widget.global_messages.toPlainText().splitlines() == [
        "[2026-08-22 12:34:56] Global 1",
        "[2026-08-22 12:34:56] Global 2",
        "[2026-08-22 12:34:56] Global 3",
        "[2026-08-22 12:34:56] Global 4",
        "[2026-08-22 12:34:56] Global 5",
    ]
    widget.select_job("job-1")
    assert widget.tabs.currentIndex() == 1
    assert widget.job_messages.toPlainText().splitlines()[-1].endswith("Job 5")
    widget.select_job(None)
    assert widget.job_messages.toPlainText() == "No job is selected."
    assert widget.global_messages.isReadOnly()


def test_main_window_message_area_is_splitter_resizable_and_logs_completion(qt_app: QApplication, tmp_path: Path) -> None:
    """The integrated panel stays in the window and consumes queue snapshots."""

    del qt_app
    queue = FakeQueue()
    bridge = QueueSnapshotBridge()
    model = JobListModel(queue, bridge)  # type: ignore[arg-type]
    window = MainWindow(model, ApplicationSettings(target_height=2160))
    assert window.findChild(QSplitter, "mainContentSplitter") is not None
    assert [window.message_tabs.tabText(index) for index in range(2)] == ["Global Messages", "Job Messages"]
    assert "Application started." in window.global_messages.toPlainText()
    assert "Add clips in order they should be concatenated." in window.global_messages.toPlainText()
    assert window.message_tabs.currentIndex() == 0
    assert window.view_stack.currentIndex() == 0
    window.queue_monitoring_button.click()
    assert window.view_stack.currentIndex() == 1
    assert not window.job_creation_button.isChecked()
    window.job_creation_button.click()
    assert window.view_stack.currentIndex() == 0
    assert window.queue_monitoring_button.isEnabled()
    window.editor.add_inputs((tmp_path / "first.mov",))
    assert window.findChild(QLabel, "sourcePreviewSource") is None
    assert window.findChild(QLabel, "sourcePreviewDisclaimer") is None
    assert window.source_preview.minimumWidth() == 600
    window.source_preview.preview_error.emit("Preview unavailable; preflight can still inspect this clip.")
    assert "Preview unavailable; preflight can still inspect this clip." in window.global_messages.toPlainText()
    assert window.source_preview.heightForWidth(300) == 400
    assert window.source_preview.play_pause_button.isEnabled()
    assert window.source_preview.previous_button.text() == "⏪"
    assert window.source_preview.next_button.text() == "⏩"
    assert window.source_preview.play_pause_button.text() == "▶"
    assert window.source_preview.audio.isMuted()
    assert window.source_preview.video.aspectRatioMode() == Qt.AspectRatioMode.KeepAspectRatio
    assert window.source_preview.video.sizePolicy().verticalPolicy().name == "Expanding"
    window.source_preview._media_status_changed(QMediaPlayer.MediaStatus.EndOfMedia)  # pylint: disable=protected-access
    assert not window.source_preview.previous_button.isEnabled()
    window.editor.add_inputs((tmp_path / "second.mov",))
    assert window.editor.inputs.currentRow() == 1
    assert window.source_preview.player.source().toLocalFile() == str(tmp_path / "second.mov")
    window.source_preview.previous_button.click()
    assert window.editor.inputs.currentRow() == 0
    window.close()


def test_runtime_loads_settings_and_owns_clean_queue_shutdown(qt_app: QApplication, tmp_path: Path) -> None:
    """Bootstrap composes real settings, queue, model, and window lifetimes."""

    store = SettingsStore(tmp_path / "settings.json")
    store.save(ApplicationSettings(target_height=1080))
    assert QCoreApplication.instance() is qt_app
    runtime = create_gui_runtime(runner=UnusedRunner(), settings_store=store)  # type: ignore[arg-type]

    assert runtime.settings.target_height == 1080
    assert runtime.model.rowCount(QModelIndex()) == 0
    assert runtime.window.findChild(QLabel, "titleLabel") is None
    assert runtime.window.findChild(QLabel, "subtitleLabel") is None
    runtime.window.close()
    runtime.shutdown()
