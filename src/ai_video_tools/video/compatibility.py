"""Typed concat compatibility analysis for probed clips."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
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


def effective_frame_rate(video: VideoStream) -> tuple[Rational | None, bool]:
    """Return the exact output rate candidate and whether timing is VFR."""

    real = video.real_frame_rate
    average = video.average_frame_rate
    if real is not None and average is not None:
        return (average, True) if real != average else (real, False)
    if average is not None:
        return average, True
    return real, False


def _finding(path: Path, reason: CompatibilityReason, detail: str) -> CompatibilityFinding:
    return CompatibilityFinding(path, reason, f"{path.name}: {detail}")


def _compare_video(path: Path, video: VideoStream, baseline: VideoStream, output_rate: Rational) -> list[CompatibilityFinding]:
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
    if rate is None or rate != output_rate:
        findings.append(_finding(path, CompatibilityReason.FRAME_RATE, "frame rate is missing or differs from the job rate"))
    if video.start_time is not None and video.start_time != 0:
        findings.append(_finding(path, CompatibilityReason.TIMESTAMP_ORIGIN, "video timestamps must start at zero"))
    if None in (video.color_space, video.color_transfer, video.color_primaries, video.color_range):
        findings.append(_finding(path, CompatibilityReason.COLOR_TAGS, "BT.709 tags must be normalized"))
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
    findings: list[CompatibilityFinding] = []
    for probe in probes:
        video = probe.primary_video
        if video is None:
            raise ValueError(f"probe has no video stream: {probe.path}")
        findings.extend(_compare_video(probe.path, video, baseline_video, output_rate))
        findings.extend(_compare_audio(probe.path, probe, baseline_audio, output_audio_layout, any_audio))
    unique = tuple(dict.fromkeys(findings))
    strategy = ConcatStrategy.NORMALIZE if unique else ConcatStrategy.STREAM_COPY
    return CompatibilityReport(strategy, unique)
