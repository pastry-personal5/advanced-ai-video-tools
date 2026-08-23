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

from PySide6.QtCore import QCoreApplication, QMimeData, QObject, QThread, QUrl, Signal  # noqa: E402  # pylint: disable=wrong-import-position,no-name-in-module
from PySide6.QtWidgets import QApplication, QGroupBox, QLabel, QListWidget, QToolButton, QWidget  # noqa: E402  # pylint: disable=wrong-import-position,no-name-in-module

from ai_video_tools.core.models import ColorMatrix, ColorProfile, ConcatStrategy, IssueCode, IssueSeverity, JobPlan, JobRequest, OverwriteMode, PipelineStage, PreflightIssue, PreflightReport, ProgressEvent, Rational, ToolOverrides  # noqa: E402  # pylint: disable=wrong-import-position
from ai_video_tools.gui.editor import SOURCE_CLIP_FILENAME_MAX_DISPLAY_WIDTH, JobEditor  # noqa: E402  # pylint: disable=wrong-import-position
from ai_video_tools.gui.preflight import GuiPreflightController  # noqa: E402  # pylint: disable=wrong-import-position
from ai_video_tools.gui.submission import JobSubmissionController, PreflightDecision, PreflightDialog  # noqa: E402  # pylint: disable=wrong-import-position
from ai_video_tools.system.settings import ApplicationSettings, SettingsStore  # noqa: E402  # pylint: disable=wrong-import-position

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
    assert editor.findChild(QLabel, "sourceClipsLabel").text() == "Source Clips"
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
    """Basic settings provide room for compact target-height guidance."""

    del qt_app
    editor = JobEditor(ApplicationSettings())
    basic_settings = editor.findChild(QGroupBox, "basicSettings")
    explanation = editor.findChild(QLabel, "targetHeightExplanation")

    assert basic_settings is not None
    assert basic_settings.width() == 290
    assert explanation is not None
    assert "preserve aspect ratio" in explanation.text()
    assert explanation.font().pointSize() <= 10

    output_explanation = editor.findChild(QLabel, "outputDirectoryExplanation")
    output_button = editor.findChild(QToolButton, "chooseOutputButton")
    assert output_explanation is not None
    assert output_explanation.font().pointSize() <= 10
    assert "completed videos" in output_explanation.text()
    assert output_button is not None
    assert output_button.text() == ""
    assert output_button.accessibleName() == "Choose output directory"

    upscaler_group = editor.findChild(QGroupBox, "aiUpscalerGroup")
    upscaler_explanation = editor.findChild(QLabel, "aiUpscalerExplanation")
    assert upscaler_group is not None
    assert upscaler_group.title() == "AI Upscaler"
    assert upscaler_explanation is not None
    assert upscaler_explanation.font().pointSize() <= 10
    assert "Enhances video detail" in upscaler_explanation.text()
    assert "font-weight: 700" in basic_settings.styleSheet()
    assert f"font-size: {basic_settings.font().pointSize() + 4}pt" in basic_settings.styleSheet()
    assert "font-weight: 700" in editor.findChild(QGroupBox, "outputDirectoryGroup").styleSheet()
    assert "font-weight: 700" in editor.findChild(QGroupBox, "targetHeightGroup").styleSheet()
    assert "font-weight: 700" in upscaler_group.styleSheet()


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

    input_controls = source_group.layout().itemAt(2).layout()
    assert input_controls is not None
    assert [input_controls.itemAt(index).widget() for index in range(2)] == [editor.add_button, editor.remove_button]
    assert input_controls.itemAt(2).spacerItem() is not None
    assert input_controls.itemAt(3).widget() is move_controls

    editor.resize(1200, 500)
    editor.show()
    qt_app.processEvents()
    assert move_controls.geometry().right() == input_controls.geometry().right()
    editor.close()


def test_source_rows_offer_os_trash_action(qt_app: QApplication, tmp_path: Path) -> None:
    """A row Trash action moves the source file before removing its row."""

    del qt_app
    first = tmp_path / "first.mov"
    second = tmp_path / "second.mov"
    first.touch()
    second.touch()
    moved: list[str] = []

    def move_to_trash(path: str) -> bool:
        moved.append(path)
        return True

    editor = JobEditor(ApplicationSettings(), trash_mover=move_to_trash)
    editor.add_inputs((first, second))
    buttons = editor.findChildren(QToolButton, "sourceClipTrashButton")
    assert len(buttons) == 2
    assert buttons[1].accessibleName() == "Move second.mov to Trash"

    messages: list[str] = []
    editor.message.connect(messages.append)
    buttons[1].click()

    assert moved == [str(second)]
    assert editor.input_paths() == (first,)
    assert editor.inputs.item(0).text() == ""
    assert messages == ["Moved source clip to Trash: second.mov"]


def test_long_source_filename_is_elided_and_trash_control_is_compact(qt_app: QApplication, tmp_path: Path) -> None:
    """Long names elide in the row and the Trash control stays compact."""

    path = tmp_path / "a-very-long-source-clip-filename\nthat-needs-elision-in-the-row.mov"
    editor = JobEditor(ApplicationSettings(), trash_mover=lambda _path: True)
    editor.resize(1200, 500)
    editor.add_inputs((path,))
    editor.show()
    qt_app.processEvents()
    filename = editor.findChild(QLabel, "sourceClipFilename")
    trash_button = editor.findChild(QToolButton, "sourceClipTrashButton")

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
    assert trash_button is not None
    assert trash_button.width() == 20
    assert trash_button.iconSize().width() == 10
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
