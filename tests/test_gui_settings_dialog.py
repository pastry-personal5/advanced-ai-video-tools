"""Headless tests for the unified, validated Settings dialog."""

# Pytest injects fixtures through same-named function parameters.
# pylint: disable=missing-function-docstring,redefined-outer-name,use-implicit-booleaness-not-comparison

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QSize, Qt, QThread  # noqa: E402  # pylint: disable=wrong-import-position,no-name-in-module
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QScrollArea, QSplitter  # noqa: E402  # pylint: disable=wrong-import-position,no-name-in-module

from advanced_ai_video_tools.core.models import ToolInfo, ToolOverrides, Toolchain  # noqa: E402  # pylint: disable=wrong-import-position
from advanced_ai_video_tools.gui.settings_dialog import DeletionRuleDialog, ExternalToolsPage, ExternalToolsValidator, FileSettingsPage, SettingsDialog, SettingsDialogSessionState, SettingsValidationState  # noqa: E402  # pylint: disable=wrong-import-position
from advanced_ai_video_tools.system.settings import ApplicationSettings, DeletionRule, SettingsError, SettingsStore  # noqa: E402  # pylint: disable=wrong-import-position
from advanced_ai_video_tools.system.tools import ToolDiscoveryError  # noqa: E402  # pylint: disable=wrong-import-position


@pytest.fixture(scope="module")
def qt_app() -> QApplication:
    """Provide one offscreen application for settings widgets and threads."""

    existing = QCoreApplication.instance()
    if existing is not None and not isinstance(existing, QApplication):
        raise RuntimeError("a non-GUI Qt application already exists")
    return existing or QApplication(["advanced-ai-video-tools-settings-tests"])


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
        self.thread_identifier = threading.get_ident()
        self.calls.append(overrides)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class BlockingDiscovery(RecordingDiscovery):
    """Hold validation until a test releases the bounded worker."""

    def __init__(self, result: Toolchain) -> None:
        super().__init__(result)
        self.started = threading.Event()
        self.release = threading.Event()

    def discover(self, overrides: ToolOverrides) -> Toolchain:
        self.started.set()
        if not self.release.wait(1.0):
            raise ToolDiscoveryError("test validation timed out")
        return super().discover(overrides)


class InvalidResultDiscovery:
    """Return a malformed success payload from the worker boundary."""

    def __init__(self, result: object) -> None:
        self.result = result

    def discover(self, overrides: ToolOverrides) -> object:
        del overrides
        return self.result


class RecordingStore:
    """Capture atomic-save requests or raise a configured storage failure."""

    def __init__(self, error: SettingsError | None = None) -> None:
        self.error = error
        self.saved: list[ApplicationSettings] = []

    def save(self, settings: ApplicationSettings) -> None:
        if self.error is not None:
            raise self.error
        self.saved.append(settings)


def _dialog(settings: ApplicationSettings, validator: ExternalToolsValidator, store: object, state: SettingsDialogSessionState | None = None) -> SettingsDialog:
    return SettingsDialog(settings, validator, store, state)  # type: ignore[arg-type]


def test_validator_runs_discovery_off_gui_thread_and_returns_on_gui_thread(qt_app: QApplication, tmp_path: Path) -> None:
    discovery = RecordingDiscovery(_toolchain(tmp_path))
    validator = ExternalToolsValidator(discovery)  # type: ignore[arg-type]
    results: list[tuple[ToolOverrides, Toolchain]] = []
    callback_threads: list[QThread] = []

    def record(overrides: object, toolchain: object) -> None:
        assert isinstance(overrides, ToolOverrides)
        assert isinstance(toolchain, Toolchain)
        results.append((overrides, toolchain))
        callback_threads.append(QThread.currentThread())

    validator.succeeded.connect(record)
    requested = ToolOverrides(ffmpeg=tmp_path / "custom-ffmpeg")
    assert validator.begin_validation(requested)
    assert not validator.begin_validation(ToolOverrides())

    assert _process_until(qt_app, lambda: bool(results) and not validator.busy)
    assert discovery.calls == [requested]
    assert discovery.thread_identifier is not None and discovery.thread_identifier != threading.get_ident()
    assert callback_threads == [qt_app.thread()]
    validator.shutdown()


def test_dialog_has_exact_navigation_pages_dimensions_and_noncollapsible_sidebar(qt_app: QApplication, tmp_path: Path) -> None:
    validator = ExternalToolsValidator(RecordingDiscovery(_toolchain(tmp_path)))  # type: ignore[arg-type]
    long_rule = DeletionRule("source-" + ("x" * 100) + "*.mov", ("{source_stem}-" + ("y" * 100) + ".png",))
    dialog = _dialog(ApplicationSettings(deletion_rules=(long_rule,)), validator, RecordingStore())

    assert dialog.size() == QSize(1080, 720)
    assert dialog.minimumSize() == QSize(960, 600)
    assert dialog.tree.topLevelItemCount() == 2
    assert dialog.tree.topLevelItem(0).text(0) == "Editor"
    assert dialog.tree.topLevelItem(0).child(0).text(0) == "File · Saved"
    assert dialog.tree.topLevelItem(1).text(0) == "Tools"
    assert dialog.tree.topLevelItem(1).child(0).text(0) == "External Tools · Saved"
    assert dialog.current_page_path == SettingsDialog.FILE_PATH
    assert dialog.tree.minimumWidth() == 240
    assert dialog.tree.maximumWidth() == 360
    assert dialog.splitter.handleWidth() == 8
    assert not dialog.splitter.childrenCollapsible()
    assert dialog.findChild(QSplitter, "settingsBodySplitter") is dialog.splitter
    assert dialog.search.accessibleName() == "Search settings"
    assert dialog.tree.accessibleName() == "Settings categories"
    assert dialog.status.accessibleName() == "Settings status"
    assert dialog.status.maximumHeight() == 72
    assert dialog.external_tools_page.ffmpeg.accessibleName() == "FFmpeg executable path"
    assert dialog.external_tools_page.ffprobe.accessibleName() == "FFprobe executable path"
    assert dialog.external_tools_page.realesrgan.accessibleName() == "Real-ESRGAN executable path"
    assert dialog.external_tools_page.model_directory.accessibleName() == "Real-ESRGAN model directory"
    file_item = dialog._leaf_items[SettingsDialog.FILE_PATH]  # pylint: disable=protected-access
    assert file_item.data(0, Qt.ItemDataRole.AccessibleTextRole) == "Editor File, Saved"
    assert file_item.toolTip(0) == "Editor → File — Saved"
    assert dialog.file_page.rules.item(0).toolTip() == dialog.file_page.rules.item(0).text()
    for scroll in dialog.findChildren(QScrollArea):
        assert scroll.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        assert not scroll.isAncestorOf(dialog.search)
        assert not scroll.isAncestorOf(dialog.status)

    dialog.show()
    qt_app.processEvents()
    assert 240 <= dialog.tree.width() <= 360
    for size in (QSize(960, 600), QSize(1080, 720), QSize(1400, 900)):
        dialog.resize(size)
        qt_app.processEvents()
        assert 240 <= dialog.tree.width() <= 360
        assert dialog.stack.width() >= 620
    dialog.close()
    validator.shutdown()


def test_search_filters_pages_and_restores_the_previous_selection(qt_app: QApplication, tmp_path: Path) -> None:
    validator = ExternalToolsValidator(RecordingDiscovery(_toolchain(tmp_path)))  # type: ignore[arg-type]
    dialog = _dialog(ApplicationSettings(), validator, RecordingStore())
    file_item = dialog._leaf_items[SettingsDialog.FILE_PATH]  # pylint: disable=protected-access
    tools_item = dialog._leaf_items[SettingsDialog.EXTERNAL_TOOLS_PATH]  # pylint: disable=protected-access

    dialog.search.setText("FFmpeg Vulkan")
    qt_app.processEvents()
    assert file_item.isHidden()
    assert not tools_item.isHidden()
    assert dialog.current_page_path == SettingsDialog.EXTERNAL_TOOLS_PATH

    dialog.search.setText("Move Up")
    qt_app.processEvents()
    assert not file_item.isHidden()
    assert tools_item.isHidden()
    assert dialog.current_page_path == SettingsDialog.FILE_PATH

    dialog.search.setText("not-a-setting")
    qt_app.processEvents()
    assert dialog.stack.currentWidget() is dialog.no_results_page

    dialog.search.clear()
    qt_app.processEvents()
    assert not file_item.isHidden() and not tools_item.isHidden()
    assert dialog.current_page_path == SettingsDialog.FILE_PATH
    dialog.close()
    validator.shutdown()


def test_file_page_keeps_rule_edits_in_the_shared_draft_until_ok(tmp_path: Path) -> None:
    rule = DeletionRule("*.mov", ("{source_stem}-last-frame.png",))
    settings = ApplicationSettings(deletion_rules=(rule,))
    store = RecordingStore()
    validator = ExternalToolsValidator(RecordingDiscovery(_toolchain(tmp_path)))  # type: ignore[arg-type]
    dialog = _dialog(settings, validator, store)
    item = dialog.file_page.rules.item(0)
    item.setCheckState(Qt.CheckState.Unchecked)

    assert dialog.dirty
    assert store.saved == []
    assert dialog._page_states[SettingsDialog.FILE_PATH] is SettingsValidationState.VALID  # pylint: disable=protected-access
    dialog.ok_button.click()

    assert dialog.result() == int(QDialog.DialogCode.Accepted)
    assert store.saved == [ApplicationSettings(deletion_rules=(DeletionRule("*.mov", ("{source_stem}-last-frame.png",), False),))]
    validator.shutdown()


def test_nullable_default_rules_remain_a_noop_until_edited(qt_app: QApplication, tmp_path: Path) -> None:
    del qt_app
    store = RecordingStore()
    validator = ExternalToolsValidator(RecordingDiscovery(_toolchain(tmp_path)))  # type: ignore[arg-type]
    dialog = _dialog(ApplicationSettings(deletion_rules=None), validator, store)

    assert not dialog.dirty
    dialog.ok_button.click()
    assert store.saved == []
    validator.shutdown()


def test_saved_home_shortcuts_remain_an_exact_noop(qt_app: QApplication, tmp_path: Path) -> None:
    del qt_app
    settings = ApplicationSettings(tools=ToolOverrides(ffmpeg=Path("~/bin/ffmpeg")))
    store = RecordingStore()
    validator = ExternalToolsValidator(RecordingDiscovery(_toolchain(tmp_path)))  # type: ignore[arg-type]
    dialog = _dialog(settings, validator, store)

    assert dialog.external_tools_page.overrides() == settings.tools
    assert not dialog.dirty
    dialog.ok_button.click()
    assert dialog.result() == int(QDialog.DialogCode.Accepted)
    assert not store.saved
    validator.shutdown()


def test_manual_validation_then_ok_saves_all_pages_once(qt_app: QApplication, tmp_path: Path) -> None:
    old_tools = ToolOverrides(ffmpeg=tmp_path / "old-ffmpeg")
    settings = ApplicationSettings(tools=old_tools, deletion_rules=(DeletionRule("*.mov", ("{source_stem}-last-frame.png",)),), target_height=1080)
    store = RecordingStore()
    discovery = RecordingDiscovery(_toolchain(tmp_path))
    validator = ExternalToolsValidator(discovery)  # type: ignore[arg-type]
    dialog = _dialog(settings, validator, store)
    dialog.external_tools_page.ffmpeg.clear()
    dialog.file_page.rules.item(0).setCheckState(Qt.CheckState.Unchecked)

    assert dialog._page_states[SettingsDialog.EXTERNAL_TOOLS_PATH] is SettingsValidationState.NEEDS_VALIDATION  # pylint: disable=protected-access
    dialog.external_tools_page.validate_button.click()
    assert _process_until(qt_app, lambda: not validator.busy and dialog._page_states[SettingsDialog.EXTERNAL_TOOLS_PATH] is SettingsValidationState.VALID)  # pylint: disable=protected-access
    assert store.saved == []

    dialog.ok_button.click()
    assert dialog.result() == int(QDialog.DialogCode.Accepted)
    assert discovery.calls == [ToolOverrides()]
    assert len(store.saved) == 1
    assert store.saved[0].tools == ToolOverrides()
    assert store.saved[0].deletion_rules == (DeletionRule("*.mov", ("{source_stem}-last-frame.png",), False),)
    assert store.saved[0].target_height == 1080
    validator.shutdown()


def test_ok_automatically_validates_changed_tools_before_atomic_save(qt_app: QApplication, tmp_path: Path) -> None:
    store = RecordingStore()
    discovery = RecordingDiscovery(_toolchain(tmp_path))
    validator = ExternalToolsValidator(discovery)  # type: ignore[arg-type]
    dialog = _dialog(ApplicationSettings(), validator, store)
    changed = tmp_path / "custom-ffmpeg"
    dialog.external_tools_page.ffmpeg.setText(str(changed))
    dialog.ok_button.click()

    assert store.saved == []
    assert _process_until(qt_app, lambda: dialog.result() == int(QDialog.DialogCode.Accepted) and not validator.busy)
    assert discovery.calls == [ToolOverrides(ffmpeg=changed)]
    assert len(store.saved) == 1 and store.saved[0].tools == ToolOverrides(ffmpeg=changed)
    validator.shutdown()


def test_ok_during_manual_validation_commits_that_same_snapshot(qt_app: QApplication, tmp_path: Path) -> None:
    store = RecordingStore()
    discovery = BlockingDiscovery(_toolchain(tmp_path))
    validator = ExternalToolsValidator(discovery)  # type: ignore[arg-type]
    dialog = _dialog(ApplicationSettings(), validator, store)
    changed = tmp_path / "custom-ffmpeg"
    dialog.external_tools_page.ffmpeg.setText(str(changed))
    dialog.external_tools_page.validate_button.click()
    assert discovery.started.wait(0.5)
    qt_app.processEvents()
    assert dialog.file_page.isEnabled()
    assert not dialog.external_tools_page.ffmpeg.isEnabled()
    assert dialog.cancel_button.isEnabled()

    dialog.ok_button.click()
    assert not dialog.file_page.isEnabled()
    assert dialog.cancel_button.isEnabled()
    assert not dialog.ok_button.isEnabled()
    discovery.release.set()

    assert _process_until(qt_app, lambda: dialog.result() == int(QDialog.DialogCode.Accepted) and not validator.busy)
    assert discovery.calls == [ToolOverrides(ffmpeg=changed)]
    assert len(store.saved) == 1 and store.saved[0].tools == ToolOverrides(ffmpeg=changed)
    validator.shutdown()


def test_stale_validation_result_cannot_save_a_changed_draft(qt_app: QApplication, tmp_path: Path) -> None:
    store = RecordingStore()
    discovery = BlockingDiscovery(_toolchain(tmp_path))
    validator = ExternalToolsValidator(discovery)  # type: ignore[arg-type]
    dialog = _dialog(ApplicationSettings(), validator, store)
    first_value = tmp_path / "first-ffmpeg"
    second_value = tmp_path / "second-ffmpeg"
    dialog.external_tools_page.ffmpeg.setText(str(first_value))
    dialog.external_tools_page.validate_button.click()
    assert discovery.started.wait(0.5)

    # Programmatic edits model any future control that can change while a
    # validation is in flight; the immutable result must still be rejected.
    dialog.external_tools_page.ffmpeg.setText(str(second_value))
    discovery.release.set()

    assert _process_until(qt_app, lambda: not validator.busy)
    assert dialog._page_states[SettingsDialog.EXTERNAL_TOOLS_PATH] is SettingsValidationState.NEEDS_VALIDATION  # pylint: disable=protected-access
    assert "stale result was ignored" in dialog.status.text()
    assert store.saved == []
    dialog._cancel_explicitly()  # pylint: disable=protected-access
    validator.shutdown()


def test_invalid_home_shortcut_is_inline_and_never_starts_validation(qt_app: QApplication, tmp_path: Path) -> None:
    store = RecordingStore()
    discovery = RecordingDiscovery(_toolchain(tmp_path))
    validator = ExternalToolsValidator(discovery)  # type: ignore[arg-type]
    dialog = _dialog(ApplicationSettings(), validator, store)
    dialog.show()
    qt_app.processEvents()

    dialog.external_tools_page.ffmpeg.setText("~advanced-ai-video-tools-user-that-does-not-exist/ffmpeg")
    assert dialog.dirty
    assert dialog._page_states[SettingsDialog.EXTERNAL_TOOLS_PATH] is SettingsValidationState.INVALID  # pylint: disable=protected-access
    assert dialog.external_tools_page.ffmpeg.property("validationError") is True
    assert "cannot be resolved" in dialog.external_tools_page.ffmpeg.accessibleDescription()

    dialog.ok_button.click()
    assert not validator.busy
    assert not discovery.calls and not store.saved
    assert dialog.focusWidget() is dialog.external_tools_page.ffmpeg

    dialog.external_tools_page.ffmpeg.clear()
    assert dialog.external_tools_page.validation_error_field is None
    assert dialog.external_tools_page.ffmpeg.property("validationError") is False
    dialog._cancel_explicitly()  # pylint: disable=protected-access
    validator.shutdown()


def test_malformed_validation_success_is_rejected_without_saving(qt_app: QApplication, tmp_path: Path) -> None:
    malformed_toolchain = Toolchain(ToolInfo("not-a-path", "ffmpeg test"), ToolInfo(tmp_path / "ffprobe", "ffprobe test"), ToolInfo(tmp_path / "realesrgan", "realesrgan test"), tmp_path / "models")  # type: ignore[arg-type]
    for result in (object(), malformed_toolchain):
        store = RecordingStore()
        validator = ExternalToolsValidator(InvalidResultDiscovery(result))  # type: ignore[arg-type]
        dialog = _dialog(ApplicationSettings(), validator, store)
        dialog.external_tools_page.ffmpeg.setText(str(tmp_path / "ffmpeg"))
        dialog.ok_button.click()

        assert _process_until(qt_app, lambda current_validator=validator, current_dialog=dialog: not current_validator.busy and current_dialog._page_states[SettingsDialog.EXTERNAL_TOOLS_PATH] is SettingsValidationState.INVALID)  # pylint: disable=protected-access
        assert dialog.result() != int(QDialog.DialogCode.Accepted)
        assert "invalid result" in dialog.external_tools_page.status.text()
        assert not store.saved
        dialog._cancel_explicitly()  # pylint: disable=protected-access
        validator.shutdown()


def test_validation_error_mapping_uses_the_failed_tool_not_path_text(qt_app: QApplication) -> None:
    del qt_app
    page = ExternalToolsPage(ApplicationSettings())

    assert page.show_validation_error("ffmpeg from configured path is not executable: /tools/ffprobe-wrapper") is page.ffmpeg
    assert page.show_validation_error("could not launch ffprobe: timed out") is page.ffprobe
    assert page.show_validation_error("Real-ESRGAN model directory /models is missing: realesrgan-x4plus.bin") is page.model_directory
    assert page.show_validation_error("Real-ESRGAN Vulkan smoke test failed: no device") is page.realesrgan


def test_failed_validation_keeps_draft_open_and_saved_settings_unchanged(qt_app: QApplication, tmp_path: Path) -> None:
    old_tools = ToolOverrides(ffmpeg=tmp_path / "known-ffmpeg")
    store = SettingsStore(tmp_path / "settings.yaml")
    store.save(ApplicationSettings(tools=old_tools))
    discovery = RecordingDiscovery(ToolDiscoveryError("Real-ESRGAN Vulkan smoke test failed: no device"))
    validator = ExternalToolsValidator(discovery)  # type: ignore[arg-type]
    dialog = SettingsDialog(store.load(), validator, store)
    dialog.show()
    qt_app.processEvents()
    dialog.external_tools_page.ffmpeg.setText(str(tmp_path / "broken-ffmpeg"))
    dialog.ok_button.click()

    assert _process_until(qt_app, lambda: not validator.busy and dialog._page_states[SettingsDialog.EXTERNAL_TOOLS_PATH] is SettingsValidationState.INVALID)  # pylint: disable=protected-access
    assert dialog.result() != int(QDialog.DialogCode.Accepted)
    assert store.load().tools == old_tools
    assert "Saved settings remain unchanged" in dialog.external_tools_page.status.text()
    assert dialog.external_tools_page.realesrgan.isEnabled()
    assert dialog.current_page_path == SettingsDialog.EXTERNAL_TOOLS_PATH
    assert dialog.focusWidget() is dialog.external_tools_page.realesrgan
    assert dialog.external_tools_page.realesrgan.property("validationError") is True
    assert "Vulkan smoke test failed" in dialog.external_tools_page.realesrgan.accessibleDescription()
    dialog._cancel_explicitly()  # pylint: disable=protected-access
    validator.shutdown()


def test_failed_revalidation_invalidates_an_older_success_for_the_same_draft(qt_app: QApplication, tmp_path: Path) -> None:
    changed = tmp_path / "custom-ffmpeg"
    discovery = RecordingDiscovery(_toolchain(tmp_path))
    validator = ExternalToolsValidator(discovery)  # type: ignore[arg-type]
    dialog = _dialog(ApplicationSettings(), validator, RecordingStore())
    dialog.external_tools_page.ffmpeg.setText(str(changed))
    dialog.external_tools_page.validate_button.click()
    assert _process_until(qt_app, lambda: not validator.busy and dialog._page_states[SettingsDialog.EXTERNAL_TOOLS_PATH] is SettingsValidationState.VALID)  # pylint: disable=protected-access

    discovery.result = ToolDiscoveryError("ffmpeg validation failed")
    dialog.external_tools_page.validate_button.click()
    assert _process_until(qt_app, lambda: not validator.busy and dialog._page_states[SettingsDialog.EXTERNAL_TOOLS_PATH] is SettingsValidationState.INVALID)  # pylint: disable=protected-access

    dialog.external_tools_page.ffmpeg.clear()
    dialog.external_tools_page.ffmpeg.setText(str(changed))
    assert dialog._page_states[SettingsDialog.EXTERNAL_TOOLS_PATH] is SettingsValidationState.NEEDS_VALIDATION  # pylint: disable=protected-access
    dialog._cancel_explicitly()  # pylint: disable=protected-access
    validator.shutdown()


def test_storage_failure_preserves_validated_draft_for_retry(qt_app: QApplication, tmp_path: Path) -> None:
    store = RecordingStore(SettingsError("read-only settings directory"))
    discovery = RecordingDiscovery(_toolchain(tmp_path))
    validator = ExternalToolsValidator(discovery)  # type: ignore[arg-type]
    dialog = _dialog(ApplicationSettings(), validator, store)
    dialog.external_tools_page.ffmpeg.setText(str(tmp_path / "ffmpeg"))
    dialog.ok_button.click()

    assert _process_until(qt_app, lambda: not validator.busy and "could not be saved" in dialog.status.text())
    assert dialog.result() != int(QDialog.DialogCode.Accepted)
    assert len(discovery.calls) == 1
    store.error = None
    dialog.ok_button.click()
    assert dialog.result() == int(QDialog.DialogCode.Accepted)
    assert len(discovery.calls) == 1
    assert len(store.saved) == 1
    validator.shutdown()


def test_cancelled_validation_is_ignored_and_reopen_allows_unrelated_save(qt_app: QApplication, tmp_path: Path) -> None:
    settings = ApplicationSettings(deletion_rules=(DeletionRule("*.mov", ("{source_stem}-last-frame.png",)),))
    store = RecordingStore()
    discovery = BlockingDiscovery(_toolchain(tmp_path))
    validator = ExternalToolsValidator(discovery)  # type: ignore[arg-type]
    first = _dialog(settings, validator, store)
    first.external_tools_page.ffmpeg.setText(str(tmp_path / "unsaved-ffmpeg"))
    first.external_tools_page.validate_button.click()
    assert discovery.started.wait(0.5)
    first._cancel_explicitly()  # pylint: disable=protected-access

    reopened = _dialog(settings, validator, store)
    assert not reopened.external_tools_page.ffmpeg.isEnabled()
    assert "earlier Settings window" in reopened.external_tools_page.status.text()
    reopened.file_page.rules.item(0).setCheckState(Qt.CheckState.Unchecked)
    reopened.ok_button.click()
    assert reopened.result() == int(QDialog.DialogCode.Accepted)
    assert len(store.saved) == 1
    assert store.saved[0].tools == settings.tools

    discovery.release.set()
    assert _process_until(qt_app, lambda: not validator.busy)
    assert len(store.saved) == 1
    validator.shutdown()


def test_reopened_external_tools_page_unlocks_when_abandoned_validation_finishes(qt_app: QApplication, tmp_path: Path) -> None:
    store = RecordingStore()
    discovery = BlockingDiscovery(_toolchain(tmp_path))
    validator = ExternalToolsValidator(discovery)  # type: ignore[arg-type]
    first = _dialog(ApplicationSettings(), validator, store)
    first.external_tools_page.ffmpeg.setText(str(tmp_path / "unsaved-ffmpeg"))
    first.external_tools_page.validate_button.click()
    assert discovery.started.wait(0.5)
    first._cancel_explicitly()  # pylint: disable=protected-access

    reopened = _dialog(ApplicationSettings(), validator, store)
    assert not reopened.external_tools_page.ffmpeg.isEnabled()
    discovery.release.set()

    assert _process_until(qt_app, lambda: not validator.busy and reopened.external_tools_page.ffmpeg.isEnabled())
    assert reopened._page_states[SettingsDialog.EXTERNAL_TOOLS_PATH] is SettingsValidationState.SAVED  # pylint: disable=protected-access
    assert not reopened.dirty and not store.saved
    reopened._cancel_explicitly()  # pylint: disable=protected-access
    validator.shutdown()


def test_session_state_restores_size_sidebar_and_selected_page(qt_app: QApplication, tmp_path: Path) -> None:
    state = SettingsDialogSessionState()
    validator = ExternalToolsValidator(RecordingDiscovery(_toolchain(tmp_path)))  # type: ignore[arg-type]
    first = _dialog(ApplicationSettings(), validator, RecordingStore(), state)
    first.show()
    qt_app.processEvents()
    first.resize(1000, 650)
    first.splitter.setSizes((320, 650))
    first.tree.setCurrentItem(first._leaf_items[SettingsDialog.EXTERNAL_TOOLS_PATH])  # pylint: disable=protected-access
    qt_app.processEvents()
    first._cancel_explicitly()  # pylint: disable=protected-access

    second = _dialog(ApplicationSettings(), validator, RecordingStore(), state)
    assert second.size() == QSize(1000, 650)
    assert second.current_page_path == SettingsDialog.EXTERNAL_TOOLS_PATH
    second.show()
    qt_app.processEvents()
    assert 300 <= second.tree.width() <= 330
    second.close()
    validator.shutdown()


def test_dirty_escape_confirms_but_explicit_cancel_is_immediate(qt_app: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    validator = ExternalToolsValidator(RecordingDiscovery(_toolchain(tmp_path)))  # type: ignore[arg-type]
    dialog = _dialog(ApplicationSettings(), validator, RecordingStore())
    dialog.external_tools_page.ffmpeg.setText(str(tmp_path / "custom-ffmpeg"))
    dialog.show()
    qt_app.processEvents()
    questions: list[str] = []

    def keep_editing(*_args: object, **_kwargs: object) -> QMessageBox.StandardButton:
        questions.append("asked")
        return QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(QMessageBox, "question", keep_editing)
    dialog.reject()
    assert questions == ["asked"]
    assert dialog.isVisible()
    dialog.close()
    assert questions == ["asked", "asked"]
    assert dialog.isVisible()

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("explicit Cancel must not confirm")),
    )
    dialog.cancel_button.click()
    assert not dialog.isVisible()
    validator.shutdown()


def test_file_page_reorders_and_restores_without_persistence(qt_app: QApplication) -> None:
    del qt_app
    first = DeletionRule("first-*.mov", ("{source_stem}-first.png",))
    second = DeletionRule("second-*.mov", ("{source_stem}-second.png",))
    page = FileSettingsPage(ApplicationSettings(deletion_rules=(first, second)))
    page.rules.setCurrentRow(1)
    page._move(-1)  # pylint: disable=protected-access
    assert page.deletion_rules() == (second, first)
    page._restore()  # pylint: disable=protected-access
    assert page.deletion_rules() == (DeletionRule("*.mov", ("{source_stem}-last-frame.png",)),)


def test_deletion_rule_editor_marks_invalid_fields_and_enables_save_only_when_valid(qt_app: QApplication) -> None:
    del qt_app
    dialog = DeletionRuleDialog()

    assert not dialog.save_button.isEnabled()
    assert dialog.source.property("validationError") is True
    assert dialog.targets.property("validationError") is True
    assert dialog.status.accessibleName() == "Deletion rule validation status"

    dialog.source.setText("*.mov")
    dialog.targets.setPlainText("{source_stem}-last-frame.png")
    assert dialog.save_button.isEnabled()
    assert dialog.source.property("validationError") is False
    assert dialog.targets.property("validationError") is False

    dialog.targets.setPlainText("../unsafe.png")
    assert not dialog.save_button.isEnabled()
    assert dialog.targets.property("validationError") is True
    assert "safe non-empty basename" in dialog.targets.accessibleDescription()
