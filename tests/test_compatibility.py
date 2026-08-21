"""Tests for typed concat compatibility decisions."""

from decimal import Decimal
from pathlib import Path

from ai_video_tools.core.models import AudioStream, ConcatStrategy, MediaProbe, Rational, VideoStream
from ai_video_tools.video.compatibility import CompatibilityReason, analyze_clip_compatibility, effective_frame_rate, frame_rates_equivalent


def _video(**changes: object) -> VideoStream:
    values: dict[str, object] = {"index": 0, "codec_name": "h264", "width": 1920, "height": 1080, "pixel_format": "yuv420p", "sample_aspect_ratio": Rational(1, 1), "real_frame_rate": Rational(30000, 1001), "average_frame_rate": Rational(30000, 1001), "time_base": Rational(1, 30000), "duration": Decimal("1"), "color_space": "bt709", "color_transfer": "bt709", "color_primaries": "bt709", "color_range": "tv", "rotation": 0, "has_hdr_metadata": False}
    values.update(changes)
    return VideoStream(**values)  # type: ignore[arg-type]


def _audio(**changes: object) -> AudioStream:
    values: dict[str, object] = {"index": 1, "codec_name": "aac", "sample_rate": 48000, "channels": 2, "channel_layout": "stereo", "duration": Decimal("1"), "time_base": Rational(1, 48000)}
    values.update(changes)
    return AudioStream(**values)  # type: ignore[arg-type]


def _probe(path: str, *, video: VideoStream | None = None, audio: AudioStream | None = None) -> MediaProbe:
    return MediaProbe(Path(path), Decimal("1"), (video or _video(),), (audio,) if audio else (), ())


def test_identical_video_and_audio_streams_are_stream_copy_safe() -> None:
    """Every property relevant to concat matches exactly."""

    report = analyze_clip_compatibility((_probe("one.mp4", audio=_audio()), _probe("two.mp4", audio=_audio())), Rational(30000, 1001), "stereo")

    assert report.strategy is ConcatStrategy.STREAM_COPY
    assert report.stream_copy_safe
    assert not report.findings


def test_incompatible_properties_return_typed_normalization_reasons() -> None:
    """Timing, image, range, and missing audio decisions remain distinguishable."""

    first = _probe("one.mp4", audio=_audio())
    second_video = _video(width=1280, height=720, real_frame_rate=Rational(30, 1), color_range="pc")
    report = analyze_clip_compatibility((first, _probe("two.mp4", video=second_video)), Rational(30000, 1001), "stereo")
    reasons = {finding.reason for finding in report.findings if finding.path.name == "two.mp4"}

    assert report.strategy is ConcatStrategy.NORMALIZE
    assert CompatibilityReason.VIDEO_DIMENSIONS in reasons
    assert CompatibilityReason.VARIABLE_FRAME_RATE in reasons
    assert CompatibilityReason.COLOR_RANGE in reasons
    assert CompatibilityReason.AUDIO_MISSING in reasons


def test_missing_time_bases_force_normalization() -> None:
    """Unknown timing cannot be declared safe for concat stream copy."""

    report = analyze_clip_compatibility((_probe("one.mp4", video=_video(time_base=None), audio=_audio(time_base=None)),), Rational(30000, 1001), "stereo")
    reasons = {finding.reason for finding in report.findings}

    assert CompatibilityReason.VIDEO_TIME_BASE in reasons
    assert CompatibilityReason.AUDIO_TIME_BASE in reasons


def test_quantized_cfr_uses_nominal_rate_and_time_base_tolerance() -> None:
    """Container tick rounding does not turn nominal 16 fps into synthetic VFR."""

    video = _video(real_frame_rate=Rational(16, 1), average_frame_rate=Rational(48600, 3037), time_base=Rational(1, 600))

    assert effective_frame_rate(video) == (Rational(16, 1), False)
    assert frame_rates_equivalent(Rational(18227, 1139), Rational(16, 1), Rational(1, 1000))
    assert not frame_rates_equivalent(Rational(30000, 1001), Rational(30, 1), Rational(1, 30000))


def test_matching_smpte170m_matrix_is_stream_copy_compatible() -> None:
    """SMPTE 170M is valid and does not force conversion to BT.709."""

    report = analyze_clip_compatibility((_probe("smpte170m.mov", video=_video(color_space="smpte170m")),), Rational(30000, 1001), None)

    assert report.strategy is ConcatStrategy.STREAM_COPY
    assert not any(finding.reason is CompatibilityReason.COLOR_TAGS for finding in report.findings)


def test_matrix_different_from_first_clip_is_not_stream_copy_compatible() -> None:
    """Defense in depth detects a mixed matrix even though preflight rejects it."""

    report = analyze_clip_compatibility((_probe("first.mov", video=_video(color_space="smpte170m")), _probe("second.mov", video=_video(color_space="bt709"))), Rational(30000, 1001), None)

    assert report.strategy is ConcatStrategy.NORMALIZE
    assert any(finding.reason is CompatibilityReason.COLOR_TAGS and "differs from the first clip" in finding.message for finding in report.findings)


def test_missing_transfer_and_primaries_do_not_force_normalization() -> None:
    """Optional absent tags are ignored when concat properties otherwise match."""

    report = analyze_clip_compatibility((_probe("first.mov"), _probe("second.mov", video=_video(color_transfer=None, color_primaries=None))), Rational(30000, 1001), None)

    assert report.strategy is ConcatStrategy.STREAM_COPY
    assert not any(finding.reason is CompatibilityReason.COLOR_TAGS for finding in report.findings)


def test_conflicting_explicit_optional_tags_are_found_when_first_is_missing() -> None:
    """A missing first value cannot hide a contradiction between later clips."""

    report = analyze_clip_compatibility(
        (
            _probe("first.mov", video=_video(color_transfer=None)),
            _probe("second.mov"),
            _probe("third.mov", video=_video(color_transfer="smpte170m")),
        ),
        Rational(30000, 1001),
        None,
    )

    assert report.strategy is ConcatStrategy.NORMALIZE
    assert any(finding.reason is CompatibilityReason.COLOR_TAGS and finding.path.name == "third.mov" for finding in report.findings)


def test_nonzero_stream_timestamps_force_normalization() -> None:
    """Concat receives zero-based streams instead of inheriting source offsets."""

    report = analyze_clip_compatibility((_probe("offset.mp4", video=_video(start_time=Decimal("0.25")), audio=_audio(start_time=Decimal("0.25"))),), Rational(30000, 1001), "stereo")

    assert CompatibilityReason.TIMESTAMP_ORIGIN in {finding.reason for finding in report.findings}
