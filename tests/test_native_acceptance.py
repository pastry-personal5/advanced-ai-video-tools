"""Opt-in native macOS presentation acceptance tests.

These checks deliberately live outside the default suite: they require an
interactive macOS desktop, Apple Silicon Metal support, and Screen Recording
permission for the invoking terminal or test runner.
"""

# Pytest injects fixtures through same-named function parameters.
# pylint: disable=redefined-outer-name

from __future__ import annotations

import os
import platform
import statistics
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from PySide6.QtCore import QCoreApplication, Qt  # pylint: disable=no-name-in-module
from PySide6.QtCore import qVersion  # pylint: disable=no-name-in-module
from PySide6.QtGui import QGuiApplication, QImage  # pylint: disable=no-name-in-module
from PySide6.QtWidgets import QApplication  # pylint: disable=no-name-in-module

from advanced_ai_video_tools.core.models import JobRequest, JobState
from advanced_ai_video_tools.gui.jobs import JobListModel, JobQueueView, QueueSnapshotBridge
from advanced_ai_video_tools.services.queue import QueueJobOutcome, QueueJobSnapshot
from advanced_ai_video_tools.gui.theme import apply_dark_theme
from advanced_ai_video_tools.gui.window import MainWindow
from advanced_ai_video_tools.system.hardware import apple_silicon_metal_error
from advanced_ai_video_tools.system.settings import ApplicationSettings

_ENABLE_NATIVE_TESTS = "ADVANCED_AI_VIDEO_TOOLS_RUN_NATIVE_ACCEPTANCE"


class _EmptyQueue:
    """The minimal queue contract needed to display an empty native window."""

    def snapshots(self) -> tuple[QueueJobSnapshot, ...]:
        """Return an empty initial queue snapshot."""

        return ()

    def cancel(self, _job_id: str) -> bool:
        """Reject cancellation because the acceptance shell has no jobs."""

        return False

    def move(self, _job_id: str, _position: int) -> None:
        """Ignore reordering because the acceptance shell has no jobs."""

    def wait(self, _job_id: str, timeout: float | None = None) -> QueueJobOutcome | None:
        """Return no terminal outcome because the acceptance shell has no jobs."""

        del timeout


class _PopulatedQueue(_EmptyQueue):
    """Representative queue records for native Queue Monitoring checks."""

    def __init__(self, root: Path) -> None:
        created = datetime(2026, 9, 1, tzinfo=timezone.utc)

        def snapshot(job_id: str, state: JobState, position: int | None) -> QueueJobSnapshot:
            request = JobRequest((root / f"{job_id}-source-with-a-long-name.mov",), root, explicit_output_path=root / f"{job_id}.mp4", created_at=created)
            return QueueJobSnapshot(job_id, request, state, position, None, 1)

        self._records = (
            snapshot("active", JobState.RUNNING, None),
            snapshot("queued", JobState.QUEUED, 0),
            snapshot("history", JobState.FAILED, None),
        )

    def snapshots(self) -> tuple[QueueJobSnapshot, ...]:
        """Return active, pending, and terminal records."""

        return self._records


def _require_native_metal() -> None:
    """Skip unless the caller explicitly requested a capable native desktop."""

    if os.environ.get(_ENABLE_NATIVE_TESTS) != "1":
        pytest.skip(f"set {_ENABLE_NATIVE_TESTS}=1 to run native acceptance tests")
    error = apple_silicon_metal_error()
    if error is not None:
        pytest.skip(error)


@pytest.fixture(scope="module")
def native_qt_app() -> QApplication:
    """Provide the real themed Cocoa application without offscreen fallback."""

    _require_native_metal()
    if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        pytest.skip("native acceptance requires QT_QPA_PLATFORM=cocoa")
    existing = QCoreApplication.instance()
    if existing is not None and not isinstance(existing, QApplication):
        raise RuntimeError("a non-GUI Qt application already exists")
    application = existing or QApplication(["advanced-ai-video-tools-native-acceptance"])
    deadline = time.monotonic() + 5.0
    while not QGuiApplication.screens() and time.monotonic() < deadline:
        application.processEvents()
        time.sleep(0.05)
    if not QGuiApplication.screens():
        pytest.fail("native acceptance was requested, but no active macOS display became available within 5 seconds")
    apply_dark_theme(application)
    return application


def _visible_window(application: QApplication, queue: JobQueueView | None = None) -> tuple[MainWindow, float]:
    """Show an empty shell and return after its native surface is exposed."""

    model = JobListModel(queue or _EmptyQueue(), QueueSnapshotBridge())
    window = MainWindow(model, ApplicationSettings())
    window.setGeometry(40, 40, 1400, 880)
    started = time.monotonic()
    window.show()
    window.raise_()
    window.activateWindow()
    deadline = started + 3.0
    while time.monotonic() < deadline:
        application.processEvents()
        handle = window.windowHandle()
        if window.isVisible() and handle is not None and handle.isExposed():
            return window, time.monotonic() - started
        time.sleep(0.01)
    window.close()
    raise AssertionError("the native main window did not become exposed within 3 seconds")


@pytest.mark.performance
def test_native_window_presentation_meets_warm_start_budget(native_qt_app: QApplication, record_property: pytest.RecordProperty) -> None:
    """Record repeatable native presentation samples against the 3 s budget."""

    samples: list[float] = []
    warmup_window, _warmup_elapsed = _visible_window(native_qt_app)
    warmup_window.close()
    native_qt_app.processEvents()
    for _ in range(2):
        warmup_window, _warmup_elapsed = _visible_window(native_qt_app)
        warmup_window.close()
        native_qt_app.processEvents()
    for _ in range(15):
        window, elapsed = _visible_window(native_qt_app)
        samples.append(elapsed)
        window.close()
        native_qt_app.processEvents()
    median = statistics.median(samples)
    p95 = statistics.quantiles(samples, n=100, method="inclusive")[94]
    record_property("host_os", platform.platform())
    record_property("host_architecture", platform.machine())
    record_property("python_version", platform.python_version())
    record_property("qt_version", qVersion())
    record_property("measurement_kind", "warm repeated window presentation")
    record_property("native_window_presentation_samples_seconds", ",".join(f"{sample:.3f}" for sample in samples))
    record_property("native_window_presentation_median_seconds", f"{median:.3f}")
    record_property("native_window_presentation_p95_seconds", f"{p95:.3f}")
    assert p95 <= 3.0, f"native window presentation p95 was {p95:.3f}s (budget: 3.000s; samples: {samples!r})"


@pytest.mark.gui_capture
def test_screencapture_contains_visible_native_window(native_qt_app: QApplication, tmp_path: Path) -> None:
    """Prove macOS can capture the exposed dark shell from the current desktop."""

    window, _elapsed = _visible_window(native_qt_app)
    image_path = tmp_path / "advanced-ai-video-tools-native.png"
    try:
        frame = window.frameGeometry()
        result = subprocess.run(
            ["/usr/sbin/screencapture", "-x", "-R", f"{frame.x()},{frame.y()},{frame.width()},{frame.height()}", str(image_path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=15.0,
            shell=False,
        )
        assert result.returncode == 0, result.stderr.strip() or result.stdout.strip() or "screencapture failed"
        assert image_path.is_file() and image_path.stat().st_size > 1024
        image = QImage(str(image_path))
        assert not image.isNull()
        dark_surface_found = any(image.pixelColor(x, y).name().lower() == "#202124" for y in range(0, image.height(), 20) for x in range(0, image.width(), 20))
        assert dark_surface_found, "the screen capture did not contain the visible Advanced AI Video Tools dark surface"
    finally:
        window.close()
        native_qt_app.processEvents()


@pytest.mark.gui_capture
def test_populated_queue_monitoring_native_layout(native_qt_app: QApplication, tmp_path: Path) -> None:
    """Capture and verify the populated Active, Up Next, and History workspace."""

    window, _elapsed = _visible_window(native_qt_app, _PopulatedQueue(tmp_path))
    try:
        window.queue_monitoring_button.click()
        native_qt_app.processEvents()
        assert all(window.region_proxies[region].rowCount() == 1 for region in ("active", "up_next", "history"))
        assert all(view.horizontalHeader().sectionResizeMode(0).name == "Fixed" for view in window.region_views.values())
        assert all(view.horizontalHeader().sectionResizeMode(1).name == "Fixed" for view in window.region_views.values())
        assert all(view.horizontalHeader().sectionResizeMode(2).name == "Fixed" for view in window.region_views.values())
        assert all(view.horizontalHeader().defaultAlignment() == Qt.AlignmentFlag.AlignCenter for view in window.region_views.values())
        image_path = tmp_path / "advanced-ai-video-tools-queue-monitoring.png"
        frame = window.frameGeometry()
        result = subprocess.run(
            ["/usr/sbin/screencapture", "-x", "-R", f"{frame.x()},{frame.y()},{frame.width()},{frame.height()}", str(image_path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=15.0,
            shell=False,
        )
        assert result.returncode == 0, result.stderr.strip() or result.stdout.strip() or "screencapture failed"
        assert image_path.is_file() and image_path.stat().st_size > 1024
    finally:
        window.close()
        native_qt_app.processEvents()
