"""Tests for the explicit quality-first final MP4 command policy."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from ai_video_tools.core.models import AudioStream, ConcatStrategy, JobPlan, MediaProbe, Rational, VideoStream
from ai_video_tools.video.finalization import FinalAudioMode, build_final_encoding_plan


def _video(duration: Decimal = Decimal("1")) -> VideoStream:
    return VideoStream(0, "ffv1", 64, 36, "yuv444p10le", Rational(1, 1), Rational(10, 1), Rational(10, 1), Rational(1, 1000), duration, "bt709", "bt709", "bt709", "tv", 0, False)


def _audio(codec: str, duration: Decimal = Decimal("1"), *, start_time: Decimal | None = None) -> AudioStream:
    return AudioStream(1, codec, 48000, 1, "mono", duration, Rational(1, 48000), start_time)


def _job(tmp_path: Path, strategy: ConcatStrategy, *, audio_layout: str | None) -> JobPlan:
    return JobPlan(datetime(2026, 8, 21, tzinfo=timezone.utc), tmp_path / "final.mp4", False, (), Rational(10, 1), 64, 36, None, strategy, audio_layout, (), 100, 120)


def _plan(tmp_path: Path, strategy: ConcatStrategy, *, audio: AudioStream | None = None):
    workspace = tmp_path / "job"
    frames = workspace / "frames"
    merged_path = workspace / "merged.mkv"
    merged = MediaProbe(merged_path, Decimal("1"), (_video(),), (audio,) if audio is not None else (), ())
    return build_final_encoding_plan(_job(tmp_path, strategy, audio_layout="mono" if audio is not None else None), Path("ffmpeg"), merged, workspace, tmp_path / ".partial.mp4", frames_directory=frames, frame_count=10, frame_width=64, frame_height=36, audio_source_path=merged_path if audio is not None else None)


def test_video_only_command_freezes_quality_color_timing_and_stream_policy(tmp_path: Path) -> None:
    """Final video has no implicit stream, color, timing, or codec decisions."""

    plan = _plan(tmp_path, ConcatStrategy.NORMALIZE)
    command = plan.command
    video_filter = command[command.index("-vf") + 1]

    assert plan.audio_mode is FinalAudioMode.NONE
    assert command[command.index("-i") - 1] == "-noautorotate"
    assert command[command.index("-framerate") + 1] == "10/1"
    assert command[command.index("-map") + 1] == "0:v:0"
    assert "scale=w=64:h=36" in video_filter
    assert "in_range=pc:out_range=tv:out_color_matrix=bt709" in video_filter
    assert "color_primaries=bt709:color_trc=bt709:colorspace=bt709" in video_filter
    assert command[command.index("-c:v") + 1] == "libx264"
    assert command[command.index("-preset") + 1] == "slow"
    assert command[command.index("-crf") + 1] == "18"
    assert command[command.index("-pix_fmt") + 1] == "yuv420p"
    assert command[command.index("-r") + 1] == "10/1"
    assert command[command.index("-frames:v") + 1] == "10"
    assert "-an" in command
    assert command[command.index("-movflags") + 1] == "+faststart"
    assert command[-2:] == ("-f", "mp4", str(tmp_path / ".partial.mp4"))[-2:]


def test_normalized_audio_is_encoded_and_aligned_to_frame_timeline(tmp_path: Path) -> None:
    """Lossless preparation audio becomes padded/trimmed 48 kHz AAC-LC."""

    plan = _plan(tmp_path, ConcatStrategy.NORMALIZE, audio=_audio("pcm_s24le", Decimal("0.8")))
    command = plan.command
    audio_filter = command[command.index("-af") + 1]

    assert plan.audio_mode is FinalAudioMode.AAC
    assert plan.duration == Decimal("1")
    assert "aresample=48000:async=0:first_pts=0" in audio_filter
    assert "channel_layouts=mono" in audio_filter
    assert "apad,atrim=duration=1" in audio_filter
    assert command[command.index("-c:a") + 1] == "aac"
    assert command[command.index("-profile:a") + 1] == "aac_low"
    assert command[command.index("-b:a") + 1] == "256k"
    assert command[command.index("-ar:a") + 1] == "48000"
    assert command[command.index("-t") + 1] == "1"


def test_exact_direct_concat_audio_can_be_copied(tmp_path: Path) -> None:
    """An exact, zero-origin, MP4-compatible first stream avoids another encode."""

    plan = _plan(tmp_path, ConcatStrategy.STREAM_COPY, audio=_audio("aac"))

    assert plan.audio_mode is FinalAudioMode.COPY
    assert plan.expected_audio_codec == "aac"
    assert plan.command[plan.command.index("-c:a") + 1] == "copy"
    assert "-af" not in plan.command


def test_shifted_or_inexact_direct_audio_is_reencoded(tmp_path: Path) -> None:
    """Timestamp correction and timeline repair force the safe AAC path."""

    shifted = _plan(tmp_path, ConcatStrategy.STREAM_COPY, audio=_audio("aac", start_time=Decimal("0.01")))
    short = _plan(tmp_path, ConcatStrategy.STREAM_COPY, audio=_audio("aac", Decimal("0.99")))

    assert shifted.audio_mode is FinalAudioMode.AAC
    assert short.audio_mode is FinalAudioMode.AAC


def test_final_builder_rejects_unsafe_destination_dimensions_and_audio_source(tmp_path: Path) -> None:
    """The low-level boundary cannot publish elsewhere or mux unverified audio."""

    workspace = tmp_path / "job"
    frames = workspace / "frames"
    merged = MediaProbe(workspace / "merged.mkv", Decimal("1"), (_video(),), (_audio("pcm_s24le"),), ())
    job = _job(tmp_path, ConcatStrategy.NORMALIZE, audio_layout="mono")
    with pytest.raises(ValueError, match="destination filesystem"):
        build_final_encoding_plan(job, Path("ffmpeg"), merged, workspace, tmp_path / "elsewhere" / ".partial.mp4", frames_directory=frames, frame_count=10, frame_width=64, frame_height=36, audio_source_path=merged.path)
    with pytest.raises(ValueError, match="retained audio source"):
        build_final_encoding_plan(job, Path("ffmpeg"), merged, workspace, tmp_path / ".partial.mp4", frames_directory=frames, frame_count=10, frame_width=64, frame_height=36, audio_source_path=workspace / "other.mkv")
    odd_job = JobPlan(datetime(2026, 8, 21, tzinfo=timezone.utc), tmp_path / "final.mp4", False, (), Rational(10, 1), 63, 36, None, ConcatStrategy.NORMALIZE, "mono", (), 100, 120)
    with pytest.raises(ValueError, match="even"):
        build_final_encoding_plan(odd_job, Path("ffmpeg"), merged, workspace, tmp_path / ".partial.mp4", frames_directory=frames, frame_count=10, frame_width=64, frame_height=36, audio_source_path=merged.path)
