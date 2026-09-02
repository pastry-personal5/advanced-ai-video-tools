"""Tests for safe FFmpeg builders and concat-first preparation plans."""

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from advanced_ai_video_tools.core.models import AudioStream, ColorMatrix, ColorProfile, ConcatStrategy, JobPlan, MediaProbe, Rational, VideoStream
from advanced_ai_video_tools.video.commands import FRAME_FILENAME_TEMPLATE, NormalizationSpec, create_concat_command, create_frame_extraction_command, create_frame_extraction_plan, create_media_preparation_plan, create_normalization_command, expected_frame_count
from advanced_ai_video_tools.video.manifest import concat_manifest_text
from advanced_ai_video_tools.video.probe import create_ffprobe_command


def _video(**changes: object) -> VideoStream:
    values: dict[str, object] = {"index": 2, "codec_name": "h264", "width": 640, "height": 360, "pixel_format": "yuv420p", "sample_aspect_ratio": Rational(1, 1), "real_frame_rate": Rational(30000, 1001), "average_frame_rate": Rational(30000, 1001), "time_base": Rational(1, 30000), "duration": Decimal("1.25"), "color_space": "bt709", "color_transfer": "bt709", "color_primaries": "bt709", "color_range": "pc", "rotation": 0, "has_hdr_metadata": False}
    values.update(changes)
    return VideoStream(**values)  # type: ignore[arg-type]


def _audio(index: int = 4) -> AudioStream:
    return AudioStream(index, "aac", 44100, 2, "stereo", Decimal("0.75"), Rational(1, 44100))


def _probe(path: Path, *, video: VideoStream | None = None, audios: tuple[AudioStream, ...] = ()) -> MediaProbe:
    return MediaProbe(path, Decimal("1.25"), (video or _video(),), audios, ())


BT709_PROFILE = ColorProfile(ColorMatrix.BT709, "bt709", "bt709")
SMPTE170M_PROFILE = ColorProfile(ColorMatrix.SMPTE170M, "bt709", "bt709")


def _job(probes: tuple[MediaProbe, ...], strategy: ConcatStrategy, audio_layout: str | None, *, color_profile: ColorProfile = BT709_PROFILE, acknowledge_dropped_streams: bool = False) -> JobPlan:
    return JobPlan(datetime(2026, 8, 21, tzinfo=timezone.utc), Path("output.mp4"), True, probes, Rational(30000, 1001), 3840, 2160, 2, strategy, audio_layout, (), 100, 120, color_profile, acknowledge_dropped_streams)


def test_normalization_command_enforces_video_color_timing_and_first_audio() -> None:
    """The command uses explicit streams and lossless quality-first defaults."""

    probe = _probe(Path("clip.mp4"), audios=(_audio(7), _audio(4)))
    spec = NormalizationSpec(640, 360, Rational(1, 1), Rational(30000, 1001), BT709_PROFILE, "stereo")
    command = create_normalization_command(Path("ffmpeg"), probe, Path("normalized.mkv"), spec)
    filter_graph = command[command.index("-filter_complex") + 1]

    assert command[command.index("-i") - 1] == "-noautorotate"
    assert "[0:2]" in filter_graph
    assert "[0:4]" in filter_graph
    assert "[0:7]" not in filter_graph
    assert "in_range=pc:out_range=tv" in filter_graph
    assert "fps=fps=30000/1001" in filter_graph
    assert "apad,atrim=duration=1.25" in filter_graph
    assert command[command.index("-c:v") + 1] == "ffv1"
    assert command[command.index("-c:a") + 1] == "pcm_s24le"


def test_normalization_inserts_bounded_silence_when_audio_is_missing() -> None:
    """An audio-bearing job supplies silence for a silent clip."""

    command = create_normalization_command(Path("ffmpeg"), _probe(Path("silent.mp4")), Path("normalized.mkv"), NormalizationSpec(640, 360, Rational(1, 1), Rational(24, 1), BT709_PROFILE, "stereo"))

    assert "lavfi" in command
    assert any(argument.startswith("anullsrc=channel_layout=stereo") for argument in command)
    assert "[1:a:0]" in command[command.index("-filter_complex") + 1]


def test_video_only_normalization_explicitly_disables_audio() -> None:
    """All-silent jobs do not gain an accidental audio stream."""

    command = create_normalization_command(Path("ffmpeg"), _probe(Path("silent.mp4")), Path("normalized.mkv"), NormalizationSpec(640, 360, Rational(1, 1), Rational(24, 1), BT709_PROFILE, None))

    assert "-an" in command
    assert not any("anullsrc" in argument for argument in command)


def test_normalization_rejects_rotation_and_filter_syntax_in_layout() -> None:
    """Defense-in-depth prevents unsupported rotation and filter injection."""

    with pytest.raises(ValueError, match="audio channel layout"):
        NormalizationSpec(640, 360, Rational(1, 1), Rational(24, 1), BT709_PROFILE, "stereo;movie=x")
    with pytest.raises(ValueError, match="rotated"):
        create_normalization_command(Path("ffmpeg"), _probe(Path("rotated.mp4"), video=_video(rotation=90)), Path("normalized.mkv"), NormalizationSpec(640, 360, Rational(1, 1), Rational(24, 1), BT709_PROFILE, None))


def test_normalization_rejects_hdr_ambiguous_color_and_source_overwrite() -> None:
    """Low-level builders retain the preflight color and source safety gates."""

    spec = NormalizationSpec(640, 360, Rational(1, 1), Rational(24, 1), BT709_PROFILE, None)
    with pytest.raises(ValueError, match="HDR"):
        create_normalization_command(Path("ffmpeg"), _probe(Path("hdr.mp4"), video=_video(color_transfer="smpte2084")), Path("normalized.mkv"), spec)
    ambiguous = _probe(Path("ambiguous.mp4"), video=_video(color_range=None))
    with pytest.raises(ValueError, match="must be explicit"):
        create_normalization_command(Path("ffmpeg"), ambiguous, Path("normalized.mkv"), spec)
    source = _probe(Path("same.mkv"))
    with pytest.raises(ValueError, match="overwrite"):
        create_normalization_command(Path("ffmpeg"), source, Path("same.mkv"), spec)


def test_normalization_omits_missing_optional_color_tags() -> None:
    """Absent transfer and primaries stay absent instead of becoming BT.709."""

    profile = ColorProfile(ColorMatrix.BT709, None, None)
    probe = _probe(Path("untagged-optionals.mov"), video=_video(color_transfer=None, color_primaries=None, color_range="tv"))

    command = create_normalization_command(Path("ffmpeg"), probe, Path("normalized.mkv"), NormalizationSpec(640, 360, Rational(1, 1), Rational(24, 1), profile, None))
    filter_graph = command[command.index("-filter_complex") + 1]

    assert "setparams=range=limited:colorspace=bt709" in filter_graph
    assert "-color_trc" not in command
    assert "-color_primaries" not in command


def test_preparation_rejects_explicit_optional_tag_conflicts_hidden_by_missing_first_tag(tmp_path: Path) -> None:
    """The execution boundary independently rejects contradictory declared tags."""

    probes = (
        _probe(Path("first.mov"), video=_video(color_transfer=None)),
        _probe(Path("second.mov")),
        _probe(Path("third.mov"), video=_video(color_transfer="smpte170m")),
    )
    job = _job(probes, ConcatStrategy.NORMALIZE, None, color_profile=ColorProfile(ColorMatrix.BT709, None, "bt709"))

    with pytest.raises(ValueError, match="conflicting explicit transfer"):
        create_media_preparation_plan(job, Path("ffmpeg"), tmp_path)


def test_normalization_preserves_smpte170m_matrix() -> None:
    """SMPTE 170M remains the input, processing, and output matrix."""

    probe = _probe(Path("smpte170m.mov"), video=_video(color_space="smpte170m", color_range="tv"))
    command = create_normalization_command(Path("ffmpeg"), probe, Path("normalized.mkv"), NormalizationSpec(640, 360, Rational(1, 1), Rational(30000, 1001), SMPTE170M_PROFILE, None))
    filter_graph = command[command.index("-filter_complex") + 1]

    assert "in_color_matrix=smpte170m:out_color_matrix=smpte170m" in filter_graph
    assert command[command.index("-colorspace") + 1] == "smpte170m"


def test_concat_and_ffprobe_builders_are_shell_free_and_explicit() -> None:
    """Probe and concat commands map known streams without implicit selection."""

    concat = create_concat_command(Path("ffmpeg"), Path("concat.ffconcat"), Path("merged.mkv"), has_audio=True)
    probe = create_ffprobe_command(Path("ffprobe"), Path("clip with spaces.mp4"))

    assert concat.index("-noautorotate") < concat.index("-i")
    assert concat[concat.index("-i") - 4 : concat.index("-i")] == ("-f", "concat", "-safe", "0")
    assert "0:v:0" in concat and "0:a:0" in concat
    assert concat[concat.index("-c") + 1] == "copy"
    assert probe[-1] == "clip with spaces.mp4"


def test_frame_extraction_builder_enforces_exact_rgb_png_contract(tmp_path: Path) -> None:
    """Extraction explicitly converts limited BT.709 YUV at the frozen rational rate."""

    merged_path = tmp_path / "merged with spaces.mkv"
    merged = _probe(merged_path, video=_video(color_range="tv"), audios=(_audio(),))
    job = _job((merged,), ConcatStrategy.STREAM_COPY, "stereo")
    command = create_frame_extraction_command(Path("ffmpeg"), merged, tmp_path / "frames", Rational(30000, 1001))
    plan = create_frame_extraction_plan(job, Path("ffmpeg"), merged, tmp_path)
    video_filter = command[command.index("-vf") + 1]

    assert command[command.index("-i") - 1] == "-noautorotate"
    assert command[command.index("-map") + 1] == "0:2"
    assert "-an" in command and "-sn" in command and "-dn" in command
    assert "in_color_matrix=bt709:out_color_matrix=bt709:in_range=tv:out_range=pc" in video_filter
    assert "format=pix_fmts=rgb24" in video_filter
    assert "fps=fps=30000/1001:round=near" in video_filter
    assert command[command.index("-c:v") + 1] == "png"
    assert command[-1] == str(tmp_path / "frames" / FRAME_FILENAME_TEMPLATE)
    assert expected_frame_count(merged, Rational(30000, 1001)) == 37
    assert plan.expected_frame_count == 37
    assert plan.audio_source_path == merged_path


def test_frame_extraction_rejects_unsafe_media_contracts(tmp_path: Path) -> None:
    """Low-level extraction cannot silently reinterpret color, rotation, or audio."""

    with pytest.raises(ValueError, match="limited-range"):
        create_frame_extraction_command(Path("ffmpeg"), _probe(tmp_path / "full.mkv", video=_video(color_range="pc")), tmp_path / "frames", Rational(24, 1))
    with pytest.raises(ValueError, match="rotated"):
        create_frame_extraction_command(Path("ffmpeg"), _probe(tmp_path / "rotated.mkv", video=_video(color_range="tv", rotation=90)), tmp_path / "frames", Rational(24, 1))
    silent_merged = _probe(tmp_path / "merged.mkv", video=_video(color_range="tv"))
    with pytest.raises(ValueError, match="audio presence"):
        create_frame_extraction_plan(_job((silent_merged,), ConcatStrategy.STREAM_COPY, "stereo"), Path("ffmpeg"), silent_merged, tmp_path)


def test_manifest_preserves_order_and_escapes_apostrophes(tmp_path: Path) -> None:
    """Concat tokens cannot be split by spaces or an embedded apostrophe."""

    first = tmp_path / "one clip.mkv"
    second = tmp_path / "director's cut.mkv"
    text = concat_manifest_text((first, second))

    assert text.index("one clip.mkv") < text.index("director")
    assert "director'\\''s cut.mkv" in text
    with pytest.raises(ValueError, match="newline"):
        concat_manifest_text((Path("bad\nname.mkv"),))


def test_preparation_plan_normalizes_every_clip_before_one_concat(tmp_path: Path) -> None:
    """One incompatible clip changes the whole set to a common intermediate."""

    first = _probe(Path("one.mp4"))
    second = _probe(Path("two.mp4"), video=_video(width=1280, height=720))
    plan = create_media_preparation_plan(_job((first, second), ConcatStrategy.NORMALIZE, None), Path("ffmpeg"), tmp_path)

    assert len(plan.normalization_commands) == 2
    assert plan.concat_inputs[0].name == "clip-000001.mkv"
    assert plan.concat_inputs[1].name == "clip-000002.mkv"
    assert plan.concat_command[-1] == str(tmp_path / "merged.mkv")


def test_preparation_plan_keeps_compatible_sources_for_stream_copy(tmp_path: Path) -> None:
    """Compatible clips avoid normalization but still enter one concat stage."""

    first = _probe(Path("one.mp4"), video=_video(color_range="tv"))
    second = _probe(Path("two.mp4"), video=_video(color_range="tv"))
    plan = create_media_preparation_plan(_job((first, second), ConcatStrategy.STREAM_COPY, None), Path("ffmpeg"), tmp_path)

    assert not plan.normalization_commands
    assert plan.concat_inputs == (Path("one.mp4"), Path("two.mp4"))
    assert plan.compatibility.stream_copy_safe


def test_preparation_plan_requires_acknowledgement_before_dropping_streams(tmp_path: Path) -> None:
    """Explicit first-stream maps never silently discard a secondary audio stream."""

    audio = _audio()
    probe = _probe(Path("multi.mp4"), audios=(audio, audio))
    with pytest.raises(ValueError, match="requires acknowledgement"):
        create_media_preparation_plan(_job((probe,), ConcatStrategy.NORMALIZE, "stereo"), Path("ffmpeg"), tmp_path)
    accepted = create_media_preparation_plan(_job((probe,), ConcatStrategy.NORMALIZE, "stereo", acknowledge_dropped_streams=True), Path("ffmpeg"), tmp_path)
    assert len(accepted.normalization_commands) == 1
