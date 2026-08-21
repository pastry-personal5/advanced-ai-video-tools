"""Typed concat compatibility analysis for probed clips."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from fractions import Fraction
from pathlib import Path

from ai_video_tools.core.models import AudioStream, ConcatStrategy, MediaProbe, Rational, VideoStream

AUDIO_DURATION_TOLERANCE = Decimal("0.05")


class CompatibilityReason(str, Enum):
    """Stable reasons why lossless concat stream copy is unsafe."""

    VIDEO_CODEC = "video_codec"
    VIDEO_DIMENSIONS = "video_dimensions"
    PIXEL_FORMAT = "pixel_format"
    SAMPLE_ASPECT_RATIO = "sample_aspect_ratio"
    VIDEO_TIME_BASE = "video_time_base"
    FRAME_RATE = "frame_rate"
    VARIABLE_FRAME_RATE = "variable_frame_rate"
    COLOR_TAGS = "color_tags"
    COLOR_RANGE = "color_range"
    AUDIO_MISSING = "audio_missing"
    AUDIO_CODEC = "audio_codec"
    AUDIO_SAMPLE_RATE = "audio_sample_rate"
    AUDIO_CHANNELS = "audio_channels"
    AUDIO_LAYOUT = "audio_layout"
    AUDIO_TIME_BASE = "audio_time_base"
    AUDIO_DURATION = "audio_duration"
    TIMESTAMP_ORIGIN = "timestamp_origin"


@dataclass(frozen=True)
class CompatibilityFinding:
    """One typed normalization requirement associated with an input clip."""

    path: Path
    reason: CompatibilityReason
    message: str


@dataclass(frozen=True)
class CompatibilityReport:
    """Concat strategy and the complete set of reasons behind it."""

    strategy: ConcatStrategy
    findings: tuple[CompatibilityFinding, ...]

    @property
    def stream_copy_safe(self) -> bool:
        """Whether source clips can enter concat without normalization."""

        return self.strategy is ConcatStrategy.STREAM_COPY


@dataclass(frozen=True)
class FrameTimingAssessment:
    """Auditable comparison between probed timing and the frozen job CFR."""

    expected_rate: Rational
    effective_rate: Rational | None
    real_rate: Rational | None
    average_rate: Rational | None
    time_base: Rational | None
    variable: bool
    period_delta: Fraction | None
    tolerance: Fraction | None
    equivalent: bool

    @property
    def accepted(self) -> bool:
        """Whether the stream is CFR and equivalent within timestamp precision."""

        return not self.variable and self.equivalent

    def diagnostic(self) -> str:
        """Render stable values suitable for retained-workspace errors."""

        def rate_text(value: Rational | None) -> str:
            return str(value) if value is not None else "missing"

        delta_text = f"{self.period_delta}s" if self.period_delta is not None else "unavailable"
        tolerance_text = f"<{self.tolerance}s" if self.tolerance is not None else "exact-only"
        return f"expected={self.expected_rate}, effective={rate_text(self.effective_rate)}, r_frame_rate={rate_text(self.real_rate)}, avg_frame_rate={rate_text(self.average_rate)}, time_base={rate_text(self.time_base)}, variable={str(self.variable).lower()}, frame_period_delta={delta_text}, tolerance={tolerance_text}"


def effective_frame_rate(video: VideoStream) -> tuple[Rational | None, bool]:
    """Return the nominal CFR unless rate disagreement exceeds one timestamp tick."""

    real = video.real_frame_rate
    average = video.average_frame_rate
    if real is not None and average is not None:
        return (real, False) if frame_rates_equivalent(real, average, video.time_base) else (average, True)
    if average is not None:
        return average, True
    return real, False


def frame_rates_equivalent(actual: Rational, expected: Rational, time_base: Rational | None) -> bool:
    """Accept rate fractions whose frame periods differ by less than one stream tick."""

    if actual == expected:
        return True
    if time_base is None or not time_base.positive or not actual.positive or not expected.positive:
        return False
    actual_period = Fraction(actual.denominator, actual.numerator)
    expected_period = Fraction(expected.denominator, expected.numerator)
    return abs(actual_period - expected_period) < time_base.as_fraction()


def assess_frame_timing(video: VideoStream, expected: Rational) -> FrameTimingAssessment:
    """Return the complete time-base-aware decision used by verifiers."""

    effective, variable = effective_frame_rate(video)
    period_delta = None
    if effective is not None and effective.positive and expected.positive:
        period_delta = abs(Fraction(effective.denominator, effective.numerator) - Fraction(expected.denominator, expected.numerator))
    tolerance = video.time_base.as_fraction() if video.time_base is not None and video.time_base.positive else None
    equivalent = effective is not None and frame_rates_equivalent(effective, expected, video.time_base)
    return FrameTimingAssessment(expected, effective, video.real_frame_rate, video.average_frame_rate, video.time_base, variable, period_delta, tolerance, equivalent)


def _finding(path: Path, reason: CompatibilityReason, detail: str) -> CompatibilityFinding:
    return CompatibilityFinding(path, reason, f"{path.name}: {detail}")


def _compare_video(path: Path, video: VideoStream, baseline: VideoStream, output_rate: Rational, optional_reference: tuple[str | None, str | None]) -> list[CompatibilityFinding]:
    findings: list[CompatibilityFinding] = []
    comparisons = (
        (video.codec_name in {"", "unknown"} or video.codec_name != baseline.codec_name, CompatibilityReason.VIDEO_CODEC, "video codec is missing or differs"),
        ((video.width, video.height) != (baseline.width, baseline.height), CompatibilityReason.VIDEO_DIMENSIONS, "video dimensions differ"),
        (video.pixel_format is None or video.pixel_format != baseline.pixel_format, CompatibilityReason.PIXEL_FORMAT, "pixel format is missing or differs"),
        (video.sample_aspect_ratio != baseline.sample_aspect_ratio, CompatibilityReason.SAMPLE_ASPECT_RATIO, "sample aspect ratio differs"),
        (video.time_base is None or video.time_base != baseline.time_base, CompatibilityReason.VIDEO_TIME_BASE, "video time base is missing or differs"),
    )
    findings.extend(_finding(path, reason, detail) for differs, reason, detail in comparisons if differs)
    rate, variable = effective_frame_rate(video)
    if variable:
        findings.append(_finding(path, CompatibilityReason.VARIABLE_FRAME_RATE, "variable frame timing must become CFR"))
    if rate is None or not frame_rates_equivalent(rate, output_rate, video.time_base):
        findings.append(_finding(path, CompatibilityReason.FRAME_RATE, "frame rate is missing or differs from the job rate"))
    if video.start_time is not None and video.start_time != 0:
        findings.append(_finding(path, CompatibilityReason.TIMESTAMP_ORIGIN, "video timestamps must start at zero"))
    if video.color_space is None or video.color_range is None:
        findings.append(_finding(path, CompatibilityReason.COLOR_TAGS, "required color tags are missing"))
    reference_transfer, reference_primaries = optional_reference
    transfer_conflicts = video.color_transfer is not None and reference_transfer is not None and video.color_transfer != reference_transfer
    primaries_conflict = video.color_primaries is not None and reference_primaries is not None and video.color_primaries != reference_primaries
    if video.color_space != baseline.color_space or transfer_conflicts or primaries_conflict:
        findings.append(_finding(path, CompatibilityReason.COLOR_TAGS, "color profile differs from the first clip"))
    if video.color_range in {"pc", "jpeg"}:
        findings.append(_finding(path, CompatibilityReason.COLOR_RANGE, "full range must convert to limited range"))
    return findings


def _compare_audio(path: Path, probe: MediaProbe, baseline: AudioStream | None, output_layout: str | None, any_audio: bool) -> list[CompatibilityFinding]:
    if not any_audio:
        return []
    audio = probe.primary_audio
    if audio is None:
        return [_finding(path, CompatibilityReason.AUDIO_MISSING, "silence must replace missing audio")]
    findings: list[CompatibilityFinding] = []
    if baseline is not None:
        comparisons = (
            (audio.codec_name in {"", "unknown"} or audio.codec_name != baseline.codec_name, CompatibilityReason.AUDIO_CODEC, "audio codec is missing or differs"),
            (audio.sample_rate is None or audio.sample_rate != baseline.sample_rate, CompatibilityReason.AUDIO_SAMPLE_RATE, "audio sample rate is missing or differs"),
            (audio.channels is None or audio.channels != baseline.channels, CompatibilityReason.AUDIO_CHANNELS, "audio channel count is missing or differs"),
            (audio.channel_layout is None or audio.channel_layout != baseline.channel_layout, CompatibilityReason.AUDIO_LAYOUT, "audio channel layout is missing or differs"),
            (audio.time_base is None or audio.time_base != baseline.time_base, CompatibilityReason.AUDIO_TIME_BASE, "audio time base is missing or differs"),
        )
        findings.extend(_finding(path, reason, detail) for differs, reason, detail in comparisons if differs)
    if output_layout is not None and audio.channel_layout != output_layout:
        finding = _finding(path, CompatibilityReason.AUDIO_LAYOUT, "audio must convert to the selected channel layout")
        if finding not in findings:
            findings.append(finding)
    if audio.start_time is not None and audio.start_time != 0:
        findings.append(_finding(path, CompatibilityReason.TIMESTAMP_ORIGIN, "audio timestamps must start at zero"))
    video_duration = probe.primary_video.duration if probe.primary_video and probe.primary_video.duration is not None else probe.duration
    if audio.duration is None or video_duration is None or abs(audio.duration - video_duration) > AUDIO_DURATION_TOLERANCE:
        findings.append(_finding(path, CompatibilityReason.AUDIO_DURATION, "audio must be padded or trimmed to the video duration"))
    return findings


def analyze_clip_compatibility(probes: tuple[MediaProbe, ...] | list[MediaProbe], output_rate: Rational, output_audio_layout: str | None) -> CompatibilityReport:
    """Choose stream copy only when every relevant stream property matches."""

    if not probes:
        raise ValueError("at least one probe is required")
    baseline_video = probes[0].primary_video
    if baseline_video is None:
        raise ValueError("the first probe has no video stream")
    any_audio = any(probe.primary_audio is not None for probe in probes)
    baseline_audio = next((probe.primary_audio for probe in probes if probe.primary_audio is not None), None)
    reference_transfer = next((video.color_transfer for probe in probes if (video := probe.primary_video) is not None and video.color_transfer is not None), None)
    reference_primaries = next((video.color_primaries for probe in probes if (video := probe.primary_video) is not None and video.color_primaries is not None), None)
    optional_reference = (reference_transfer, reference_primaries)
    findings: list[CompatibilityFinding] = []
    for probe in probes:
        video = probe.primary_video
        if video is None:
            raise ValueError(f"probe has no video stream: {probe.path}")
        findings.extend(_compare_video(probe.path, video, baseline_video, output_rate, optional_reference))
        findings.extend(_compare_audio(probe.path, probe, baseline_audio, output_audio_layout, any_audio))
    unique = tuple(dict.fromkeys(findings))
    strategy = ConcatStrategy.NORMALIZE if unique else ConcatStrategy.STREAM_COPY
    return CompatibilityReport(strategy, unique)
