"""Pure FFmpeg argument builders for normalization and concat preparation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from ai_video_tools.core.models import ColorProfile, ConcatStrategy, JobPlan, MediaProbe, Rational
from ai_video_tools.video.compatibility import CompatibilityReport, analyze_clip_compatibility
from ai_video_tools.video.frames import FRAME_FILENAME_TEMPLATE
from ai_video_tools.video.policy import color_profile, color_profiles_compatible, color_profiles_mutually_compatible, has_ambiguous_color_tags, has_unsupported_sdr_tags, is_hdr_or_wide_gamut

_SAFE_CHANNEL_LAYOUT = re.compile(r"^[A-Za-z0-9_.()+-]+$")


@dataclass(frozen=True)
class NormalizationSpec:
    """Common lossless intermediate profile selected for every input clip."""

    width: int
    height: int
    sample_aspect_ratio: Rational
    frame_rate: Rational
    color_profile: ColorProfile
    audio_layout: str | None
    audio_sample_rate: int = 48000

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("normalization dimensions must be positive")
        if not self.frame_rate.positive:
            raise ValueError("normalization frame rate must be positive")
        if not self.sample_aspect_ratio.positive:
            raise ValueError("normalization sample aspect ratio must be positive")
        if self.audio_sample_rate <= 0:
            raise ValueError("normalization audio sample rate must be positive")
        if self.audio_layout is not None and not _SAFE_CHANNEL_LAYOUT.fullmatch(self.audio_layout):
            raise ValueError(f"unsupported audio channel layout syntax: {self.audio_layout!r}")


@dataclass(frozen=True)
class MediaPreparationPlan:
    """Ordered normalization commands followed by exactly one concat command."""

    compatibility: CompatibilityReport
    normalization_commands: tuple[tuple[str, ...], ...]
    concat_inputs: tuple[Path, ...]
    concat_manifest_path: Path
    concat_command: tuple[str, ...]
    merged_output_path: Path


@dataclass(frozen=True)
class FrameExtractionPlan:
    """One exact-CFR RGB PNG extraction from the verified merged timeline."""

    frames_directory: Path
    frame_pattern: Path
    command: tuple[str, ...]
    expected_frame_count: int
    audio_source_path: Path | None


def _duration(probe: MediaProbe) -> Decimal:
    video = probe.primary_video
    duration = video.duration if video is not None and video.duration is not None else probe.duration
    if duration is None or duration <= 0:
        raise ValueError(f"input has no positive video duration: {probe.path}")
    return duration


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def _validate_video_policy(probe: MediaProbe, *, expected_profile: ColorProfile | None = None) -> ColorProfile:
    video = probe.primary_video
    if video is None:
        raise ValueError(f"input has no video stream: {probe.path}")
    if video.rotation:
        raise ValueError(f"rotated input cannot be processed: {probe.path}")
    if is_hdr_or_wide_gamut(video):
        raise ValueError(f"HDR or wide-gamut input cannot be processed: {probe.path}")
    if has_unsupported_sdr_tags(video):
        raise ValueError(f"input has an unsupported SDR color profile: {probe.path}")
    if has_ambiguous_color_tags(video):
        raise ValueError(f"input color matrix and range must be explicit: {probe.path}")
    profile = color_profile(video)
    if expected_profile is not None and not color_profiles_compatible(profile, expected_profile):
        raise ValueError(f"input color profile differs from the first clip; cross-profile conversion is unsupported: {probe.path}")
    return profile


def build_normalization_command(ffmpeg: Path, probe: MediaProbe, output: Path, spec: NormalizationSpec) -> tuple[str, ...]:
    """Build one shell-free FFV1/PCM normalization invocation."""

    _validate_video_policy(probe, expected_profile=spec.color_profile)
    video = probe.primary_video
    if video is None:
        raise AssertionError("validated probe lost its primary video")
    if output.resolve(strict=False) == probe.path.resolve(strict=False):
        raise ValueError("normalization output cannot overwrite its source input")
    duration = _duration(probe)
    duration_text = _decimal_text(duration)
    input_range = "pc" if video.color_range in {"pc", "jpeg"} else "tv"
    matrix = spec.color_profile.matrix.value
    transfer = spec.color_profile.transfer
    primaries = spec.color_profile.primaries
    setparams = ["range=limited"]
    if primaries is not None:
        setparams.append(f"color_primaries={primaries}")
    if transfer is not None:
        setparams.append(f"color_trc={transfer}")
    setparams.append(f"colorspace={matrix}")
    arguments = [str(ffmpeg), "-hide_banner", "-nostdin", "-y", "-noautorotate", "-i", str(probe.path)]
    audio_input_index = 0
    if spec.audio_layout is not None and probe.primary_audio is None:
        audio_input_index = 1
        arguments.extend(["-f", "lavfi", "-t", duration_text, "-i", f"anullsrc=channel_layout={spec.audio_layout}:sample_rate={spec.audio_sample_rate}"])
    video_filter = f"[0:{video.index}]scale=w={spec.width}:h={spec.height}:force_original_aspect_ratio=decrease:force_divisible_by=2:flags=lanczos+accurate_rnd+full_chroma_int:in_color_matrix={matrix}:out_color_matrix={matrix}:in_range={input_range}:out_range=tv,setsar={spec.sample_aspect_ratio},pad=width={spec.width}:height={spec.height}:x=(ow-iw)/2:y=(oh-ih)/2:color=black,trim=duration={duration_text},setpts=PTS-STARTPTS,fps=fps={spec.frame_rate}:round=near,format=yuv444p10le,setparams={':'.join(setparams)}[v]"
    filters = [video_filter]
    if spec.audio_layout is not None:
        audio = probe.primary_audio
        audio_label = f"[0:{audio.index}]" if audio is not None else f"[{audio_input_index}:a:0]"
        filters.append(f"{audio_label}aresample={spec.audio_sample_rate}:async=0:first_pts=0,aformat=sample_rates={spec.audio_sample_rate}:channel_layouts={spec.audio_layout},apad,atrim=duration={duration_text},asetpts=PTS-STARTPTS[a]")
    arguments.extend(["-filter_complex", ";".join(filters), "-map", "[v]"])
    if spec.audio_layout is not None:
        arguments.extend(["-map", "[a]"])
    arguments.extend(["-map_metadata", "-1", "-map_chapters", "-1", "-c:v", "ffv1", "-level:v", "3", "-coder:v", "1", "-context:v", "1", "-g:v", "1", "-slicecrc:v", "1", "-pix_fmt", "yuv444p10le", "-r", str(spec.frame_rate), "-fps_mode", "cfr", "-colorspace", matrix])
    if transfer is not None:
        arguments.extend(["-color_trc", transfer])
    if primaries is not None:
        arguments.extend(["-color_primaries", primaries])
    arguments.extend(["-color_range", "tv"])
    if spec.audio_layout is None:
        arguments.append("-an")
    else:
        arguments.extend(["-c:a", "pcm_s24le", "-ar:a", str(spec.audio_sample_rate), "-channel_layout:a", spec.audio_layout])
    arguments.extend(["-t", duration_text, "-avoid_negative_ts", "make_zero", "-f", "matroska", str(output)])
    return tuple(arguments)


def build_concat_command(ffmpeg: Path, manifest: Path, output: Path, *, has_audio: bool) -> tuple[str, ...]:
    """Build one concat-demuxer stream-copy invocation with explicit maps."""

    arguments = [str(ffmpeg), "-hide_banner", "-nostdin", "-y", "-noautorotate", "-f", "concat", "-safe", "0", "-i", str(manifest), "-map", "0:v:0"]
    if has_audio:
        arguments.extend(["-map", "0:a:0"])
    arguments.extend(["-map_metadata", "-1", "-map_chapters", "-1", "-c", "copy", "-avoid_negative_ts", "make_zero", "-f", "matroska", str(output)])
    return tuple(arguments)


def build_media_preparation_plan(job: JobPlan, ffmpeg: Path, workspace: Path) -> MediaPreparationPlan:
    """Plan normalize-all-or-none and then one concat operation."""

    if not job.probes:
        raise ValueError("a preparation plan requires at least one probe")
    first_video = job.probes[0].primary_video
    if first_video is None:
        raise ValueError("the first input has no video stream")
    profiles: list[ColorProfile] = []
    for probe in job.probes:
        profiles.append(_validate_video_policy(probe, expected_profile=job.output_color_profile))
        drops_streams = len(probe.video_streams) > 1 or len(probe.audio_streams) > 1 or bool(probe.other_streams) or probe.chapter_count > 0
        if drops_streams and not job.acknowledge_dropped_streams:
            raise ValueError(f"dropping unsupported streams requires acknowledgement: {probe.path}")
    if not color_profiles_mutually_compatible(profiles):
        raise ValueError("input clips contain conflicting explicit transfer characteristics or color primaries")
    compatibility = analyze_clip_compatibility(job.probes, job.output_frame_rate, job.output_audio_layout)
    if compatibility.strategy is not job.concat_strategy:
        raise ValueError("job concat strategy is inconsistent with probed media")
    manifest = workspace / "concat.ffconcat"
    merged = workspace / "merged.mkv"
    normalization_commands: list[tuple[str, ...]] = []
    if compatibility.strategy is ConcatStrategy.NORMALIZE:
        normalized_directory = workspace / "normalized"
        spec = NormalizationSpec(first_video.width, first_video.height, first_video.sample_aspect_ratio, job.output_frame_rate, job.output_color_profile, job.output_audio_layout)
        concat_inputs = tuple(normalized_directory / f"clip-{index:06d}.mkv" for index in range(1, len(job.probes) + 1))
        normalization_commands.extend(build_normalization_command(ffmpeg, probe, output, spec) for probe, output in zip(job.probes, concat_inputs))
    else:
        concat_inputs = tuple(probe.path for probe in job.probes)
    concat_command = build_concat_command(ffmpeg, manifest, merged, has_audio=job.output_audio_layout is not None)
    return MediaPreparationPlan(compatibility, tuple(normalization_commands), concat_inputs, manifest, concat_command, merged)


def expected_frame_count(probe: MediaProbe, frame_rate: Rational) -> int:
    """Calculate the nearest positive CFR frame count without using floats."""

    if not frame_rate.positive:
        raise ValueError("frame extraction rate must be positive")
    video = probe.primary_video
    if video is None:
        raise ValueError("frame extraction requires a primary video stream")
    duration = video.duration if video.duration is not None else probe.duration
    if duration is None or duration <= 0:
        raise ValueError("frame extraction requires a positive merged-video duration")
    exact_count = duration * Decimal(frame_rate.numerator) / Decimal(frame_rate.denominator)
    return max(1, int(exact_count.to_integral_value(rounding=ROUND_HALF_UP)))


def build_frame_extraction_command(ffmpeg: Path, merged: MediaProbe, frames_directory: Path, frame_rate: Rational) -> tuple[str, ...]:
    """Build one shell-free limited SDR YUV to full-range RGB PNG decode."""

    if not frame_rate.positive:
        raise ValueError("frame extraction rate must be positive")
    video = merged.primary_video
    if video is None:
        raise ValueError("frame extraction requires a primary video stream")
    if video.rotation:
        raise ValueError("rotated merged video cannot be extracted")
    profile = color_profile(video)
    if video.color_range not in {"tv", "limited"}:
        raise ValueError("frame extraction requires explicitly limited-range SDR video")
    matrix = profile.matrix.value
    frame_pattern = frames_directory / FRAME_FILENAME_TEMPLATE
    video_filter = f"scale=w=iw:h=ih:flags=lanczos+accurate_rnd+full_chroma_int:in_color_matrix={matrix}:out_color_matrix={matrix}:in_range=tv:out_range=pc,format=pix_fmts=rgb24,fps=fps={frame_rate}:round=near"
    return (str(ffmpeg), "-hide_banner", "-nostdin", "-y", "-noautorotate", "-i", str(merged.path), "-map", f"0:{video.index}", "-an", "-sn", "-dn", "-vf", video_filter, "-c:v", "png", "-pix_fmt", "rgb24", "-compression_level", "6", "-fps_mode", "passthrough", "-start_number", "1", "-f", "image2", str(frame_pattern))


def build_frame_extraction_plan(job: JobPlan, ffmpeg: Path, merged: MediaProbe, workspace: Path) -> FrameExtractionPlan:
    """Plan deterministic frame extraction while retaining merged audio in place."""

    if merged.path.resolve(strict=False).parent != workspace.resolve(strict=False):
        raise ValueError("merged media must be a direct child of the owned workspace")
    frames_directory = workspace / "frames"
    command = build_frame_extraction_command(ffmpeg, merged, frames_directory, job.output_frame_rate)
    video = merged.primary_video
    if video is None or color_profile(video) != job.output_color_profile:
        raise ValueError("merged color profile differs from the frozen job profile")
    audio_source = merged.path if job.output_audio_layout is not None else None
    if (audio_source is None) != (merged.primary_audio is None):
        raise ValueError("merged audio presence differs from the job plan")
    return FrameExtractionPlan(frames_directory, frames_directory / FRAME_FILENAME_TEMPLATE, command, expected_frame_count(merged, job.output_frame_rate), audio_source)
