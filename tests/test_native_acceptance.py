"""Opt-in native macOS presentation acceptance tests.

These checks deliberately live outside the default suite: they require an
interactive macOS desktop, Apple Silicon Metal support, and Screen Recording
permission for the invoking terminal or test runner.
"""

# Pytest injects fixtures through same-named function parameters.
# pylint: disable=redefined-outer-name

from __future__ import annotations

import os
import shutil
import statistics
import subprocess
import time
from pathlib import Path

import pytest

from PySide6.QtCore import QCoreApplication  # pylint: disable=no-name-in-module
from PySide6.QtGui import QImage  # pylint: disable=no-name-in-module
from PySide6.QtWidgets import QApplication  # pylint: disable=no-name-in-module

from advanced_ai_video_tools.gui.jobs import JobListModel, QueueSnapshotBridge
from advanced_ai_video_tools.gui.theme import apply_dark_theme
from advanced_ai_video_tools.gui.window import MainWindow
from advanced_ai_video_tools.system.hardware import apple_silicon_metal_error
from advanced_ai_video_tools.system.settings import ApplicationSettings

_ENABLE_NATIVE_TESTS = "ADVANCED_AI_VIDEO_TOOLS_RUN_NATIVE_ACCEPTANCE"


class _EmptyQueue:
    """The minimal queue contract needed to display an empty native window."""

    def snapshots(self) -> tuple[object, ...]:
        """Return an empty initial queue snapshot."""

        return ()

    def cancel(self, _job_id: str) -> bool:
        """Reject cancellation because the acceptance shell has no jobs."""

        return False

    def move(self, _job_id: str, _position: int) -> None:
        """Ignore reordering because the acceptance shell has no jobs."""

    def wait(self, _job_id: str, timeout: float | None = None) -> None:
        """Return no terminal outcome because the acceptance shell has no jobs."""

        del timeout


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
    apply_dark_theme(application)
    return application


def _visible_window(application: QApplication) -> tuple[MainWindow, float]:
    """Show an empty shell and return after its native surface is exposed."""

    model = JobListModel(_EmptyQueue(), QueueSnapshotBridge())  # type: ignore[arg-type]
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
    """Record three Metal-gated native presentation samples against the 3 s budget."""

    samples: list[float] = []
    for _ in range(3):
        window, elapsed = _visible_window(native_qt_app)
        samples.append(elapsed)
        window.close()
        native_qt_app.processEvents()
    median = statistics.median(samples)
    p95 = statistics.quantiles(samples, n=100, method="inclusive")[94]
    record_property("native_window_presentation_median_seconds", f"{median:.3f}")
    record_property("native_window_presentation_p95_seconds", f"{p95:.3f}")
    assert p95 <= 3.0, f"native window presentation p95 was {p95:.3f}s (budget: 3.000s; samples: {samples!r})"


@pytest.mark.gui_capture
def test_screencapture_contains_visible_native_window(native_qt_app: QApplication, tmp_path: Path) -> None:
    """Prove macOS can capture the exposed dark shell from the current desktop."""

    if shutil.which("screencapture") is None:
        pytest.skip("macOS screencapture is unavailable")
    window, _elapsed = _visible_window(native_qt_app)
    image_path = tmp_path / "advanced-ai-video-tools-native.png"
    try:
        result = subprocess.run(["screencapture", "-x", str(image_path)], check=False, capture_output=True, text=True, timeout=15.0, shell=False)
        assert result.returncode == 0, result.stderr.strip() or result.stdout.strip() or "screencapture failed"
        assert image_path.is_file() and image_path.stat().st_size > 1024
        image = QImage(str(image_path))
        assert not image.isNull()
        screen = window.screen()
        assert screen is not None
        screen_geometry = screen.geometry()
        scale = image.width() / screen_geometry.width()
        frame = window.frameGeometry()
        start_x = int((frame.x() - screen_geometry.x()) * scale)
        start_y = int((frame.y() - screen_geometry.y()) * scale)
        end_x = min(image.width(), int((frame.right() - screen_geometry.x()) * scale))
        end_y = min(image.height(), int((frame.bottom() - screen_geometry.y()) * scale))
        dark_surface_found = any(image.pixelColor(x, y).name().lower() == "#202124" for y in range(max(start_y, 0), max(end_y, 0), max(int(20 * scale), 1)) for x in range(max(start_x, 0), max(end_x, 0), max(int(20 * scale), 1)))
        assert dark_surface_found, "the screen capture did not contain the visible Advanced AI Video Tools dark surface"
    finally:
        window.close()
        native_qt_app.processEvents()
