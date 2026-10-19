"""GUI coverage for authoritative queued-job plan disclosure."""

# Pytest injects fixtures through same-named function parameters.
# pylint: disable=redefined-outer-name

from __future__ import annotations

import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication  # noqa: E402  # pylint: disable=wrong-import-position,no-name-in-module
from PySide6.QtWidgets import QApplication  # noqa: E402  # pylint: disable=wrong-import-position,no-name-in-module

from advanced_ai_video_tools.core.models import ColorMatrix, ColorProfile, ConcatStrategy, JobPlan, JobRequest, JobState, MediaProbe, ProcessingPipeline, Rational, UpscaleBackend, UpscalePassPlan, VideoStream  # noqa: E402  # pylint: disable=wrong-import-position
from advanced_ai_video_tools.gui.jobs import JobListModel, QueueSnapshotBridge  # noqa: E402  # pylint: disable=wrong-import-position
from advanced_ai_video_tools.gui.window import MainWindow  # noqa: E402  # pylint: disable=wrong-import-position
from advanced_ai_video_tools.services.queue import QueueJobSnapshot  # noqa: E402  # pylint: disable=wrong-import-position
from advanced_ai_video_tools.system.settings import ApplicationSettings  # noqa: E402  # pylint: disable=wrong-import-position


@pytest.fixture(scope="module")
def qt_app() -> QApplication:
    """Provide one offscreen Qt application."""

    existing = QCoreApplication.instance()
    if existing is not None and not isinstance(existing, QApplication):
        raise RuntimeError("a non-GUI Qt application already exists")
    return existing or QApplication(["ai-video-tools-plan-summary-tests"])


class EmptyQueue:
    """Minimal idle queue view for the window model."""

    def snapshots(self) -> tuple[QueueJobSnapshot, ...]:
        """Return an empty initial queue."""

        return ()

    def cancel(self, _job_id: str) -> bool:
        """Report that an idle queue has nothing to cancel."""

        return False

    def move(self, _job_id: str, _position: int) -> None:
        """Accept the unused queue-view operation."""

        return None

    def wait(self, _job_id: str, _timeout: float | None = None) -> None:
        """Return no terminal outcome for an idle queue."""

        return None


def test_running_job_writes_authoritative_upscale_summary_to_global_messages(qt_app: QApplication, tmp_path: Path) -> None:
    """The RUNNING transition shows source, target, stages, and model names."""

    created = datetime(2026, 10, 19, tzinfo=timezone.utc)
    source = tmp_path / "source.mov"
    request = JobRequest((source,), tmp_path, explicit_output_path=tmp_path / "output.mp4", created_at=created, pipeline=ProcessingPipeline.TWO_X_THREE_X_RESIZE)
    video = VideoStream(0, "h264", 1920, 1080, "yuv420p", Rational(1, 1), Rational(24, 1), Rational(24, 1), Rational(1, 1000), Decimal("1"), "bt709", "bt709", "bt709", "tv", 0, False)
    probe = MediaProbe(source, Decimal("1"), (video,), (), ())
    runner = tmp_path / "spandrel-runner"
    passes = (
        UpscalePassPlan(1, UpscaleBackend.SPANDREL, 2, 1920, 1080, 3840, 2160, runner, tmp_path / "RealPLKSR_x2.pth"),
        UpscalePassPlan(2, UpscaleBackend.SPANDREL, 3, 3840, 2160, 11520, 6480, runner, tmp_path / "DAT_x3.safetensors"),
    )
    plan = JobPlan(created, tmp_path / "output.mp4", False, (probe,), Rational(24, 1), 7680, 4320, 6, ConcatStrategy.NORMALIZE, None, (), 100, 120, ColorProfile(ColorMatrix.BT709, "bt709", "bt709"), pipeline=ProcessingPipeline.TWO_X_THREE_X_RESIZE, upscale_passes=passes)
    validating = QueueJobSnapshot("job", request, JobState.VALIDATING, None, None, 1, plan)
    running = QueueJobSnapshot("job", request, JobState.RUNNING, None, None, 2, plan)
    model = JobListModel(EmptyQueue(), QueueSnapshotBridge())  # type: ignore[arg-type]
    window = MainWindow(model, ApplicationSettings())

    window._handle_queue_snapshot(validating)  # pylint: disable=protected-access
    window._handle_queue_snapshot(running)  # pylint: disable=protected-access
    qt_app.processEvents()

    messages = window.global_messages.toPlainText()
    assert "Original 1920×1080; target 7680×4320; pipeline 2× → 3× → resize." in messages
    assert "Stage 1: Normalize and concatenate — FFmpeg." in messages
    assert "Stage 3: AI upscale 2× — RealPLKSR_x2.pth (Spandrel)." in messages
    assert "Stage 4: AI upscale 3× — DAT_x3.safetensors (Spandrel)." in messages
    assert "Stage 5: Resize to 7680×4320 and encode — FFmpeg." in messages
    window.close()
