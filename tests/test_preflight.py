"""Behavioral tests for deterministic, dependency-injected preflight."""

import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from advanced_ai_video_tools.core.models import (
    AudioStream,
    ColorMatrix,
    ColorProfile,
    ConcatStrategy,
    IssueCode,
    IssueSeverity,
    JobRequest,
    MediaProbe,
    OtherStream,
    OverwriteMode,
    PipelineStage,
    ProgressEvent,
    Rational,
    ToolInfo,
    Toolchain,
    VideoStream,
)
from advanced_ai_video_tools.services.preflight import PreflightService, aspect_width
from advanced_ai_video_tools.storage.naming import automatic_output_basename
from advanced_ai_video_tools.system.platform import PlatformInfo
from advanced_ai_video_tools.system.tools import ToolDiscovery
from advanced_ai_video_tools.video.probe import MediaProber


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
    assert re.fullmatch(r"ai-video-20260821-143052-[0-9a-f]{32}\.mp4", report.plan.output_path.name)
    assert (report.plan.output_width, report.plan.output_height) == (3840, 2160)
    assert report.plan.output_frame_rate == Rational(30000, 1001)
    assert report.plan.ai_scale == 2
    assert report.plan.model_name == "realesrgan-x4plus"
    assert report.plan.overwrite_mode is OverwriteMode.REPLACE
    assert report.plan.output_color_profile == ColorProfile(ColorMatrix.BT709, "bt709", "bt709")
    assert report.plan.concat_strategy is ConcatStrategy.STREAM_COPY
    assert report.plan.required_free_bytes >= report.plan.estimated_peak_bytes
    service.registry.release(report.plan.output_path)


def test_preflight_preserves_queue_frozen_creation_identity(tmp_path: Path) -> None:
    """A delayed queued job keeps its submission timestamp and UUIDv7 basename."""

    source = _input(tmp_path)
    service = _service(tmp_path, {source: _probe(source)})
    created = datetime(2026, 7, 4, 9, 8, 7, 654321, tzinfo=timezone.utc)
    basename = automatic_output_basename(created)

    report = service.run(JobRequest((source,), tmp_path, created_at=created, generated_output_basename=basename))

    assert report.ready
    assert report.plan is not None
    assert report.plan.created_at == created
    assert report.plan.output_path.name == basename
    service.registry.release(report.plan.output_path)


def test_frozen_generated_destination_that_appears_before_start_is_rejected(tmp_path: Path) -> None:
    """An external collision cannot make a delayed generated job overwrite a file."""

    source = _input(tmp_path)
    service = _service(tmp_path, {source: _probe(source)})
    created = datetime(2026, 7, 4, 9, 8, 7, 654321, tzinfo=timezone.utc)
    basename = automatic_output_basename(created)
    (tmp_path / basename).touch()

    report = service.run(JobRequest((source,), tmp_path, created_at=created, generated_output_basename=basename))

    assert not report.ready
    assert report.plan is None
    assert any(issue.code is IssueCode.INVALID_OUTPUT and "no longer available" in issue.message for issue in report.issues)


def test_preflight_reports_measured_validation_and_probe_progress(tmp_path: Path) -> None:
    """Frontends can render validation and per-input probe progress."""

    first = _input(tmp_path, "first.mp4")
    second = _input(tmp_path, "second.mp4")
    service = _service(tmp_path, {first: _probe(first), second: _probe(second)})
    events: list[ProgressEvent] = []

    report = service.run(JobRequest((first, second), tmp_path), progress=events.append)

    assert report.ready and report.plan is not None
    assert [(event.stage, event.completed, event.total) for event in events] == [
        (PipelineStage.VALIDATE, 0, 1),
        (PipelineStage.VALIDATE, 1, 1),
        (PipelineStage.PROBE, 0, 2),
        (PipelineStage.PROBE, 1, 2),
        (PipelineStage.PROBE, 2, 2),
    ]
    service.registry.release(report.plan.output_path)


def test_aspect_width_uses_sample_aspect_ratio_and_even_rounding() -> None:
    """Display aspect, not coded aspect alone, determines final width."""

    video = _video(width=720, height=576, sample_aspect_ratio=Rational(16, 15))
    assert aspect_width(video, 2160) == 2880


def test_nonpositive_target_height_is_a_validation_issue_not_an_exception(tmp_path: Path) -> None:
    """Strict scale policy remains behind the user-facing request validator."""

    source = _input(tmp_path)
    report = _service(tmp_path, {source: _probe(source)}).run(JobRequest((source,), tmp_path, target_height=0))

    assert not report.ready
    assert any(issue.code is IssueCode.INVALID_OUTPUT and "Target height" in issue.message for issue in report.issues)


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


def test_missing_transfer_and_primaries_are_accepted_without_defaults(tmp_path: Path) -> None:
    """Optional signaling can remain absent without becoming BT.709."""

    source = _input(tmp_path)
    media = _probe(source, video_streams=(_video(color_transfer=None, color_primaries=None),))
    service = _service(tmp_path, {source: media})

    report = service.run(JobRequest((source,), tmp_path))

    assert report.ready and report.plan is not None
    assert report.plan.output_color_profile == ColorProfile(ColorMatrix.BT709, None, None)
    service.registry.release(report.plan.output_path)


@pytest.mark.parametrize("missing_field", ["color_space", "color_range"])
def test_missing_matrix_or_range_is_rejected(tmp_path: Path, missing_field: str) -> None:
    """Matrix and range remain mandatory because sample conversion needs them."""

    source = _input(tmp_path)
    media = _probe(source, video_streams=(_video(**{missing_field: None}),))
    report = _service(tmp_path, {source: media}).run(JobRequest((source,), tmp_path))

    assert not report.ready
    color_issue = next(issue for issue in report.issues if issue.code is IssueCode.AMBIGUOUS_COLOR)
    assert color_issue.severity is IssueSeverity.ERROR
    assert "matrix and range must be explicit" in color_issue.message


def test_first_clip_smpte170m_matrix_is_preserved_as_output_profile(tmp_path: Path) -> None:
    """An explicit SMPTE 170M first clip freezes SMPTE 170M output."""

    source = _input(tmp_path)
    smpte170m = _probe(source, video_streams=(_video(color_space="smpte170m"),))
    service = _service(tmp_path, {source: smpte170m})

    report = service.run(JobRequest((source,), tmp_path))

    assert report.ready and report.plan is not None
    assert report.plan.output_color_profile == ColorProfile(ColorMatrix.SMPTE170M, "bt709", "bt709")
    assert report.plan.concat_strategy is ConcatStrategy.STREAM_COPY
    service.registry.release(report.plan.output_path)


def test_color_profile_different_from_first_clip_is_rejected(tmp_path: Path) -> None:
    """Mixed BT.709 and SMPTE 170M jobs never enter conversion."""

    first = _input(tmp_path, "first.mov")
    second = _input(tmp_path, "second.mov")
    probes = {first: _probe(first, video_streams=(_video(color_space="smpte170m"),)), second: _probe(second)}

    report = _service(tmp_path, probes).run(JobRequest((first, second), tmp_path))

    assert not report.ready
    issue = next(issue for issue in report.issues if issue.code is IssueCode.UNSUPPORTED_COLOR)
    assert "explicitly conflicts with another clip" in issue.message


def test_explicit_transfer_conflict_is_rejected_but_missing_value_is_ignored(tmp_path: Path) -> None:
    """Only two contradictory declared optional tags create a conflict."""

    first = _input(tmp_path, "first.mov")
    missing = _input(tmp_path, "missing.mov")
    conflicting = _input(tmp_path, "conflicting.mov")
    conflicting_again = _input(tmp_path, "conflicting-again.mov")
    accepted_probes = {first: _probe(first), missing: _probe(missing, video_streams=(_video(color_transfer=None),))}
    accepted_service = _service(tmp_path, accepted_probes)

    accepted = accepted_service.run(JobRequest((first, missing), tmp_path))
    rejected_probes = {
        first: _probe(first, video_streams=(_video(color_transfer=None),)),
        conflicting: _probe(conflicting),
        conflicting_again: _probe(conflicting_again, video_streams=(_video(color_transfer="smpte170m"),)),
    }
    rejected = _service(tmp_path, rejected_probes).run(JobRequest((first, conflicting, conflicting_again), tmp_path))

    assert accepted.ready and accepted.plan is not None
    assert not rejected.ready
    assert any(issue.code is IssueCode.UNSUPPORTED_COLOR and "explicitly conflicts" in issue.message for issue in rejected.issues)
    accepted_service.registry.release(accepted.plan.output_path)


def test_other_explicit_sdr_matrices_remain_unsupported(tmp_path: Path) -> None:
    """The design expansion is limited to SMPTE 170M rather than arbitrary matrices."""

    source = _input(tmp_path)
    report = _service(tmp_path, {source: _probe(source, video_streams=(_video(color_space="fcc"),))}).run(JobRequest((source,), tmp_path))

    assert not report.ready
    assert any(issue.code is IssueCode.UNSUPPORTED_COLOR for issue in report.issues)


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
    rejected_issue = next(item for item in rejected.issues if item.code is IssueCode.STREAM_ACKNOWLEDGEMENT)
    assert rejected_issue.acknowledgement_key is not None
    bound = service.run(JobRequest((source,), tmp_path, acknowledge_dropped_streams=True, acknowledged_stream_keys=(rejected_issue.acknowledgement_key,)))

    assert not rejected.ready
    assert accepted.ready
    assert bound.ready
    issue = next(item for item in accepted.issues if item.code is IssueCode.STREAM_ACKNOWLEDGEMENT)
    assert "extra audio" in issue.message
    assert "subtitle:3" in issue.message
    assert accepted.plan is not None
    assert accepted.plan.output_audio_layout == "stereo"
    service.registry.release(accepted.plan.output_path)
    assert bound.plan is not None
    service.registry.release(bound.plan.output_path)

    changed_media = _probe(source, audio_streams=(audio, audio), other_streams=(OtherStream(3, "subtitle", "mov_text"),), chapter_count=2)
    changed = _service(tmp_path, {source: changed_media}).run(JobRequest((source,), tmp_path, acknowledge_dropped_streams=True, acknowledged_stream_keys=(rejected_issue.acknowledgement_key,)))
    assert not changed.ready
    changed_issue = next(item for item in changed.issues if item.code is IssueCode.STREAM_ACKNOWLEDGEMENT)
    assert changed_issue.severity is IssueSeverity.ERROR
    assert "inventory changed" in changed_issue.message


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


def test_quantized_sixteen_fps_is_recognized_as_cfr(tmp_path: Path) -> None:
    """Alternating source ticks preserve the nominal 16/1 rate."""

    source = _input(tmp_path)
    video = _video(real_frame_rate=Rational(16, 1), average_frame_rate=Rational(48600, 3037), time_base=Rational(1, 600))
    service = _service(tmp_path, {source: _probe(source, video_streams=(video,))})

    report = service.run(JobRequest((source,), tmp_path))

    assert report.ready and report.plan is not None
    assert report.plan.output_frame_rate == Rational(16, 1)
    assert report.plan.concat_strategy is ConcatStrategy.STREAM_COPY
    assert not any("frame timing" in reason for reason in report.plan.normalization_reasons)
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
