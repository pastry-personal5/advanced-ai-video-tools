"""Tests for defensive conversion of FFprobe JSON."""

import json
import subprocess
from decimal import Decimal
from pathlib import Path

import pytest

from advanced_ai_video_tools.core.models import Rational
from advanced_ai_video_tools.video.probe import FFprobeClient, build_ffprobe_command, parse_probe_document


def test_probe_parser_preserves_exact_rates_and_stream_inventory() -> None:
    """FFprobe values become immutable models without float conversion."""

    parsed = parse_probe_document(
        Path("clip.mov"),
        {
            "format": {"duration": "2.500"},
            "chapters": [{"id": 0}],
            "streams": [
                {
                    "index": 0,
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1920,
                    "height": 1080,
                    "pix_fmt": "yuv420p",
                    "sample_aspect_ratio": "1:1",
                    "r_frame_rate": "30000/1001",
                    "avg_frame_rate": "30000/1001",
                    "time_base": "1/30000",
                    "color_space": "bt709",
                    "color_transfer": "bt709",
                    "color_primaries": "bt709",
                    "color_range": "tv",
                    "side_data_list": [{"rotation": "-90.000000"}],
                },
                {
                    "index": 1,
                    "codec_type": "audio",
                    "codec_name": "aac",
                    "sample_rate": "48000",
                    "channels": 2,
                    "channel_layout": "stereo",
                    "duration": "2.4",
                    "time_base": "1/48000",
                    "start_time": "0.125",
                },
                {"index": 2, "codec_type": "subtitle", "codec_name": "mov_text"},
            ],
        },
    )

    assert parsed.primary_video is not None
    assert parsed.primary_video.real_frame_rate == Rational(30000, 1001)
    assert parsed.primary_video.rotation == 270
    assert parsed.primary_audio is not None
    assert parsed.primary_audio.sample_rate == 48000
    assert parsed.primary_audio.time_base == Rational(1, 48000)
    assert parsed.primary_audio.start_time == Decimal("0.125")
    assert parsed.other_streams[0].kind == "subtitle"
    assert parsed.chapter_count == 1


def test_probe_parser_treats_attached_picture_as_unsupported_attachment() -> None:
    """Cover art cannot accidentally become the primary timeline video."""

    parsed = parse_probe_document(
        Path("with-cover.mp4"),
        {
            "streams": [
                {
                    "index": 0,
                    "codec_type": "video",
                    "codec_name": "mjpeg",
                    "width": 600,
                    "height": 600,
                    "disposition": {"attached_pic": 1},
                },
                {
                    "index": 1,
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1920,
                    "height": 1080,
                    "r_frame_rate": "24/1",
                },
            ]
        },
    )

    assert parsed.primary_video is not None
    assert parsed.primary_video.index == 1
    assert parsed.other_streams[0].kind == "attachment"


def test_probe_parser_detects_hdr_side_data() -> None:
    """Mastering metadata is retained as an explicit HDR signal."""

    parsed = parse_probe_document(
        Path("hdr.mp4"),
        {
            "streams": [
                {
                    "index": 0,
                    "codec_type": "video",
                    "codec_name": "hevc",
                    "width": 3840,
                    "height": 2160,
                    "r_frame_rate": "24/1",
                    "side_data_list": [{"side_data_type": "Mastering display metadata"}],
                }
            ]
        },
    )

    assert parsed.primary_video is not None
    assert parsed.primary_video.has_hdr_metadata


def test_probe_parser_reads_matroska_duration_tags() -> None:
    """Stream-level Matroska timecodes support audio/video alignment checks."""

    parsed = parse_probe_document(Path("normalized.mkv"), {"format": {"duration": "1.25"}, "streams": [{"index": 0, "codec_type": "video", "codec_name": "ffv1", "width": 64, "height": 36, "r_frame_rate": "10/1", "tags": {"DURATION": "00:00:01.200000000"}}, {"index": 1, "codec_type": "audio", "codec_name": "pcm_s24le", "sample_rate": "48000", "channels": 1, "channel_layout": "mono", "tags": {"duration": "00:00:01.200000000"}}]})

    assert parsed.primary_video is not None
    assert parsed.primary_audio is not None
    assert parsed.primary_video.duration == Decimal("1.200000000")
    assert parsed.primary_audio.duration == Decimal("1.200000000")


def test_ffprobe_client_logs_the_complete_argument_vector_before_launch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every media probe passes its exact launch arguments to INFO logging."""

    executable = tmp_path / "custom ffprobe"
    media = tmp_path / "clip with spaces.mov"
    logged: list[tuple[str, ...]] = []

    def completed(arguments: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(arguments, 0, json.dumps({"streams": []}), "")  # type: ignore[arg-type]

    monkeypatch.setattr("advanced_ai_video_tools.video.probe.log_subprocess_launch", lambda command: logged.append(tuple(command)))
    monkeypatch.setattr("advanced_ai_video_tools.video.probe.subprocess.run", completed)

    FFprobeClient(executable).probe(media)

    assert logged == [build_ffprobe_command(executable, media)]
