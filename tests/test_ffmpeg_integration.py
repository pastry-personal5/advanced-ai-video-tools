"""Tiny real-FFmpeg tests for normalization and concat behavior."""

from __future__ import annotations

import shutil
import subprocess
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from ai_video_tools.core.models import ConcatStrategy, JobPlan, Rational
from ai_video_tools.services.media_preparation import MediaPreparationExecutor, MergedOutputVerifier
from ai_video_tools.storage.workspaces import WorkspaceManager
from ai_video_tools.system.processes import SubprocessRunner
from ai_video_tools.video.commands import NormalizationSpec, build_concat_command, build_normalization_command
from ai_video_tools.video.manifest import write_concat_manifest
from ai_video_tools.video.probe import FFprobeClient


def _run(arguments: tuple[str, ...] | list[str]) -> None:
    result = subprocess.run(arguments, check=False, capture_output=True, text=True, timeout=30, shell=False)
    assert result.returncode == 0, result.stderr


def _generate_source(ffmpeg: Path, output: Path, audio_duration: Decimal | None) -> None:
    arguments = [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-f", "lavfi", "-i", "testsrc2=size=64x36:rate=10:duration=0.4"]
    if audio_duration is not None:
        arguments.extend(["-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={audio_duration}", "-map", "0:v:0", "-map", "1:a:0"])
    else:
        arguments.extend(["-map", "0:v:0", "-an"])
    arguments.extend(["-c:v", "libx264", "-preset", "ultrafast", "-crf", "30", "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_trc", "bt709", "-color_primaries", "bt709", "-color_range", "tv"])
    if audio_duration is not None:
        arguments.extend(["-c:a", "aac", "-b:a", "64k"])
    arguments.append(str(output))
    _run(arguments)


def _audio_packet_end(ffprobe: Path, media: Path) -> Decimal:
    result = subprocess.run([str(ffprobe), "-v", "error", "-select_streams", "a:0", "-show_entries", "packet=pts_time,duration_time", "-of", "csv=p=0", str(media)], check=False, capture_output=True, text=True, timeout=30, shell=False)
    assert result.returncode == 0, result.stderr
    ends = []
    for line in result.stdout.splitlines():
        parts = line.split(",")
        if len(parts) >= 2 and parts[0] != "N/A" and parts[1] != "N/A":
            ends.append(Decimal(parts[0]) + Decimal(parts[1]))
    assert ends
    return max(ends)


@pytest.mark.integration
def test_normalize_pad_trim_silence_then_concat_once(tmp_path: Path) -> None:
    """Three heterogeneous audio timelines become one aligned lossless timeline."""

    ffmpeg_name = shutil.which("ffmpeg")
    ffprobe_name = shutil.which("ffprobe")
    if ffmpeg_name is None or ffprobe_name is None:
        pytest.skip("FFmpeg and FFprobe are required for integration tests")
    ffmpeg = Path(ffmpeg_name)
    ffprobe = Path(ffprobe_name)
    sources = (tmp_path / "short-audio.mp4", tmp_path / "silent.mp4", tmp_path / "long-audio.mp4")
    _generate_source(ffmpeg, sources[0], Decimal("0.2"))
    _generate_source(ffmpeg, sources[1], None)
    _generate_source(ffmpeg, sources[2], Decimal("0.7"))
    client = FFprobeClient(ffprobe)
    probes = tuple(client.probe(path) for path in sources)
    normalized = (tmp_path / "normalized-short.mkv", tmp_path / "normalized-silent.mkv", tmp_path / "director's-normalized-long.mkv")
    spec = NormalizationSpec(64, 36, Rational(1, 1), Rational(10, 1), "mono")
    for probe, output in zip(probes, normalized):
        _run(build_normalization_command(ffmpeg, probe, output, spec, assume_bt709=True))

    for output in normalized:
        audio_end = _audio_packet_end(ffprobe, output)
        assert Decimal("0.38") <= audio_end <= Decimal("0.45")
    manifest = tmp_path / "concat.ffconcat"
    merged_path = tmp_path / "merged.mkv"
    write_concat_manifest(manifest, normalized)
    _run(build_concat_command(ffmpeg, manifest, merged_path, has_audio=True))

    merged = client.probe(merged_path)
    assert merged.primary_video is not None
    assert merged.primary_video.codec_name == "ffv1"
    assert merged.primary_video.real_frame_rate == Rational(10, 1)
    assert merged.primary_video.color_space == "bt709"
    assert merged.primary_video.color_transfer == "bt709"
    assert merged.primary_video.color_primaries == "bt709"
    assert merged.primary_video.color_range == "tv"
    assert merged.primary_audio is not None
    assert merged.primary_audio.codec_name == "pcm_s24le"
    assert merged.primary_audio.sample_rate == 48000
    assert merged.duration is not None
    assert Decimal("1.18") <= merged.duration <= Decimal("1.25")


@pytest.mark.integration
def test_media_preparation_executor_runs_real_ffmpeg_and_cleans_success(tmp_path: Path) -> None:
    """The service executes normalize-all, one concat, verification, and cleanup."""

    ffmpeg_name = shutil.which("ffmpeg")
    ffprobe_name = shutil.which("ffprobe")
    if ffmpeg_name is None or ffprobe_name is None:
        pytest.skip("FFmpeg and FFprobe are required for integration tests")
    ffmpeg = Path(ffmpeg_name)
    ffprobe = Path(ffprobe_name)
    sources = (tmp_path / "short.mp4", tmp_path / "silent.mp4")
    _generate_source(ffmpeg, sources[0], Decimal("0.2"))
    _generate_source(ffmpeg, sources[1], None)
    prober = FFprobeClient(ffprobe)
    probes = tuple(prober.probe(path) for path in sources)
    job = JobPlan(datetime(2026, 8, 21, tzinfo=timezone.utc), tmp_path / "unused-output.mp4", True, probes, Rational(10, 1), 3840, 2160, 4, ConcatStrategy.NORMALIZE, "mono", ("audio timelines require normalization",), 100, 120, assume_bt709=True)
    manager = WorkspaceManager(tmp_path / "jobs")
    executor = MediaPreparationExecutor(manager, SubprocessRunner(), MergedOutputVerifier(prober), command_timeout_seconds=30)

    result = executor.execute(job, ffmpeg)

    assert result.normalization_count == 2
    assert len(result.process_results) == 3
    assert result.merged_probe.primary_video is not None
    assert result.merged_probe.primary_video.codec_name == "ffv1"
    assert result.merged_probe.primary_audio is not None
    assert result.merged_probe.primary_audio.codec_name == "pcm_s24le"
    assert result.merged_probe.duration is not None
    assert Decimal("0.78") <= result.merged_probe.duration <= Decimal("0.85")
    assert not result.merged_probe.path.exists()
    assert not any(manager.root.iterdir())
