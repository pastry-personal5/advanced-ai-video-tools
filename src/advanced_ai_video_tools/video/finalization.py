"""Quality-first final MP4 policy and shell-free FFmpeg arguments."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from pathlib import Path

from advanced_ai_video_tools.core.models import ColorProfile, ConcatStrategy, JobPlan, MediaProbe
from advanced_ai_video_tools.video.frames import FRAME_FILENAME_TEMPLATE

_SAFE_CHANNEL_LAYOUT = re.compile(r"^[A-Za-z0-9_.()+-]+$")
_MP4_COPY_AUDIO_CODECS = frozenset({"aac", "alac", "mp3", "ac3", "eac3"})
_AUDIO_ALIGNMENT_TOLERANCE = Decimal(1) / Decimal(48000)
DEFAULT_VIDEO_CRF = 3


class FinalAudioMode(str, Enum):
    """How the retained primary audio enters the final MP4."""

    NONE = "none"
    COPY = "copy"
    AAC = "aac"


@dataclass(frozen=True)
class FinalEncodingPlan:
    """Frozen final-frame, audio, duration, and destination policy."""

    frames_directory: Path
    frame_pattern: Path
    frame_count: int
    frame_width: int
    frame_height: int
    audio_source_path: Path | None
    audio_mode: FinalAudioMode
    expected_audio_codec: str | None
    duration: Decimal
    partial_output_path: Path
    command: tuple[str, ...]


def final_duration(job: JobPlan, frame_count: int) -> Decimal:
    """Return the authoritative frame-sequence duration without float conversion."""

    if frame_count <= 0 or not job.output_frame_rate.positive:
        raise ValueError("final frame count and frame rate must be positive")
    return Decimal(frame_count * job.output_frame_rate.denominator) / Decimal(job.output_frame_rate.numerator)


def _effective_layout(probe: MediaProbe) -> str | None:
    audio = probe.primary_audio
    if audio is None:
        return None
    return audio.channel_layout or {1: "mono", 2: "stereo"}.get(audio.channels)


def _color_signaling(profile: ColorProfile) -> tuple[str, tuple[str, ...]]:
    """Build filter and encoder signaling without inventing optional tags."""

    matrix = profile.matrix.value
    setparams = ["range=limited"]
    arguments = ["-colorspace", matrix]
    if profile.primaries is not None:
        setparams.append(f"color_primaries={profile.primaries}")
    if profile.transfer is not None:
        setparams.append(f"color_trc={profile.transfer}")
        arguments.extend(["-color_trc", profile.transfer])
    setparams.append(f"colorspace={matrix}")
    if profile.primaries is not None:
        arguments.extend(["-color_primaries", profile.primaries])
    arguments.extend(["-color_range", "tv"])
    return ":".join(setparams), tuple(arguments)


def select_final_audio_mode(job: JobPlan, merged: MediaProbe, duration: Decimal) -> FinalAudioMode:
    """Copy only exactly aligned MP4-compatible direct-concat audio."""

    expects_audio = job.output_audio_layout is not None
    audio = merged.primary_audio
    if not expects_audio:
        if merged.audio_streams:
            raise ValueError("merged media unexpectedly contains audio")
        return FinalAudioMode.NONE
    if audio is None or len(merged.audio_streams) != 1:
        raise ValueError("merged media does not contain exactly one expected audio stream")
    if _effective_layout(merged) != job.output_audio_layout:
        raise ValueError("merged audio layout differs from the final job layout")
    aligned = audio.duration is not None and abs(audio.duration - duration) <= _AUDIO_ALIGNMENT_TOLERANCE and audio.start_time in {None, Decimal(0)}
    if job.concat_strategy is ConcatStrategy.STREAM_COPY and audio.codec_name in _MP4_COPY_AUDIO_CODECS and aligned:
        return FinalAudioMode.COPY
    return FinalAudioMode.AAC


def _final_audio_arguments(job: JobPlan, merged: MediaProbe, audio_mode: FinalAudioMode, duration_text: str) -> tuple[str | None, list[str]]:
    """Return the expected codec and explicit audio arguments."""

    if audio_mode is FinalAudioMode.NONE:
        return None, ["-an"]
    if audio_mode is FinalAudioMode.COPY:
        expected_codec = merged.primary_audio.codec_name if merged.primary_audio is not None else None
        return expected_codec, ["-c:a", "copy"]
    audio_filter = f"aresample=48000:async=0:first_pts=0,aformat=sample_rates=48000:channel_layouts={job.output_audio_layout},apad,atrim=duration={duration_text},asetpts=PTS-STARTPTS"
    return "aac", ["-af", audio_filter, "-c:a", "aac", "-profile:a", "aac_low", "-b:a", "256k", "-ar:a", "48000"]


def build_final_encoding_plan(job: JobPlan, ffmpeg: Path, merged: MediaProbe, workspace: Path, partial_output: Path, *, frames_directory: Path, frame_count: int, frame_width: int, frame_height: int, audio_source_path: Path | None) -> FinalEncodingPlan:
    """Build explicit RGB-to-frozen-SDR H.264 encoding and audio mux policy."""

    workspace_path = workspace.resolve(strict=False)
    if frames_directory.resolve(strict=False).parent != workspace_path:
        raise ValueError("final frames must be a direct child of the owned workspace")
    if frame_count <= 0 or frame_width <= 0 or frame_height <= 0:
        raise ValueError("final frame inventory is invalid")
    if job.output_width <= 0 or job.output_height <= 0 or job.output_width % 2 or job.output_height % 2:
        raise ValueError("final dimensions must be positive even integers")
    if partial_output.resolve(strict=False).parent != job.output_path.resolve(strict=False).parent:
        raise ValueError("partial output must be on the destination filesystem")
    if partial_output.resolve(strict=False) == job.output_path.resolve(strict=False):
        raise ValueError("partial output cannot be the final destination")
    duration = final_duration(job, frame_count)
    audio_mode = select_final_audio_mode(job, merged, duration)
    if (audio_source_path is None) != (audio_mode is FinalAudioMode.NONE):
        raise ValueError("retained audio source differs from the final audio policy")
    if audio_source_path is not None and audio_source_path.resolve(strict=False) != merged.path.resolve(strict=False):
        raise ValueError("retained audio source differs from the verified merged media")
    if job.output_audio_layout is not None and not _SAFE_CHANNEL_LAYOUT.fullmatch(job.output_audio_layout):
        raise ValueError(f"unsupported final audio channel layout syntax: {job.output_audio_layout!r}")
    duration_text = format(duration, "f")
    frame_pattern = frames_directory / FRAME_FILENAME_TEMPLATE
    matrix = job.output_color_profile.matrix.value
    setparams, color_arguments = _color_signaling(job.output_color_profile)
    video_filter = f"scale=w={job.output_width}:h={job.output_height}:flags=lanczos+accurate_rnd+full_chroma_int:in_range=pc:out_range=tv:out_color_matrix={matrix},setsar=1,format=pix_fmts=yuv420p,setparams={setparams}"
    arguments = [str(ffmpeg), "-hide_banner", "-nostdin", "-y", "-framerate", str(job.output_frame_rate), "-start_number", "1", "-noautorotate", "-i", str(frame_pattern)]
    if audio_source_path is not None:
        arguments.extend(["-noautorotate", "-i", str(audio_source_path)])
    arguments.extend(["-map", "0:v:0"])
    if audio_source_path is not None:
        arguments.extend(["-map", "1:a:0"])
    arguments.extend(["-map_metadata", "-1", "-map_chapters", "-1", "-vf", video_filter, "-c:v", "libx264", "-preset", "slow", "-crf", str(DEFAULT_VIDEO_CRF), "-pix_fmt", "yuv420p", "-r", str(job.output_frame_rate), "-fps_mode", "cfr", "-frames:v", str(frame_count)])
    arguments.extend(color_arguments)
    arguments.extend(["-metadata:s:v:0", "rotate=0"])
    expected_audio_codec, audio_arguments = _final_audio_arguments(job, merged, audio_mode, duration_text)
    arguments.extend(audio_arguments)
    arguments.extend(["-t", duration_text, "-movflags", "+faststart", "-f", "mp4", str(partial_output)])
    return FinalEncodingPlan(frames_directory, frame_pattern, frame_count, frame_width, frame_height, audio_source_path, audio_mode, expected_audio_codec, duration, partial_output, tuple(arguments))
