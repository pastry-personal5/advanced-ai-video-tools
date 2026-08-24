"""Headless tests for validated external-tool preference editing."""

# Pytest injects fixtures through same-named function parameters.
# pylint: disable=redefined-outer-name

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QThread  # noqa: E402  # pylint: disable=wrong-import-position,no-name-in-module
from PySide6.QtWidgets import QApplication, QDialog, QPushButton  # noqa: E402  # pylint: disable=wrong-import-position,no-name-in-module

from advanced_ai_video_tools.core.models import ToolInfo, ToolOverrides, Toolchain  # noqa: E402  # pylint: disable=wrong-import-position
from advanced_ai_video_tools.gui.tool_settings import ToolSettingsDialog, ToolSettingsValidator  # noqa: E402  # pylint: disable=wrong-import-position
from advanced_ai_video_tools.system.settings import ApplicationSettings, SettingsStore  # noqa: E402  # pylint: disable=wrong-import-position
from advanced_ai_video_tools.system.tools import ToolDiscoveryError  # noqa: E402  # pylint: disable=wrong-import-position


@pytest.fixture(scope="module")
def qt_app() -> QApplication:
    """Provide one offscreen application for settings widgets and threads."""

    existing = QCoreApplication.instance()
    if existing is not None and not isinstance(existing, QApplication):
        raise RuntimeError("a non-GUI Qt application already exists")
    return existing or QApplication(["ai-video-tools-settings-tests"])


def _process_until(qt_app: QApplication, predicate: Callable[[], bool], timeout: float = 1.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qt_app.processEvents()
        if predicate():
            return True
        time.sleep(0.001)
    qt_app.processEvents()
    return predicate()


def _toolchain(tmp_path: Path) -> Toolchain:
    return Toolchain(ToolInfo(tmp_path / "ffmpeg", "ffmpeg test"), ToolInfo(tmp_path / "ffprobe", "ffprobe test"), ToolInfo(tmp_path / "realesrgan", "realesrgan test"), tmp_path / "models")


class RecordingDiscovery:
    """Return a typed toolchain while capturing thread and override facts."""

    def __init__(self, result: Toolchain | Exception) -> None:
        self.result = result
        self.calls: list[ToolOverrides] = []
        self.thread_identifier: int | None = None

    def discover(self, overrides: ToolOverrides) -> Toolchain:
        """Record one validation and return or raise its configured outcome."""

        self.thread_identifier = threading.get_ident()
        self.calls.append(overrides)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_validator_runs_discovery_off_gui_thread_and_returns_on_gui_thread(qt_app: QApplication, tmp_path: Path) -> None:
    """Executable launch and Vulkan checks cannot stall Qt presentation."""

    discovery = RecordingDiscovery(_toolchain(tmp_path))
    validator = ToolSettingsValidator(discovery)  # type: ignore[arg-type]
    results: list[tuple[ToolOverrides, Toolchain]] = []
    callback_threads: list[QThread] = []

    def record(overrides: object, toolchain: object) -> None:
        assert isinstance(overrides, ToolOverrides)
        assert isinstance(toolchain, Toolchain)
        results.append((overrides, toolchain))
        callback_threads.append(QThread.currentThread())

    validator.succeeded.connect(record)
    requested = ToolOverrides(ffmpeg=tmp_path / "custom-ffmpeg")
    assert validator.start(requested)
    assert not validator.start(ToolOverrides())

    assert _process_until(qt_app, lambda: bool(results) and not validator.busy)
    assert discovery.calls == [requested]
    assert discovery.thread_identifier is not None and discovery.thread_identifier != threading.get_ident()
    assert callback_threads == [qt_app.thread()]
    validator.shutdown()


def test_dialog_resets_overrides_and_persists_only_after_success(qt_app: QApplication, tmp_path: Path) -> None:
    """Blank fields mean discovery defaults, and validated values replace settings atomically."""

    old_tools = ToolOverrides(tmp_path / "old-ffmpeg", tmp_path / "old-ffprobe", tmp_path / "old-realesrgan", tmp_path / "old-models")
    store = SettingsStore(tmp_path / "settings.yaml")
    store.save(ApplicationSettings(tools=old_tools, target_height=1080))
    discovery = RecordingDiscovery(_toolchain(tmp_path))
    validator = ToolSettingsValidator(discovery)  # type: ignore[arg-type]
    dialog = ToolSettingsDialog(store.load(), validator, store)
    saved: list[ApplicationSettings] = []
    dialog.settings_saved.connect(saved.append)

    for name in ("usePathFfmpegButton", "usePathFfprobeButton", "usePathRealesrganButton", "automaticModelDirectoryButton"):
        button = dialog.findChild(QPushButton, name)
        assert button is not None
        button.click()
    assert dialog.overrides() == ToolOverrides()
    dialog.save_button.click()

    assert _process_until(qt_app, lambda: dialog.result() == int(QDialog.DialogCode.Accepted) and not validator.busy)
    assert discovery.calls == [ToolOverrides()]
    assert len(saved) == 1 and saved[0].tools == ToolOverrides()
    assert store.load().tools == ToolOverrides()
    assert store.load().target_height == 1080
    assert "Resolved tools:" in dialog.status.text()
    validator.shutdown()


def test_failed_validation_keeps_previous_settings_and_dialog_open(qt_app: QApplication, tmp_path: Path) -> None:
    """A bad executable or backend never becomes a persisted future-job default."""

    old_tools = ToolOverrides(ffmpeg=tmp_path / "known-ffmpeg")
    store = SettingsStore(tmp_path / "settings.yaml")
    store.save(ApplicationSettings(tools=old_tools))
    discovery = RecordingDiscovery(ToolDiscoveryError("Real-ESRGAN Vulkan smoke test failed: no device"))
    validator = ToolSettingsValidator(discovery)  # type: ignore[arg-type]
    dialog = ToolSettingsDialog(store.load(), validator, store)
    dialog.ffmpeg.setText(str(tmp_path / "broken-ffmpeg"))
    dialog.save_button.click()

    assert _process_until(qt_app, lambda: "Validation failed" in dialog.status.text() and not validator.busy)
    assert dialog.result() != int(QDialog.DialogCode.Accepted)
    assert store.load().tools == old_tools
    assert dialog.ffmpeg.isEnabled()
    dialog.reject()
    validator.shutdown()
