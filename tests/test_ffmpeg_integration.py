"""Tiny real-FFmpeg tests for stage behavior and full-job composition."""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from ai_video_tools.core.models import ColorMatrix, ColorProfile, ConcatStrategy, JobPlan, JobRequest, JobState, OverwriteMode, PipelineStage, ProgressEvent, Rational, ToolInfo, Toolchain
from ai_video_tools.services.finalization import FinalOutputVerifier, FinalizationExecutor
from ai_video_tools.services.frame_extraction import FrameExtractionExecutor
from ai_video_tools.services.media_preparation import MediaPreparationExecutor, MergedOutputVerifier
from ai_video_tools.services.pipeline import PipelineService
from ai_video_tools.services.preflight import PreflightService
from ai_video_tools.services.upscaling import UpscalingResult
from ai_video_tools.storage.workspaces import WorkspaceManager
from ai_video_tools.system.platform import PlatformInfo
from ai_video_tools.system.processes import SubprocessRunner
from ai_video_tools.video.commands import NormalizationSpec, build_concat_command, build_normalization_command
from ai_video_tools.video.compatibility import effective_frame_rate, frame_rates_equivalent
from ai_video_tools.video.manifest import write_concat_manifest
from ai_video_tools.video.probe import FFprobeClient

BT709_PROFILE = ColorProfile(ColorMatrix.BT709, "bt709", "bt709")
SMPTE170M_PROFILE = ColorProfile(ColorMatrix.SMPTE170M, None, None)


def _run(arguments: tuple[str, ...] | list[str]) -> None:
    result = subprocess.run(arguments, check=False, capture_output=True, text=True, timeout=30, shell=False)
    assert result.returncode == 0, result.stderr


def _generate_source(ffmpeg: Path, output: Path, audio_duration: Decimal | None, *, color_space: str = "bt709", include_transfer_primaries: bool = True) -> None:
    arguments = [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-f", "lavfi", "-i", "testsrc2=size=64x36:rate=10:duration=0.4"]
    if audio_duration is not None:
        arguments.extend(["-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={audio_duration}", "-map", "0:v:0", "-map", "1:a:0"])
    else:
        arguments.extend(["-map", "0:v:0", "-an"])
    matrix_code = "6" if color_space == "smpte170m" else "1"
    bitstream_metadata = f"h264_metadata=video_full_range_flag=0:matrix_coefficients={matrix_code}"
    arguments.extend(["-c:v", "libx264", "-preset", "ultrafast", "-crf", "30", "-pix_fmt", "yuv420p", "-colorspace", color_space, "-color_range", "tv"])
    if include_transfer_primaries:
        arguments.extend(["-color_trc", "bt709", "-color_primaries", "bt709"])
        bitstream_metadata += ":colour_primaries=1:transfer_characteristics=1"
    arguments.extend(["-bsf:v", bitstream_metadata])
    if audio_duration is not None:
        arguments.extend(["-c:a", "aac", "-b:a", "64k"])
    arguments.append(str(output))
    _run(arguments)


def _generate_quantized_prores(ffmpeg: Path, output: Path, width: int) -> None:
    """Create nominal 16 fps MOV media whose 1/600 clock quantizes frame ticks."""

    _run(
        [
            str(ffmpeg),
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=size={width}x36:rate=16",
            "-frames:v",
            "81",
            "-an",
            "-c:v",
            "prores_ks",
            "-profile:v",
            "1",
            "-pix_fmt",
            "yuv422p10le",
            "-colorspace",
            "smpte170m",
            "-color_range",
            "tv",
            "-video_track_timescale",
            "600",
            str(output),
        ]
    )


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


class FixedToolDiscovery:
    """Return real FFmpeg tools and the integration-only fake upscaler."""

    def __init__(self, toolchain: Toolchain) -> None:
        self.toolchain = toolchain

    def discover(self, _overrides: object) -> Toolchain:
        """Return the frozen integration toolchain without a GPU smoke test."""

        return self.toolchain


@pytest.mark.integration
def test_quantized_sixteen_fps_prores_normalizes_concats_and_verifies(tmp_path: Path) -> None:
    """Real MOV and Matroska clocks preserve nominal 16/1 through preparation."""

    ffmpeg_name = shutil.which("ffmpeg")
    ffprobe_name = shutil.which("ffprobe")
    if ffmpeg_name is None or ffprobe_name is None:
        pytest.skip("FFmpeg and FFprobe are required for integration tests")
    ffmpeg = Path(ffmpeg_name)
    prober = FFprobeClient(Path(ffprobe_name))
    sources = (tmp_path / "quantized-first.mov", tmp_path / "quantized-second.mov")
    _generate_quantized_prores(ffmpeg, sources[0], 64)
    _generate_quantized_prores(ffmpeg, sources[1], 66)
    probes = tuple(prober.probe(path) for path in sources)
    first_video = probes[0].primary_video
    assert first_video is not None
    assert first_video.real_frame_rate == Rational(16, 1)
    assert first_video.average_frame_rate != Rational(16, 1)
    assert first_video.time_base == Rational(1, 600)
    assert effective_frame_rate(first_video) == (Rational(16, 1), False)
    job = JobPlan(datetime(2026, 8, 21, tzinfo=timezone.utc), tmp_path / "unused-output.mp4", True, probes, Rational(16, 1), 3840, 2160, 4, ConcatStrategy.NORMALIZE, None, ("dimensions differ",), 100, 120, SMPTE170M_PROFILE)
    manager = WorkspaceManager(tmp_path / "jobs")
    workspace = manager.create()
    executor = MediaPreparationExecutor(manager, SubprocessRunner(), MergedOutputVerifier(prober), command_timeout_seconds=30)

    result = executor.execute_in_workspace(job, ffmpeg, workspace)

    merged_video = result.merged_probe.primary_video
    assert result.normalization_count == 2
    assert merged_video is not None
    assert merged_video.time_base is not None
    merged_rate, variable = effective_frame_rate(merged_video)
    assert not variable
    assert merged_rate == Rational(16, 1)
    assert frame_rates_equivalent(merged_rate, Rational(16, 1), merged_video.time_base)
    manager.cleanup(workspace)


def _write_fake_upscaler(executable: Path, ffmpeg: Path, invocation_log: Path) -> None:
    """Create a directory-mode fake that scales PNGs with the installed FFmpeg."""

    executable.write_text(
        f"""#!/usr/bin/env python3
import json
import pathlib
import subprocess
import sys

arguments = sys.argv[1:]
required = ('-i', '-o', '-m', '-n', '-s', '-t', '-f')
if any(flag not in arguments for flag in required):
    raise SystemExit(8)
if arguments[arguments.index('-n') + 1] != 'realesrgan-x4plus' or arguments[arguments.index('-f') + 1] != 'png':
    raise SystemExit(9)
if any(flag in arguments for flag in ('-g', '-j', '-x')):
    raise SystemExit(10)
input_directory = pathlib.Path(arguments[arguments.index('-i') + 1])
output_directory = pathlib.Path(arguments[arguments.index('-o') + 1])
scale = int(arguments[arguments.index('-s') + 1])
inputs = sorted(input_directory.glob('frame-*.png'))
if not inputs:
    raise SystemExit(11)
with pathlib.Path({str(invocation_log)!r}).open('a', encoding='utf-8') as handle:
    handle.write(json.dumps(arguments) + '\\n')
command = [
    {str(ffmpeg)!r}, '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
    '-framerate', '10', '-start_number', '1', '-i', str(input_directory / 'frame-%09d.png'),
    '-vf', f'scale=iw*{{scale}}:ih*{{scale}}:flags=neighbor,format=rgb24',
    '-frames:v', str(len(inputs)), '-start_number', '1', '-c:v', 'png', '-pix_fmt', 'rgb24',
    str(output_directory / 'frame-%09d.png'),
]
result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=30)
sys.stdout.write(result.stdout)
sys.stderr.write(result.stderr)
raise SystemExit(result.returncode)
""",
        encoding="utf-8",
        newline="\n",
    )
    executable.chmod(0o755)


def _full_pipeline_fixture(tmp_path: Path) -> tuple[PipelineService, JobRequest, WorkspaceManager, PreflightService, Path, Path]:
    """Build a real-media job with only its directory upscaler replaced."""

    ffmpeg_name = shutil.which("ffmpeg")
    ffprobe_name = shutil.which("ffprobe")
    if ffmpeg_name is None or ffprobe_name is None:
        pytest.skip("FFmpeg and FFprobe are required for integration tests")
    ffmpeg = Path(ffmpeg_name)
    ffprobe = Path(ffprobe_name)
    sources = (tmp_path / "audio.mp4", tmp_path / "silent.mp4")
    _generate_source(ffmpeg, sources[0], Decimal("0.2"), color_space="smpte170m", include_transfer_primaries=False)
    _generate_source(ffmpeg, sources[1], None, color_space="smpte170m", include_transfer_primaries=False)
    invocation_log = tmp_path / "fake-upscaler-invocations.jsonl"
    fake_upscaler = tmp_path / "fake-realesrgan-ncnn-vulkan"
    _write_fake_upscaler(fake_upscaler, ffmpeg, invocation_log)
    models = tmp_path / "models"
    models.mkdir()
    (models / "realesrgan-x4plus.param").touch()
    (models / "realesrgan-x4plus.bin").touch()
    toolchain = Toolchain(ToolInfo(ffmpeg, "integration"), ToolInfo(ffprobe, "integration"), ToolInfo(fake_upscaler, "integration fake"), models)
    manager = WorkspaceManager(tmp_path / "jobs")
    preflight = PreflightService(
        tool_discovery=FixedToolDiscovery(toolchain),
        platform_provider=lambda: PlatformInfo("Darwin", "arm64", "26.5.2"),
        prober_factory=lambda tools: FFprobeClient(tools.ffprobe.path),
        clock=lambda: datetime(2026, 8, 21, tzinfo=timezone.utc),
        workspace_root_provider=lambda: manager.root,
        free_space_provider=lambda _path: 10**12,
    )
    output = tmp_path / "full-pipeline.mp4"
    output.write_bytes(b"previous complete output")
    request = JobRequest(sources, tmp_path, explicit_output_path=output, target_height=72)
    return PipelineService(preflight=preflight, workspace_manager=manager), request, manager, preflight, output, invocation_log


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
    spec = NormalizationSpec(64, 36, Rational(1, 1), Rational(10, 1), BT709_PROFILE, "mono")
    for probe, output in zip(probes, normalized):
        _run(build_normalization_command(ffmpeg, probe, output, spec))

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
    job = JobPlan(datetime(2026, 8, 21, tzinfo=timezone.utc), tmp_path / "unused-output.mp4", True, probes, Rational(10, 1), 3840, 2160, 4, ConcatStrategy.NORMALIZE, "mono", ("audio timelines require normalization",), 100, 120, BT709_PROFILE)
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


@pytest.mark.integration
def test_caller_owned_preparation_extracts_exact_rgb_frame_sequence(tmp_path: Path) -> None:
    """A retained merged timeline becomes one verified RGB PNG sequence."""

    ffmpeg_name = shutil.which("ffmpeg")
    ffprobe_name = shutil.which("ffprobe")
    if ffmpeg_name is None or ffprobe_name is None:
        pytest.skip("FFmpeg and FFprobe are required for integration tests")
    ffmpeg = Path(ffmpeg_name)
    ffprobe = Path(ffprobe_name)
    sources = (tmp_path / "first.mp4", tmp_path / "second.mp4")
    _generate_source(ffmpeg, sources[0], Decimal("0.2"))
    _generate_source(ffmpeg, sources[1], None)
    prober = FFprobeClient(ffprobe)
    probes = tuple(prober.probe(path) for path in sources)
    job = JobPlan(datetime(2026, 8, 21, tzinfo=timezone.utc), tmp_path / "unused-output.mp4", True, probes, Rational(10, 1), 3840, 2160, 4, ConcatStrategy.NORMALIZE, "mono", ("audio timelines require normalization",), 100, 120, BT709_PROFILE)
    manager = WorkspaceManager(tmp_path / "jobs")
    workspace = manager.create()
    runner = SubprocessRunner()
    preparation = MediaPreparationExecutor(manager, runner, MergedOutputVerifier(prober), command_timeout_seconds=30)
    extraction = FrameExtractionExecutor(manager, runner, command_timeout_seconds=30)

    prepared = preparation.execute_in_workspace(job, ffmpeg, workspace)
    extracted = extraction.execute(prepared, job, ffmpeg, workspace=workspace)

    assert prepared.merged_probe.path.is_file()
    assert extracted.frame_count == 8
    assert extracted.expected_frame_count == 8
    assert extracted.audio_source_path == prepared.merged_probe.path
    assert (extracted.frames_directory / "frame-000000001.png").is_file()
    assert (extracted.frames_directory / "frame-000000008.png").is_file()
    assert len(tuple(extracted.frames_directory.iterdir())) == 8
    manager.cleanup(workspace)
    assert not workspace.path.exists()


@pytest.mark.integration
def test_terminal_pipeline_encodes_verifies_atomically_replaces_and_cleans(tmp_path: Path) -> None:
    """Real frames and normalized audio become one verified quality-first MP4."""

    ffmpeg_name = shutil.which("ffmpeg")
    ffprobe_name = shutil.which("ffprobe")
    if ffmpeg_name is None or ffprobe_name is None:
        pytest.skip("FFmpeg and FFprobe are required for integration tests")
    ffmpeg = Path(ffmpeg_name)
    ffprobe = Path(ffprobe_name)
    sources = (tmp_path / "audio.mp4", tmp_path / "silent.mp4")
    _generate_source(ffmpeg, sources[0], Decimal("0.2"))
    _generate_source(ffmpeg, sources[1], None)
    prober = FFprobeClient(ffprobe)
    probes = tuple(prober.probe(path) for path in sources)
    output = tmp_path / "ai-video-integration.mp4"
    output.write_bytes(b"previous complete output")
    job = JobPlan(datetime(2026, 8, 21, tzinfo=timezone.utc), output, False, probes, Rational(10, 1), 64, 36, None, ConcatStrategy.NORMALIZE, "mono", ("audio timelines require normalization",), 100, 120, BT709_PROFILE)
    toolchain = Toolchain(ToolInfo(ffmpeg, "integration"), ToolInfo(ffprobe, "integration"), ToolInfo(Path("realesrgan-ncnn-vulkan"), "unused"), tmp_path / "models")
    manager = WorkspaceManager(tmp_path / "jobs")
    workspace = manager.create()
    runner = SubprocessRunner()
    preparation = MediaPreparationExecutor(manager, runner, MergedOutputVerifier(prober), command_timeout_seconds=30)
    extraction = FrameExtractionExecutor(manager, runner, command_timeout_seconds=30)
    finalization = FinalizationExecutor(manager, runner, FinalOutputVerifier(prober), command_timeout_seconds=30)

    prepared = preparation.execute_in_workspace(job, ffmpeg, workspace)
    extracted = extraction.execute(prepared, job, ffmpeg, workspace=workspace)
    upscaled = UpscalingResult(extracted.frames_directory, extracted.frame_pattern, extracted.frame_count, extracted.frame_width, extracted.frame_height, None, True, extracted.audio_source_path, (), workspace.identifier)
    result = finalization.execute(prepared, upscaled, job, toolchain, workspace=workspace)

    assert result.output_path == output
    assert result.output_probe.path == output
    assert result.output_probe.primary_video is not None
    assert result.output_probe.primary_video.codec_name == "h264"
    assert result.output_probe.primary_video.pixel_format == "yuv420p"
    assert (result.output_probe.primary_video.width, result.output_probe.primary_video.height) == (64, 36)
    assert result.output_probe.primary_video.real_frame_rate == Rational(10, 1)
    assert result.output_probe.primary_video.color_space == "bt709"
    assert result.output_probe.primary_video.color_transfer == "bt709"
    assert result.output_probe.primary_video.color_primaries == "bt709"
    assert result.output_probe.primary_video.color_range == "tv"
    assert result.output_probe.primary_audio is not None
    assert result.output_probe.primary_audio.codec_name == "aac"
    assert result.output_probe.primary_audio.sample_rate == 48000
    assert output.stat().st_size > len(b"previous complete output")
    assert not workspace.path.exists()


@pytest.mark.integration
def test_full_pipeline_service_runs_concat_first_upscales_once_and_publishes(tmp_path: Path) -> None:
    """One request crosses real preflight and FFmpeg stages with one fake AI pass."""

    service, request, manager, preflight, output, invocation_log = _full_pipeline_fixture(tmp_path)
    states: list[JobState] = []
    events: list[ProgressEvent] = []

    result = service.run(request, progress=events.append, state_changed=states.append)

    assert states == [JobState.QUEUED, JobState.VALIDATING, JobState.RUNNING, JobState.COMPLETED]
    assert result.output_path == output
    assert result.preflight.plan is not None
    assert result.preflight.plan.probes[0].primary_video is not None
    assert result.preflight.plan.probes[0].primary_video.color_space == "smpte170m"
    assert result.preflight.plan.concat_strategy is ConcatStrategy.NORMALIZE
    assert result.preflight.plan.ai_scale == 2
    assert result.preflight.plan.output_color_profile == SMPTE170M_PROFILE
    completed_stages = [event.stage for event in events if event.completed == event.total]
    assert completed_stages.count(PipelineStage.CONCATENATE) == 1
    assert completed_stages.index(PipelineStage.NORMALIZE) < completed_stages.index(PipelineStage.CONCATENATE)
    assert completed_stages.index(PipelineStage.CONCATENATE) < completed_stages.index(PipelineStage.EXTRACT)
    assert completed_stages.index(PipelineStage.EXTRACT) < completed_stages.index(PipelineStage.UPSCALE)
    assert completed_stages.index(PipelineStage.UPSCALE) < completed_stages.index(PipelineStage.ENCODE)
    assert completed_stages[-3:] == [PipelineStage.VERIFY, PipelineStage.PUBLISH, PipelineStage.CLEANUP]

    invocations = [json.loads(line) for line in invocation_log.read_text(encoding="utf-8").splitlines()]
    assert len(invocations) == 1
    arguments = invocations[0]
    assert arguments[arguments.index("-s") + 1] == "2"
    assert arguments[arguments.index("-t") + 1] == "0"
    assert Path(arguments[arguments.index("-i") + 1]).name == "frames"
    assert Path(arguments[arguments.index("-o") + 1]).name == "upscaled"
    assert not {"-g", "-j", "-x"}.intersection(arguments)

    final_probe = result.finalization.output_probe
    assert final_probe.primary_video is not None
    assert final_probe.primary_video.codec_name == "h264"
    assert final_probe.primary_video.pixel_format == "yuv420p"
    assert (final_probe.primary_video.width, final_probe.primary_video.height) == (128, 72)
    assert final_probe.primary_video.real_frame_rate == Rational(10, 1)
    assert (final_probe.primary_video.color_space, final_probe.primary_video.color_transfer, final_probe.primary_video.color_primaries, final_probe.primary_video.color_range) == ("smpte170m", None, None, "tv")
    assert final_probe.primary_audio is not None
    assert final_probe.primary_audio.codec_name == "aac"
    assert final_probe.primary_audio.sample_rate == 48000
    assert final_probe.primary_audio.duration is not None
    assert final_probe.primary_video.duration is not None
    assert abs(final_probe.primary_audio.duration - final_probe.primary_video.duration) <= Decimal("0.08")
    assert output.stat().st_size > len(b"previous complete output")
    assert not any(manager.root.iterdir())
    assert not tuple(tmp_path.glob(".*.partial.mp4"))

    reserved_again = preflight.registry.reserve_explicit(output, OverwriteMode.REPLACE)
    assert reserved_again == output
    preflight.registry.release(reserved_again)
