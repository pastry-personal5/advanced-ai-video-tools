"""Headless tests for job editing, asynchronous preflight, and safe submission."""

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
import yaml

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QMimeData, QObject, QSize, QThread, QUrl, Signal  # noqa: E402  # pylint: disable=wrong-import-position,no-name-in-module
from PySide6.QtGui import QColor  # noqa: E402  # pylint: disable=wrong-import-position,no-name-in-module
from PySide6.QtWidgets import QApplication, QComboBox, QGroupBox, QLabel, QListWidget, QPushButton, QScrollArea, QToolButton, QWidget  # noqa: E402  # pylint: disable=wrong-import-position,no-name-in-module

from advanced_ai_video_tools.core.models import ColorMatrix, ColorProfile, ConcatStrategy, IssueCode, IssueSeverity, JobPlan, JobRequest, OverwriteMode, PipelineStage, PreflightIssue, PreflightReport, ProgressEvent, Rational, ToolOverrides  # noqa: E402  # pylint: disable=wrong-import-position
from advanced_ai_video_tools.gui.editor import EDITOR_SETTINGS_WIDTH, OUTPUT_DIRECTORY_ICON_COLOR, OUTPUT_DIRECTORY_ICON_SIZE, SOURCE_CLIP_ACTION_ICON_SIZE, SOURCE_CLIP_FILENAME_MAX_DISPLAY_WIDTH, SOURCE_CLIP_ROW_HEIGHT, JobEditor  # noqa: E402  # pylint: disable=wrong-import-position
from advanced_ai_video_tools.gui.preflight import GuiPreflightController  # noqa: E402  # pylint: disable=wrong-import-position
from advanced_ai_video_tools.gui.source_clip_actions import SourceClipTrashService  # noqa: E402  # pylint: disable=wrong-import-position
from advanced_ai_video_tools.gui.submission import JobSubmissionController, PreflightDecision, PreflightDialog  # noqa: E402  # pylint: disable=wrong-import-position
from advanced_ai_video_tools.gui.theme import CONTROL_HEIGHT, MAJOR_REGION_GAP, SPACE_2, SPACE_3, SPACE_4, apply_dark_theme  # noqa: E402  # pylint: disable=wrong-import-position
from advanced_ai_video_tools.system.settings import ApplicationSettings, SettingsStore  # noqa: E402  # pylint: disable=wrong-import-position

_CREATED = datetime(2026, 8, 21, 14, 30, 52, 123456, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def qt_app() -> QApplication:
    """Provide one offscreen application for submission widgets and threads."""

    existing = QCoreApplication.instance()
    if existing is not None and not isinstance(existing, QApplication):
        raise RuntimeError("a non-GUI Qt application already exists")
    return existing or QApplication(["ai-video-tools-submission-tests"])


def _process_until(qt_app: QApplication, predicate: Callable[[], bool], timeout: float = 1.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qt_app.processEvents()
        if predicate():
            return True
        time.sleep(0.001)
    qt_app.processEvents()
    return predicate()


def _request(tmp_path: Path) -> JobRequest:
    return JobRequest((tmp_path / "input" / "clip.mov",), tmp_path / "output", target_height=2160, created_at=_CREATED, generated_output_basename="ai-video-20260821-143052-0198f30d6e7b70008000000000000000.mp4")


def _plan(tmp_path: Path) -> JobPlan:
    return JobPlan(
        created_at=_CREATED,
        output_path=tmp_path / "output" / "preview.mp4",
        generated_output_name=True,
        probes=(),
        output_frame_rate=Rational(24, 1),
        output_width=3840,
        output_height=2160,
        ai_scale=2,
        concat_strategy=ConcatStrategy.STREAM_COPY,
        output_audio_layout=None,
        normalization_reasons=(),
        estimated_peak_bytes=100,
        required_free_bytes=120,
        output_color_profile=ColorProfile(ColorMatrix.BT709, "bt709", "bt709"),
    )


class RecordingRegistry:
    """Capture diagnostic plan reservation release."""

    def __init__(self) -> None:
        self.released: list[Path] = []

    def release(self, path: Path) -> None:
        """Record one preview-only output release."""

        self.released.append(path)


class RecordingPreflight:
    """Return a typed report while recording its execution thread."""

    def __init__(self, report: PreflightReport) -> None:
        self.report = report
        self.registry = RecordingRegistry()
        self.thread_identifier: int | None = None

    def run(self, _request: JobRequest, progress: object = None) -> PreflightReport:
        """Emit measured progress and return the configured report."""

        self.thread_identifier = threading.get_ident()
        if callable(progress):
            progress(ProgressEvent(PipelineStage.PROBE, 1, 1, "Preview probe complete"))
        return self.report


class FakePreview(QObject):
    """Controllable preview signals for submission-policy tests."""

    finished = Signal(object, object)
    failed = Signal(object, str)
    progress = Signal(object)
    busy_changed = Signal(bool)

    def __init__(self) -> None:
        super().__init__()
        self.requests: list[JobRequest] = []

    def start(self, request: JobRequest) -> bool:
        """Record a preview request without resolving it automatically."""

        self.requests.append(request)
        return True


class RecordingQueue:
    """Capture the authoritative request handed to queue execution."""

    def __init__(self) -> None:
        self.requests: list[JobRequest] = []

    def submit(self, request: JobRequest) -> str:
        """Record and return one stable fake identifier."""

        self.requests.append(request)
        return "queued-job-id"


def test_editor_preserves_concat_order_and_builds_frozen_supported_request(qt_app: QApplication, tmp_path: Path) -> None:
    """Visible clip order becomes immutable backend intent without safety acknowledgement."""

    tools = ToolOverrides(ffmpeg=tmp_path / "ffmpeg", ffprobe=tmp_path / "ffprobe", realesrgan=tmp_path / "realesrgan", model_directory=tmp_path / "models")
    settings = ApplicationSettings(tools=tools, target_height=2160, overwrite_mode=OverwriteMode.NO_OVERWRITE)
    editor = JobEditor(settings, clock=lambda: _CREATED)
    paths = (tmp_path / "one.mov", tmp_path / "two.mov", tmp_path / "three.mov")
    assert editor.findChild(QGroupBox, "sourceClipListGroup").title() == "Source Clips"
    editor.add_inputs(paths)
    assert [editor.inputs.item(row).text() for row in range(editor.inputs.count())] == [""] * len(paths)
    editor.inputs.setCurrentRow(2)

    assert editor.move_selected(-1)
    assert editor.input_paths() == (paths[0], paths[2], paths[1])
    editor.output_directory.setText(str(tmp_path / "output"))
    editor.target_height.setValue(1080)
    request = editor.build_request()

    assert request.inputs == (paths[0], paths[2], paths[1])
    assert request.output_directory == tmp_path / "output"
    assert request.target_height == 1080
    assert request.tools == tools
    assert request.overwrite_mode is OverwriteMode.NO_OVERWRITE
    assert not request.acknowledge_dropped_streams
    assert request.created_at == _CREATED
    assert request.generated_output_basename is not None and request.generated_output_basename.startswith("ai-video-20260821-143052-")
    assert QCoreApplication.instance() is qt_app


def test_editor_shows_inline_accessible_validation_errors(qt_app: QApplication) -> None:
    """Basic field errors are routed to the global message stream before preflight."""

    del qt_app
    editor = JobEditor(ApplicationSettings())
    messages: list[str] = []
    editor.message.connect(messages.append)
    editor.submit_button.click()

    assert messages == ["Add at least one input clip."]
    assert editor.findChild(QLabel, "editorStatus") is None

    editor.add_inputs((Path("clip.mov"),))
    editor.output_directory.setText("/tmp/output")
    editor.submit_button.click()
    assert messages == ["Add at least one input clip."]


def test_basic_settings_width_and_target_height_guidance(qt_app: QApplication) -> None:
    """Basic settings use the shared editor width and readable guidance."""

    del qt_app
    editor = JobEditor(ApplicationSettings())
    basic_settings = editor.findChild(QGroupBox, "basicSettings")
    explanation = editor.findChild(QLabel, "targetHeightExplanation")

    assert basic_settings is not None
    assert basic_settings.width() == EDITOR_SETTINGS_WIDTH
    assert explanation is not None
    assert "preserve aspect ratio" in explanation.text()
    assert explanation.font().pointSize() == 12

    output_explanation = editor.findChild(QLabel, "outputDirectoryExplanation")
    output_button = editor.findChild(QToolButton, "chooseOutputButton")
    assert output_explanation is not None
    assert output_explanation.font().pointSize() == 12
    assert "completed videos" in output_explanation.text()
    assert output_button is not None
    assert output_button.text() == ""
    assert output_button.accessibleName() == "Choose output directory"
    assert editor.output_directory.height() == output_button.height() == 32
    output_row = editor.findChild(QGroupBox, "outputDirectoryGroup").layout().itemAt(1).layout()
    assert output_row is not None
    assert [output_row.itemAt(index).widget() for index in range(2)] == [editor.output_directory, output_button]
    assert output_button.iconSize() == QSize(16, 16)
    image = output_button.icon().pixmap(QSize(OUTPUT_DIRECTORY_ICON_SIZE, OUTPUT_DIRECTORY_ICON_SIZE)).toImage()
    assert any(image.pixelColor(x, y).name() == OUTPUT_DIRECTORY_ICON_COLOR for x in range(image.width()) for y in range(image.height()))
    visible_rows = [row for row in range(image.height()) if any(image.pixelColor(column, row).alpha() > 0 for column in range(image.width()))]
    assert visible_rows[0] == image.height() - visible_rows[-1] - 1
    assert output_button.styleSheet() == ""
    assert image.pixelColor(0, 0).alpha() == 0

    upscaler_group = editor.findChild(QGroupBox, "aiUpscalerGroup")
    upscaler_explanation = editor.findChild(QLabel, "aiUpscalerExplanation")
    assert upscaler_group is not None
    assert upscaler_group.title() == "AI Upscaler"
    assert upscaler_explanation is not None
    assert upscaler_explanation.font().pointSize() == 12
    assert "Enhances video detail" in upscaler_explanation.text()
    assert basic_settings.styleSheet() == ""
    assert editor.findChild(QGroupBox, "outputDirectoryGroup").styleSheet() == ""
    assert editor.findChild(QGroupBox, "targetHeightGroup").styleSheet() == ""
    assert upscaler_group.styleSheet() == ""


def test_editor_uses_shared_spacing_and_control_metrics(qt_app: QApplication, tmp_path: Path) -> None:
    """The job editor's panels, controls, and rows share one visual system."""

    apply_dark_theme(qt_app)
    source = tmp_path / "source.mov"
    source.touch()
    editor = JobEditor(ApplicationSettings())
    editor.add_inputs((source,))
    editor.show()
    qt_app.processEvents()

    basic_settings = editor.findChild(QGroupBox, "basicSettings")
    source_group = editor.findChild(QGroupBox, "sourceClipListGroup")
    assert basic_settings is not None
    assert source_group is not None
    assert source_group.title() == "Source Clips"
    assert basic_settings.layout().contentsMargins().left() == SPACE_3
    assert basic_settings.layout().contentsMargins().top() == SPACE_4
    settings_scroll = editor.findChild(QScrollArea, "basicSettingsScroll")
    assert settings_scroll is not None
    settings_content_layout = settings_scroll.widget().layout()
    assert settings_content_layout.contentsMargins().left() == SPACE_2
    assert settings_content_layout.contentsMargins().right() == SPACE_2
    assert settings_content_layout.contentsMargins().top() == SPACE_2
    assert settings_content_layout.contentsMargins().bottom() == SPACE_2
    assert source_group.layout().contentsMargins().left() == SPACE_3
    assert source_group.layout().contentsMargins().top() == SPACE_4
    assert source_group.layout().spacing() == SPACE_2
    assert editor.layout().itemAt(0).layout().spacing() == MAJOR_REGION_GAP
    assert {button.height() for button in (editor.add_button, editor.input_up_button, editor.input_down_button, editor.submit_button, editor.output_button, editor.target_height)} == {CONTROL_HEIGHT}
    assert editor.inputs.minimumHeight() == CONTROL_HEIGHT * 5
    assert editor.inputs.sizeHintForRow(0) == SOURCE_CLIP_ROW_HEIGHT
    remove_button = editor.findChild(QToolButton, "sourceClipRemoveButton")
    assert remove_button is not None
    assert remove_button.size() == QSize(CONTROL_HEIGHT, CONTROL_HEIGHT)
    assert remove_button.iconSize() == QSize(SOURCE_CLIP_ACTION_ICON_SIZE, SOURCE_CLIP_ACTION_ICON_SIZE)
    assert editor.findChild(QPushButton, "removeClipButton") is None
    assert "border-radius: 8px" in qt_app.styleSheet()
    assert "border-radius: 6px" in qt_app.styleSheet()
    assert editor.target_height.style().metaObject().className() in {"QStyleSheetStyle", "_ReadableSpinBoxStyle"}
    editor.close()


def test_source_row_fullscreen_action_matches_adjacent_icons(qt_app: QApplication, tmp_path: Path) -> None:
    """The fullscreen row action shares the adjacent actions' subdued treatment."""

    apply_dark_theme(qt_app)
    source = tmp_path / "source.mov"
    source.touch()
    editor = JobEditor(ApplicationSettings())
    editor.add_inputs((source,))
    fullscreen_button = editor.findChild(QToolButton, "sourceClipFullscreenButton")
    remove_button = editor.findChild(QToolButton, "sourceClipRemoveButton")
    menu_button = editor.findChild(QToolButton, "sourceClipMenuButton")
    assert fullscreen_button is not None
    assert remove_button is not None
    assert menu_button is not None
    for button in (fullscreen_button, remove_button, menu_button):
        assert button.size() == QSize(CONTROL_HEIGHT, CONTROL_HEIGHT)
        assert button.iconSize() == QSize(SOURCE_CLIP_ACTION_ICON_SIZE, SOURCE_CLIP_ACTION_ICON_SIZE)
        assert not button.icon().isNull()
        assert button.styleSheet() == ""

    assert fullscreen_button.text() == ""
    fullscreen_image = fullscreen_button.icon().pixmap(QSize(SOURCE_CLIP_ACTION_ICON_SIZE, SOURCE_CLIP_ACTION_ICON_SIZE)).toImage()
    fullscreen_pixels = [fullscreen_image.pixelColor(column, row) for row in range(fullscreen_image.height()) for column in range(fullscreen_image.width()) if fullscreen_image.pixelColor(column, row).alpha() > 0]
    expected_color = QColor(OUTPUT_DIRECTORY_ICON_COLOR)
    assert fullscreen_pixels
    assert all(max(abs(pixel.red() - expected_color.red()), abs(pixel.green() - expected_color.green()), abs(pixel.blue() - expected_color.blue())) <= 8 for pixel in fullscreen_pixels)
    assert max(pixel.lightness() for pixel in fullscreen_pixels) < 205
    visible_columns = [column for column in range(fullscreen_image.width()) if any(fullscreen_image.pixelColor(column, row).alpha() > 0 for row in range(fullscreen_image.height()))]
    visible_rows = [row for row in range(fullscreen_image.height()) if any(fullscreen_image.pixelColor(column, row).alpha() > 0 for column in range(fullscreen_image.width()))]
    assert visible_columns[0] == fullscreen_image.width() - visible_columns[-1] - 1
    assert visible_rows[0] == fullscreen_image.height() - visible_rows[-1] - 1
    editor.close()


def test_target_height_remains_custom_without_presets(qt_app: QApplication) -> None:
    """Target height stays an editable even-pixel control with no preset selector."""

    del qt_app
    editor = JobEditor(ApplicationSettings(target_height=2160))
    editor.target_height.setValue(1440)

    assert editor.target_height.value() == 1440
    assert editor.target_height.suffix() == " px"
    assert editor.target_height.singleStep() == 2
    assert editor.findChildren(QComboBox) == []


def test_source_clip_reorder_controls_are_grouped_and_right_aligned(qt_app: QApplication) -> None:
    """Move controls share one right-aligned group in the source-list row."""

    editor = JobEditor(ApplicationSettings())
    source_group = editor.findChild(QGroupBox, "sourceClipListGroup")
    move_controls = editor.findChild(QWidget, "sourceClipMoveControls")
    assert source_group is not None
    assert move_controls is not None
    move_layout = move_controls.layout()
    assert move_layout is not None
    assert [move_layout.itemAt(index).widget() for index in range(2)] == [editor.input_up_button, editor.input_down_button]

    input_controls = source_group.layout().itemAt(1).layout()
    assert input_controls is not None
    assert input_controls.itemAt(0).widget() is editor.add_button
    assert input_controls.itemAt(1).spacerItem() is not None
    assert input_controls.itemAt(2).widget() is move_controls

    editor.resize(1200, 500)
    editor.show()
    qt_app.processEvents()
    assert move_controls.geometry().right() == input_controls.geometry().right()
    editor.close()


def test_source_rows_offer_minus_remove_action(qt_app: QApplication, tmp_path: Path) -> None:
    """A row minus-circle action removes only the source-list item."""

    del qt_app
    first = tmp_path / "first.mov"
    second = tmp_path / "second.mov"
    first.touch()
    second.touch()
    editor = JobEditor(ApplicationSettings())
    editor.add_inputs((first, second))
    buttons = editor.findChildren(QToolButton, "sourceClipRemoveButton")
    assert len(buttons) == 2
    assert buttons[1].accessibleName() == "Remove second.mov from source clips"

    messages: list[str] = []
    editor.message.connect(messages.append)
    buttons[1].click()

    assert second.exists()
    assert editor.input_paths() == (first,)
    assert messages == ["Removed source clip: second.mov"]


def test_source_row_overflow_menu_offers_filesystem_and_trash_actions(qt_app: QApplication, tmp_path: Path) -> None:
    """The per-row overflow menu exposes Finder reveal and OS Trash actions."""

    del qt_app
    path = tmp_path / "clip.mov"
    path.touch()
    editor = JobEditor(ApplicationSettings(), trash_service=SourceClipTrashService(lambda _path: True))
    editor.add_inputs((path, path))
    menu_button = editor.findChild(QToolButton, "sourceClipMenuButton")
    assert menu_button is not None
    assert not menu_button.icon().isNull()
    messages: list[str] = []
    editor.message.connect(messages.append)
    menu = editor._item_menu(editor.inputs.item(0), menu_button)  # pylint: disable=protected-access
    assert [action.text() for action in menu.actions()] == ["Open in Filesystem", "", "Move to Trash"]
    menu.actions()[2].trigger()
    assert not editor.input_paths()
    assert path.exists()
    assert messages == ["Moved source clip to Trash: clip.mov and removed 2 list entries."]


def test_trash_failure_preserves_duplicate_source_rows(qt_app: QApplication, tmp_path: Path) -> None:
    """A failed OS Trash operation cannot silently discard duplicate intent."""

    del qt_app
    path = tmp_path / "clip.mov"
    path.touch()
    editor = JobEditor(ApplicationSettings(), trash_service=SourceClipTrashService(lambda _path: False))
    editor.add_inputs((path, path))
    menu_button = editor.findChild(QToolButton, "sourceClipMenuButton")
    assert menu_button is not None
    messages: list[str] = []
    editor.message.connect(messages.append)
    menu = editor._item_menu(editor.inputs.item(0), menu_button)  # pylint: disable=protected-access
    menu.actions()[2].trigger()

    assert editor.input_paths() == (path, path)
    assert messages == ["Could not move source clip to Trash: clip.mov"]


def test_trash_is_blocked_when_source_is_in_active_queue_intent(qt_app: QApplication, tmp_path: Path) -> None:
    """Queued source intent blocks Trash and emits a global-ready message."""

    del qt_app
    path = tmp_path / "clip.mov"
    path.touch()
    calls: list[str] = []
    editor = JobEditor(
        ApplicationSettings(),
        trash_service=SourceClipTrashService(lambda value: calls.append(value) or True),
        queued_inputs=lambda: (path,),
    )
    editor.add_inputs((path,))
    menu_button = editor.findChild(QToolButton, "sourceClipMenuButton")
    assert menu_button is not None
    messages: list[str] = []
    editor.message.connect(messages.append)
    menu = editor._item_menu(editor.inputs.item(0), menu_button)  # pylint: disable=protected-access
    menu.actions()[2].trigger()

    assert editor.input_paths() == (path,)
    assert not calls
    assert messages == ["Cannot move source clip to Trash because it is already queued: clip.mov"]


def test_trash_provider_exception_preserves_source(qt_app: QApplication, tmp_path: Path) -> None:
    """An OS Trash provider exception fails closed without list mutation."""

    del qt_app
    path = tmp_path / "clip.mov"
    path.touch()

    def raising_mover(_path: str) -> bool:
        raise OSError("Trash service unavailable")

    editor = JobEditor(ApplicationSettings(), trash_service=SourceClipTrashService(raising_mover))
    editor.add_inputs((path,))
    menu_button = editor.findChild(QToolButton, "sourceClipMenuButton")
    assert menu_button is not None
    messages: list[str] = []
    editor.message.connect(messages.append)
    menu = editor._item_menu(editor.inputs.item(0), menu_button)  # pylint: disable=protected-access
    menu.actions()[2].trigger()

    assert editor.input_paths() == (path,)
    assert path.exists()
    assert messages == ["Could not move source clip to Trash: clip.mov"]


def test_queue_lookup_exception_blocks_trash_fail_closed(qt_app: QApplication, tmp_path: Path) -> None:
    """A queue-state lookup failure cannot authorize a destructive action."""

    del qt_app
    path = tmp_path / "clip.mov"
    path.touch()
    editor = JobEditor(ApplicationSettings(), queued_inputs=lambda: (_ for _ in ()).throw(RuntimeError("queue unavailable")))
    editor.add_inputs((path,))
    menu_button = editor.findChild(QToolButton, "sourceClipMenuButton")
    assert menu_button is not None
    messages: list[str] = []
    editor.message.connect(messages.append)
    menu = editor._item_menu(editor.inputs.item(0), menu_button)  # pylint: disable=protected-access
    menu.actions()[2].trigger()

    assert editor.input_paths() == (path,)
    assert path.exists()
    assert messages == ["Could not verify whether source clip is safe to move to Trash: clip.mov"]


def test_long_source_filename_is_elided_and_remove_control_is_compact(qt_app: QApplication, tmp_path: Path) -> None:
    """Long names elide in the row and the minus remove control stays compact."""

    path = tmp_path / "a-very-long-source-clip-filename\nthat-needs-elision-in-the-row.mov"
    editor = JobEditor(ApplicationSettings())
    editor.resize(1200, 500)
    editor.add_inputs((path,))
    editor.show()
    qt_app.processEvents()
    filename = editor.findChild(QLabel, "sourceClipFilename")
    remove_button = editor.findChild(QToolButton, "sourceClipRemoveButton")

    assert filename is not None
    assert editor.inputs.item(0).text() == ""
    assert len(editor.findChildren(QLabel, "sourceClipFilename")) == 1
    assert "…" in filename.text()
    assert filename.text() != path.name
    assert "\n" not in filename.text()
    assert filename.wordWrap() is False
    assert filename.contentsRect().width() > SOURCE_CLIP_FILENAME_MAX_DISPLAY_WIDTH
    assert filename.fontMetrics().horizontalAdvance(filename.text()) <= SOURCE_CLIP_FILENAME_MAX_DISPLAY_WIDTH
    assert filename.parentWidget().width() <= editor.inputs.viewport().width()
    assert filename.parentWidget().height() == editor.inputs.sizeHintForRow(0)
    assert filename.toolTip() == str(path)
    assert editor.input_paths() == (path,)
    assert remove_button is not None
    assert remove_button.width() == CONTROL_HEIGHT
    assert remove_button.iconSize().width() == SOURCE_CLIP_ACTION_ICON_SIZE
    editor.close()


def test_editor_drop_boundary_accepts_local_files_and_rejects_remote_urls(qt_app: QApplication, tmp_path: Path) -> None:
    """File-manager drops accept local files only and preserve URL safety."""

    del qt_app
    first = tmp_path / "first.mov"
    second = tmp_path / "second.mov"
    text_file = tmp_path / "notes.txt"
    first.touch()
    second.touch()
    text_file.touch()
    editor = JobEditor(ApplicationSettings())

    class DropEvent:
        """Minimal typed mime-data boundary for headless drop testing."""

        def __init__(self, urls: tuple[QUrl, ...]) -> None:
            """Build one fake drop event."""

            self._mime = QMimeData()
            self._mime.setUrls(list(urls))

        def mimeData(self) -> QMimeData:  # pylint: disable=invalid-name
            """Return the event mime payload."""

            return self._mime

    local = DropEvent((QUrl.fromLocalFile(str(first)), QUrl.fromLocalFile(str(second))))
    assert editor._local_drop_paths(local) == (first, second)  # pylint: disable=protected-access
    non_video = DropEvent((QUrl.fromLocalFile(str(text_file)),))
    assert not editor._local_drop_paths(non_video)  # pylint: disable=protected-access
    remote = DropEvent((QUrl("https://example.com/video.mov"),))
    assert not editor._local_drop_paths(remote)  # pylint: disable=protected-access


def test_preflight_controller_runs_off_gui_thread_forwards_progress_and_releases_plan(qt_app: QApplication, tmp_path: Path) -> None:
    """Tool discovery and probing never execute on the Qt presentation thread."""

    report = PreflightReport((), _plan(tmp_path), None)
    service = RecordingPreflight(report)
    controller = GuiPreflightController(service_factory=lambda: service)  # type: ignore[arg-type]
    results: list[tuple[JobRequest, PreflightReport]] = []
    progress: list[ProgressEvent] = []
    callback_threads: list[QThread] = []

    def record_result(request: object, result: object) -> None:
        assert isinstance(request, JobRequest)
        assert isinstance(result, PreflightReport)
        results.append((request, result))
        callback_threads.append(QThread.currentThread())

    controller.finished.connect(record_result)
    controller.progress.connect(progress.append)
    assert controller.start(_request(tmp_path))
    assert not controller.start(_request(tmp_path))

    assert _process_until(qt_app, lambda: bool(results) and not controller.busy)
    assert service.thread_identifier is not None and service.thread_identifier != threading.get_ident()
    assert callback_threads == [qt_app.thread()]
    assert progress and progress[-1].message == "Preview probe complete"
    assert service.registry.released == [report.plan.output_path]
    controller.shutdown()


def test_stream_drop_review_requires_checkbox_and_unrelated_errors_cannot_queue(qt_app: QApplication, tmp_path: Path) -> None:
    """The native review cannot silently bypass stream dropping or real errors."""

    stream_issue = PreflightIssue(IssueSeverity.ERROR, IssueCode.STREAM_ACKNOWLEDGEMENT, "One subtitle will be dropped.", tmp_path / "clip.mov")
    stream_dialog = PreflightDialog(PreflightReport((stream_issue,), None, None))
    assert not stream_dialog.queue_button.isEnabled()
    assert stream_dialog.findChild(QListWidget, "preflightIssues").item(0).text() == "Blocking issues"
    stream_dialog.acknowledge.setChecked(True)
    assert stream_dialog.queue_button.isEnabled()

    hdr_issue = PreflightIssue(IssueSeverity.ERROR, IssueCode.UNSUPPORTED_HDR, "HDR is unsupported.", tmp_path / "clip.mov")
    blocked_dialog = PreflightDialog(PreflightReport((hdr_issue,), None, None))
    assert not blocked_dialog.queue_button.isEnabled()
    assert QCoreApplication.instance() is qt_app


def test_acknowledged_request_is_queued_and_only_non_safety_preferences_persist(qt_app: QApplication, tmp_path: Path) -> None:
    """Per-job acknowledgement reaches the queue but never the settings document."""

    input_directory = tmp_path / "input"
    output_directory = tmp_path / "output"
    input_directory.mkdir()
    output_directory.mkdir()
    request = _request(tmp_path)
    preview = FakePreview()
    queue = RecordingQueue()
    store = SettingsStore(tmp_path / "settings.yaml")
    settings = ApplicationSettings(target_height=720)
    decisions: list[PreflightReport] = []

    def acknowledge(_parent: object, report: PreflightReport) -> PreflightDecision:
        decisions.append(report)
        return PreflightDecision(True, acknowledge_dropped_streams=True)

    controller = JobSubmissionController(queue, preview, settings, store, decision_provider=acknowledge)  # type: ignore[arg-type]
    queued: list[str] = []
    controller.queued.connect(queued.append)
    controller.start(request)
    issue = PreflightIssue(IssueSeverity.ERROR, IssueCode.STREAM_ACKNOWLEDGEMENT, "An extra audio stream will be dropped.", request.inputs[0], "reviewed-inventory-key")
    preview.finished.emit(request, PreflightReport((issue,), None, None))
    qt_app.processEvents()

    assert decisions
    assert queued == ["queued-job-id"]
    assert len(queue.requests) == 1 and queue.requests[0].acknowledge_dropped_streams
    assert queue.requests[0].acknowledged_stream_keys == ("reviewed-inventory-key",)
    persisted = store.load()
    assert persisted.target_height == 2160
    assert persisted.recent_input_directory == input_directory
    assert persisted.recent_output_directory == output_directory
    document = yaml.safe_load(store.path.read_text(encoding="utf-8"))
    assert "acknowledge_dropped_streams" not in document
    assert "acknowledge_dropped_streams" not in document["processing"]


def test_submission_controller_refuses_unrelated_error_even_if_provider_accepts(qt_app: QApplication, tmp_path: Path) -> None:
    """An injected or faulty decision provider cannot override media safety errors."""

    preview = FakePreview()
    queue = RecordingQueue()
    controller = JobSubmissionController(queue, preview, ApplicationSettings(), SettingsStore(tmp_path / "settings.yaml"), decision_provider=lambda _parent, _report: PreflightDecision(True, True))  # type: ignore[arg-type]
    request = _request(tmp_path)
    controller.start(request)
    issue = PreflightIssue(IssueSeverity.ERROR, IssueCode.UNSUPPORTED_HDR, "HDR is unsupported.", request.inputs[0])
    preview.finished.emit(request, PreflightReport((issue,), None, None))
    qt_app.processEvents()

    assert not queue.requests
