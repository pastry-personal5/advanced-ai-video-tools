"""Headless tests for job editing, asynchronous preflight, and safe submission."""

# Pytest injects fixtures through same-named function parameters.
# pylint: disable=redefined-outer-name

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QMimeData, QObject, QThread, QUrl, Signal  # noqa: E402  # pylint: disable=wrong-import-position,no-name-in-module
from PySide6.QtWidgets import QApplication  # noqa: E402  # pylint: disable=wrong-import-position,no-name-in-module

from ai_video_tools.core.models import ColorMatrix, ColorProfile, ConcatStrategy, IssueCode, IssueSeverity, JobPlan, JobRequest, OverwriteMode, PipelineStage, PreflightIssue, PreflightReport, ProgressEvent, Rational, ToolOverrides  # noqa: E402  # pylint: disable=wrong-import-position
from ai_video_tools.gui.editor import JobEditor  # noqa: E402  # pylint: disable=wrong-import-position
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
    editor.add_inputs(paths)
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


def test_editor_drop_boundary_accepts_local_files_and_rejects_remote_urls(qt_app: QApplication, tmp_path: Path) -> None:
    """File-manager drops accept local files only and preserve URL safety."""

    del qt_app
    first = tmp_path / "first.mov"
    second = tmp_path / "second.mov"
    first.touch()
    second.touch()
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
    store = SettingsStore(tmp_path / "settings.json")
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
    document = json.loads(store.path.read_text(encoding="utf-8"))
    assert "acknowledge_dropped_streams" not in document
    assert "acknowledge_dropped_streams" not in document["processing"]


def test_submission_controller_refuses_unrelated_error_even_if_provider_accepts(qt_app: QApplication, tmp_path: Path) -> None:
    """An injected or faulty decision provider cannot override media safety errors."""

    preview = FakePreview()
    queue = RecordingQueue()
    controller = JobSubmissionController(queue, preview, ApplicationSettings(), SettingsStore(tmp_path / "settings.json"), decision_provider=lambda _parent, _report: PreflightDecision(True, True))  # type: ignore[arg-type]
    request = _request(tmp_path)
    controller.start(request)
    issue = PreflightIssue(IssueSeverity.ERROR, IssueCode.UNSUPPORTED_HDR, "HDR is unsupported.", request.inputs[0])
    preview.finished.emit(request, PreflightReport((issue,), None, None))
    qt_app.processEvents()

    assert not queue.requests
