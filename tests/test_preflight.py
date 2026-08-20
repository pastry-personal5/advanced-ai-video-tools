"""Behavioral tests for deterministic, dependency-injected preflight."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from ai_video_tools.core.models import (
    AudioStream,
    ConcatStrategy,
    IssueCode,
    IssueSeverity,
    JobRequest,
    MediaProbe,
    OtherStream,
    Rational,
    ToolInfo,
    Toolchain,
    VideoStream,
)
from ai_video_tools.services.preflight import PreflightService, aspect_width
from ai_video_tools.system.platform import PlatformInfo
from ai_video_tools.system.tools import ToolDiscovery
from ai_video_tools.video.probe import MediaProber


class FakeDiscovery(ToolDiscovery):
    """Return a frozen toolchain without launching host dependencies."""

    def __init__(self, toolchain: Toolchain) -> None:
        super().__init__()
        self.toolchain = toolchain

    def discover(self, _overrides: object) -> Toolchain:
        """Satisfy the discovery boundary."""

        return self.toolchain


class FakeProber(MediaProber):
    """Look up media facts by input path."""

    def __init__(self, probes: dict[Path, MediaProbe]) -> None:
        self.probes = probes

    def probe(self, path: Path) -> MediaProbe:
        """Return the prepared probe result."""

        return self.probes[path]


def _video(**changes: object) -> VideoStream:
    values: dict[str, object] = {
        "index": 0,
        "codec_name": "h264",
        "width": 1920,
        "height": 1080,
        "pixel_format": "yuv420p",
        "sample_aspect_ratio": Rational(1, 1),
        "real_frame_rate": Rational(30000, 1001),
        "average_frame_rate": Rational(30000, 1001),
        "time_base": Rational(1, 30000),
        "duration": Decimal("1"),
        "color_space": "bt709",
        "color_transfer": "bt709",
        "color_primaries": "bt709",
        "color_range": "tv",
        "rotation": 0,
        "has_hdr_metadata": False,
    }
    values.update(changes)
    return VideoStream(**values)  # type: ignore[arg-type]


def _probe(path: Path, **changes: object) -> MediaProbe:
    values: dict[str, object] = {
        "path": path,
        "duration": Decimal("1"),
        "video_streams": (_video(),),
        "audio_streams": (),
        "other_streams": (),
        "chapter_count": 0,
    }
    values.update(changes)
    return MediaProbe(**values)  # type: ignore[arg-type]


def _service(
    tmp_path: Path,
    probes: dict[Path, MediaProbe],
    *,
    free_bytes: int = 10**15,
) -> PreflightService:
    executable = ToolInfo(tmp_path / "tool", "version 1")
    toolchain = Toolchain(executable, executable, executable, tmp_path / "models")
    prober = FakeProber(probes)
    return PreflightService(
        tool_discovery=FakeDiscovery(toolchain),
        platform_provider=lambda: PlatformInfo("Darwin", "arm64", "26.5.2"),
        prober_factory=lambda _tools: prober,
        clock=lambda: datetime(
            2026,
            8,
            21,
            14,
            30,
            52,
            123456,
            tzinfo=timezone(timedelta(hours=9)),
        ),
        workspace_root_provider=lambda: tmp_path,
        free_space_provider=lambda _path: free_bytes,
    )


def _input(tmp_path: Path, name: str = "clip.mp4") -> Path:
    path = tmp_path / name
    path.write_bytes(b"small fixture stand-in")
    return path


def test_ready_plan_freezes_name_dimensions_rate_and_scale(tmp_path: Path) -> None:
    """A valid SDR clip produces all core execution decisions."""

    source = _input(tmp_path)
    service = _service(tmp_path, {source: _probe(source)})

    report = service.run(JobRequest((source,), tmp_path))

    assert report.ready
    assert report.plan is not None
    assert report.plan.output_path.name == ("ai-video-20260821-143052-123456+0900.mp4")
    assert (report.plan.output_width, report.plan.output_height) == (3840, 2160)
    assert report.plan.output_frame_rate == Rational(30000, 1001)
    assert report.plan.ai_scale == 2
    assert report.plan.concat_strategy is ConcatStrategy.STREAM_COPY
    assert report.plan.required_free_bytes >= report.plan.estimated_peak_bytes
    service.registry.release(report.plan.output_path)


def test_aspect_width_uses_sample_aspect_ratio_and_even_rounding() -> None:
    """Display aspect, not coded aspect alone, determines final width."""

    video = _video(width=720, height=576, sample_aspect_ratio=Rational(16, 15))
    assert aspect_width(video, 2160) == 2880


@pytest.mark.parametrize(
    ("video", "code"),
    [
        (_video(color_transfer="smpte2084"), IssueCode.UNSUPPORTED_HDR),
        (_video(rotation=90), IssueCode.UNSUPPORTED_ROTATION),
    ],
)
def test_hdr_and_rotation_are_hard_failures(tmp_path: Path, video: VideoStream, code: IssueCode) -> None:
    """Unsupported image interpretation is rejected, never normalized silently."""

    source = _input(tmp_path)
    report = _service(tmp_path, {source: _probe(source, video_streams=(video,))}).run(JobRequest((source,), tmp_path))

    assert not report.ready
    assert code in {issue.code for issue in report.issues}


def test_ambiguous_color_requires_explicit_acknowledgement(tmp_path: Path) -> None:
    """Missing tags block by default and become a warning only by consent."""

    source = _input(tmp_path)
    ambiguous = _probe(source, video_streams=(_video(color_primaries=None),))
    service = _service(tmp_path, {source: ambiguous})

    rejected = service.run(JobRequest((source,), tmp_path))
    accepted = service.run(JobRequest((source,), tmp_path, assume_bt709=True))

    assert not rejected.ready
    assert accepted.ready
    color_issue = next(issue for issue in accepted.issues if issue.code is IssueCode.AMBIGUOUS_COLOR)
    assert color_issue.severity is IssueSeverity.WARNING
    assert accepted.plan is not None
    service.registry.release(accepted.plan.output_path)


def test_secondary_streams_require_acknowledgement(tmp_path: Path) -> None:
    """Unsupported streams are inventoried before an intentional drop."""

    source = _input(tmp_path)
    audio = AudioStream(1, "aac", 48000, 2, "stereo", Decimal("1"))
    media = _probe(
        source,
        audio_streams=(audio, audio),
        other_streams=(OtherStream(3, "subtitle", "mov_text"),),
        chapter_count=1,
    )
    service = _service(tmp_path, {source: media})

    rejected = service.run(JobRequest((source,), tmp_path))
    accepted = service.run(JobRequest((source,), tmp_path, acknowledge_dropped_streams=True))

    assert not rejected.ready
    assert accepted.ready
    issue = next(item for item in accepted.issues if item.code is IssueCode.STREAM_ACKNOWLEDGEMENT)
    assert "extra audio" in issue.message
    assert "subtitle:3" in issue.message
    assert accepted.plan is not None
    assert accepted.plan.output_audio_layout == "stereo"
    service.registry.release(accepted.plan.output_path)


def test_vfr_uses_exact_average_rate_and_forces_normalization(tmp_path: Path) -> None:
    """VFR timing chooses avg_frame_rate exactly and visibly normalizes."""

    source = _input(tmp_path)
    video = _video(
        real_frame_rate=Rational(30, 1),
        average_frame_rate=Rational(30000, 1001),
    )
    service = _service(tmp_path, {source: _probe(source, video_streams=(video,))})

    report = service.run(JobRequest((source,), tmp_path))

    assert report.ready
    assert report.plan is not None
    assert report.plan.output_frame_rate == Rational(30000, 1001)
    assert any("frame timing" in reason for reason in report.plan.normalization_reasons)
    assert report.plan.concat_strategy is ConcatStrategy.NORMALIZE
    service.registry.release(report.plan.output_path)


def test_disk_estimate_requires_twenty_percent_margin(tmp_path: Path) -> None:
    """Insufficient cache volume capacity blocks work before extraction."""

    source = _input(tmp_path)
    report = _service(tmp_path, {source: _probe(source)}, free_bytes=1).run(JobRequest((source,), tmp_path))

    assert not report.ready
    assert IssueCode.INSUFFICIENT_DISK in {issue.code for issue in report.issues}


def test_explicit_output_cannot_alias_an_input(tmp_path: Path) -> None:
    """Overwrite mode never permits destruction of a source clip."""

    source = _input(tmp_path)
    report = _service(tmp_path, {source: _probe(source)}).run(JobRequest((source,), tmp_path, explicit_output_path=source))

    assert not report.ready
    assert IssueCode.INVALID_OUTPUT in {issue.code for issue in report.issues}
