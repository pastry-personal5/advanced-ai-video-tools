"""End-to-end Phase 6 pipelines over real FFmpeg with fake AI backends.

The real preflight, tool discovery, runner protocol parser, executors, cancellation
adapter, and FFmpeg stages run here. Only the two AI executables are scripted fakes
that scale PNG frames with FFmpeg, so no GPU, model, or download is needed.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from loguru import logger

from advanced_ai_video_tools.core.models import IssueCode, JobRequest, NativeScale, OverwriteMode, PipelineStage, ProcessingPipeline, ProgressEvent, Rational, ToolOverrides
from advanced_ai_video_tools.services.pipeline import PipelineCancelled, PipelineFailed, PipelineService
from advanced_ai_video_tools.services.preflight import PreflightService
from advanced_ai_video_tools.storage.workspaces import WorkspaceManager
from advanced_ai_video_tools.system import spandrel
from advanced_ai_video_tools.system.platform import PlatformInfo
from advanced_ai_video_tools.system.processes import CancellationToken, ProcessResult, SubprocessRunner
from advanced_ai_video_tools.system.tools import ToolDiscovery
from advanced_ai_video_tools.video.probe import FFprobeClient
from tests.test_ffmpeg_integration import _generate_source, _write_fake_upscaler

pytestmark = pytest.mark.integration

_RUNNER_SCRIPT = """#!/usr/bin/env python3
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import time

FFMPEG = "@FFMPEG@"
LOG = pathlib.Path("@LOG@")
CONTROL = pathlib.Path("@CONTROL@")
arguments = sys.argv[1:]
if arguments[:1] == ["--help"]:
    print("usage: spandrel-runner [inspect|run]")
    raise SystemExit(0)
command = arguments[0]
model = pathlib.Path(arguments[arguments.index("--model") + 1]).resolve()
scale = 3 if "x3" in model.name else 2


def identity(path):
    stat = path.stat()
    return {"path": str(path.resolve()), "device": stat.st_dev, "inode": stat.st_ino, "size_bytes": stat.st_size, "modified_ns": stat.st_mtime_ns, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


if command == "inspect":
    print(json.dumps({
        "protocol_version": 1, "runner_version": "fake-1", "model_identity": identity(model), "architecture": "FakeSR",
        "purpose": "SR", "input_channels": 3, "output_channels": 3, "scale": scale,
        "size_requirements": {"minimum": 1, "multiple_of": 1, "square": False},
        "maximum_input_pixels": 16777216, "device": "mps", "precision": "float32",
    }))
    raise SystemExit(0)

manifest = json.loads(pathlib.Path(arguments[arguments.index("--manifest") + 1]).read_text())
with LOG.open("a") as handle:
    handle.write(json.dumps({"scale": scale, "model": model.name, "frames": len(manifest["jobs"])}) + "\\n")
if (CONTROL / f"fail-{scale}x").exists():
    sys.stderr.write(json.dumps({"event": "error", "code": "inference_failed", "message": "MPS inference failed for the test"}) + "\\n")
    raise SystemExit(5)
for index, job in enumerate(manifest["jobs"]):
    source, destination = job["input"]["path"], job["output"]["path"]
    result = subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", source, "-vf", f"scale=iw*{scale}:ih*{scale}:flags=neighbor,format=rgb24", "-frames:v", "1", destination], capture_output=True, text=True)
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        raise SystemExit(5)
    if index == 0 and (CONTROL / f"hold-{scale}x").exists():
        (CONTROL / "holding").write_text("held")
        time.sleep(60)
"""


class _IntegrationDiscovery(ToolDiscovery):
    """Real discovery and protocol parsing, minus the host GPU smoke test."""

    def _validate_realesrgan_backend(self, executable: Path, model_directory: Path) -> None:
        """The scripted Real-ESRGAN stand-in has no Vulkan device to smoke-test."""


@dataclass
class _Environment:
    """Everything a Phase 6 pipeline test needs, rooted in one temporary directory."""

    root: Path
    ffmpeg: Path
    ffprobe: Path
    tools: ToolOverrides
    realesrgan_log: Path
    runner_log: Path
    control: Path
    manager: WorkspaceManager
    service: PipelineService
    preflight: PreflightService

    def realesrgan_calls(self) -> list[list[str]]:
        """Return every recorded Real-ESRGAN invocation."""

        return [json.loads(line) for line in self.realesrgan_log.read_text(encoding="utf-8").splitlines()] if self.realesrgan_log.exists() else []

    def runner_calls(self) -> list[dict[str, object]]:
        """Return every recorded Spandrel `run` invocation."""

        return [json.loads(line) for line in self.runner_log.read_text(encoding="utf-8").splitlines()] if self.runner_log.exists() else []


def _environment(tmp_path: Path, *, defaults: bool = False) -> _Environment:
    """Build the environment; `defaults` configures no runner or model, leaving the factory defaults."""

    ffmpeg_name = shutil.which("ffmpeg")
    ffprobe_name = shutil.which("ffprobe")
    if ffmpeg_name is None or ffprobe_name is None:
        pytest.skip("FFmpeg and FFprobe are required for integration tests")
    ffmpeg, ffprobe = Path(ffmpeg_name), Path(ffprobe_name)
    realesrgan_log, runner_log, control = tmp_path / "realesrgan.jsonl", tmp_path / "runner.jsonl", tmp_path / "control"
    control.mkdir()
    realesrgan = tmp_path / "fake-realesrgan-ncnn-vulkan"
    _write_fake_upscaler(realesrgan, ffmpeg, realesrgan_log)
    models = tmp_path / "models"
    models.mkdir()
    (models / "realesrgan-x4plus.param").touch()
    (models / "realesrgan-x4plus.bin").touch()
    runner = tmp_path / "fake-spandrel-runner"
    runner.write_text(_RUNNER_SCRIPT.replace("@FFMPEG@", str(ffmpeg)).replace("@LOG@", str(runner_log)).replace("@CONTROL@", str(control)), encoding="utf-8")
    runner.chmod(0o755)
    model_2x, model_3x = tmp_path / "DAT_x2.safetensors", tmp_path / "DAT_x3.safetensors"
    model_2x.write_bytes(b"fake 2x weights")
    model_3x.write_bytes(b"fake 3x weights")
    if defaults:
        for default_scale, default_name in spandrel.DEFAULT_SPANDREL_MODELS.items():
            (models / default_name).write_bytes(f"fake default {default_scale}x weights".encode())
    manager = WorkspaceManager(tmp_path / "jobs")
    preflight = PreflightService(
        tool_discovery=_IntegrationDiscovery(default_spandrel_runner=runner) if defaults else _IntegrationDiscovery(),
        platform_provider=lambda: PlatformInfo("Darwin", "arm64", "26.5.2"),
        prober_factory=lambda tools: FFprobeClient(tools.ffprobe.path),
        clock=lambda: datetime(2026, 8, 21, tzinfo=timezone.utc),
        workspace_root_provider=lambda: manager.root,
        free_space_provider=lambda _path: 10**12,
    )
    tools = ToolOverrides(ffmpeg, ffprobe, realesrgan, models) if defaults else ToolOverrides(ffmpeg, ffprobe, realesrgan, models, runner, model_2x, model_3x)
    return _Environment(tmp_path, ffmpeg, ffprobe, tools, realesrgan_log, runner_log, control, manager, PipelineService(preflight=preflight, workspace_manager=manager), preflight)


def _clips(env: _Environment, suffix: str = ".mp4", count: int = 2) -> tuple[Path, ...]:
    clips = tuple(env.root / f"clip-{index}{suffix}" for index in range(count))
    for clip in clips:
        _generate_source(env.ffmpeg, clip, Decimal("0.4"))
    return clips


def _request(env: _Environment, clips: tuple[Path, ...], output: Path | None = None, **changes: object) -> JobRequest:
    return JobRequest(clips, env.root, explicit_output_path=output, tools=env.tools, **changes)  # type: ignore[arg-type]


def _final_size(result_probe: object) -> tuple[int, int]:
    video = result_probe.primary_video  # type: ignore[attr-defined]
    return video.width, video.height


@pytest.mark.parametrize(("scale", "expected_size"), [(2, (128, 72)), (3, (192, 108)), (4, (256, 144))])
def test_native_upscale_runs_the_selected_backend_once_even_without_a_target_height(tmp_path: Path, scale: int, expected_size: tuple[int, int]) -> None:
    """Native 2x/3x use the Spandrel runner; native 4x uses Real-ESRGAN; height is ignored."""

    env = _environment(tmp_path)
    output = tmp_path / "native.mp4"
    result = env.service.execute_pipeline(_request(env, _clips(env, count=1), output, pipeline=ProcessingPipeline.NATIVE, native_scale=NativeScale(scale), target_height=1))

    assert _final_size(result.finalization.output_probe) == expected_size
    assert result.preflight.plan is not None and result.preflight.plan.ai_scale == scale
    if scale == 4:
        assert [call[call.index("-s") + 1] for call in env.realesrgan_calls()] == ["4"] and not env.runner_calls()
    else:
        assert [(call["scale"], call["model"]) for call in env.runner_calls()] == [(scale, f"DAT_x{scale}.safetensors")] and not env.realesrgan_calls()
    assert not any(env.manager.root.iterdir())


def test_two_pass_pipeline_runs_2x_then_3x_then_resizes_with_monotonic_pass_progress(tmp_path: Path) -> None:
    """The only multi-pass pipeline invokes AI twice, in order, and resizes once at the end."""

    env = _environment(tmp_path)
    events: list[ProgressEvent] = []
    result = env.service.execute_pipeline(_request(env, _clips(env, count=1), tmp_path / "two-pass.mp4", pipeline=ProcessingPipeline.TWO_X_THREE_X_RESIZE, target_height=144), progress=events.append)

    assert [(call["scale"], call["frames"]) for call in env.runner_calls()] == [(2, 4), (3, 4)]
    assert not env.realesrgan_calls()
    assert _final_size(result.finalization.output_probe) == (256, 144)
    plan = result.preflight.plan
    assert plan is not None and [(item.input_width, item.output_width) for item in plan.upscale_passes] == [(64, 128), (128, 384)]
    upscale = [event for event in events if event.stage is PipelineStage.UPSCALE]
    assert [event.completed for event in upscale] == sorted(event.completed for event in upscale)
    assert upscale[0].completed == 0 and upscale[-1].completed == upscale[-1].total == 8
    assert {event.pass_index for event in upscale} == {1, 2} and {event.pass_count for event in upscale} == {2}
    assert all(event.pass_index == 2 for event in upscale if event.upscaled_preview_image_path is not None)


def test_four_x_then_resize_runs_realesrgan_once_and_resizes_to_the_desired_height(tmp_path: Path) -> None:
    """The explicit 4x pipeline resizes the 4x result, not the source, to the desired height."""

    env = _environment(tmp_path)
    result = env.service.execute_pipeline(_request(env, _clips(env, count=1), tmp_path / "four.mp4", pipeline=ProcessingPipeline.FOUR_X_RESIZE, target_height=108))

    assert [call[call.index("-s") + 1] for call in env.realesrgan_calls()] == ["4"]
    assert not env.runner_calls()
    assert _final_size(result.finalization.output_probe) == (192, 108)


@pytest.mark.parametrize("pipeline", [ProcessingPipeline.FOUR_X_RESIZE, ProcessingPipeline.TWO_X_THREE_X_RESIZE])
def test_resize_pipeline_skips_ai_when_the_source_is_tall_enough_and_needs_no_ai_tool(tmp_path: Path, pipeline: ProcessingPipeline) -> None:
    """A skip resizes only; it neither launches nor requires any AI backend."""

    env = _environment(tmp_path)
    tools = ToolOverrides(env.ffmpeg, env.ffprobe)
    events: list[ProgressEvent] = []
    request = JobRequest(_clips(env, count=1), env.root, explicit_output_path=tmp_path / "skip.mp4", tools=tools, pipeline=pipeline, target_height=36)

    result = env.service.execute_pipeline(request, progress=events.append)

    assert not env.realesrgan_calls() and not env.runner_calls()
    assert result.preflight.plan is not None and result.preflight.plan.upscale_passes == ()
    assert result.preflight.toolchain is not None and result.preflight.toolchain.realesrgan is None and result.preflight.toolchain.spandrel_runner is None
    assert _final_size(result.finalization.output_probe) == (64, 36)
    assert any("not required" in event.message for event in events if event.stage is PipelineStage.UPSCALE)


def test_height_above_the_pipeline_ceiling_is_rejected_before_any_work(tmp_path: Path) -> None:
    """Desired heights beyond the native 4x or 6x result are errors, never enlargements."""

    env = _environment(tmp_path)
    for pipeline, height in ((ProcessingPipeline.FOUR_X_RESIZE, 146), (ProcessingPipeline.TWO_X_THREE_X_RESIZE, 218)):
        report = env.preflight.execute_preflight(_request(env, _clips(env, count=1), tmp_path / "too-tall.mp4", pipeline=pipeline, target_height=height))
        assert not report.ready and IssueCode.UPSCALE_LIMIT in {issue.code for issue in report.issues}
    assert not env.realesrgan_calls() and not env.runner_calls()


@pytest.mark.parametrize("suffix", [".mp4", ".mov"])
def test_concat_only_stream_copies_without_normalizing_extracting_or_encoding(tmp_path: Path, suffix: str) -> None:
    """Concat only publishes the first clip's container with the original codecs and no AI."""

    env = _environment(tmp_path)
    commands: list[tuple[str, ...]] = []

    class Recorder(SubprocessRunner):
        """Record each external command before running it."""

        def run(self, command: Sequence[str], cancellation: CancellationToken, timeout_seconds: float) -> ProcessResult:
            """Capture the exact argument array."""

            commands.append(tuple(command))
            return super().run(command, cancellation, timeout_seconds)

    service = PipelineService(preflight=env.preflight, workspace_manager=env.manager, process_runner=Recorder())
    events: list[ProgressEvent] = []
    result = service.execute_pipeline(_request(env, _clips(env, suffix), pipeline=ProcessingPipeline.CONCAT, target_height=1), progress=events.append)

    assert result.output_path.suffix == suffix and result.output_path.parent == tmp_path
    video, audio = result.finalization.output_probe.primary_video, result.finalization.output_probe.primary_audio
    assert video is not None and audio is not None and (video.codec_name, audio.codec_name, video.width, video.height) == ("h264", "aac", 64, 36)
    assert video.real_frame_rate == Rational(10, 1)
    assert len(commands) == 1 and "-c" in commands[0] and commands[0][commands[0].index("-c") + 1] == "copy"
    assert not {"-vf", "-filter_complex", "-c:v", "-c:a", "libx264"}.intersection(commands[0])
    assert not env.realesrgan_calls() and not env.runner_calls()
    assert not any(env.manager.root.iterdir()) and not tuple(tmp_path.glob(f".*.partial{suffix}"))
    assert PipelineStage.EXTRACT not in {event.stage for event in events} and PipelineStage.ENCODE not in {event.stage for event in events}


def test_concat_only_refuses_clips_that_would_need_normalization(tmp_path: Path) -> None:
    """Differing frame rates fail with the exact normalization reason instead of re-encoding."""

    env = _environment(tmp_path)
    slow, fast = tmp_path / "slow.mp4", tmp_path / "fast.mp4"
    _generate_source(env.ffmpeg, slow, Decimal("0.4"))
    _generate_source(env.ffmpeg, fast, Decimal("0.4"))
    other = tmp_path / "other-rate.mp4"
    result = SubprocessRunner().run((str(env.ffmpeg), "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", str(fast), "-vf", "fps=12", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "copy", str(other)), CancellationToken(), 30)
    assert isinstance(result, ProcessResult) and result.returncode == 0

    report = env.preflight.execute_preflight(_request(env, (slow, other), pipeline=ProcessingPipeline.CONCAT))

    assert not report.ready
    reasons = [issue.message for issue in report.issues if issue.code is IssueCode.NORMALIZATION_REQUIRED]
    assert reasons and any("frame rate" in reason.lower() for reason in reasons)


def test_failure_in_the_second_pass_retains_the_workspace_and_the_previous_output(tmp_path: Path) -> None:
    """A model failure is reported with the runner's code and never replaces the old file."""

    env = _environment(tmp_path)
    (env.control / "fail-3x").write_text("fail")
    output = tmp_path / "previous.mp4"
    output.write_bytes(b"previous complete output")

    with pytest.raises(PipelineFailed) as captured:
        env.service.execute_pipeline(_request(env, _clips(env, count=1), output, pipeline=ProcessingPipeline.TWO_X_THREE_X_RESIZE, target_height=144))

    assert captured.value.stage is PipelineStage.UPSCALE
    assert "pass 2" in str(captured.value) and "inference_failed" in str(captured.value)
    assert [call["scale"] for call in env.runner_calls()] == [2, 3]
    assert output.read_bytes() == b"previous complete output"
    assert captured.value.workspace_path is not None and captured.value.workspace_path.is_dir()


def test_cancelling_the_second_pass_terminates_the_runner_cleans_up_and_keeps_the_old_output(tmp_path: Path) -> None:
    """Cancellation reaches the runner's process group during pass two and removes owned state."""

    env = _environment(tmp_path)
    (env.control / "hold-3x").write_text("hold")
    output = tmp_path / "previous.mp4"
    output.write_bytes(b"previous complete output")
    token = CancellationToken()

    def cancel_when_held() -> None:
        for _ in range(600):
            if (env.control / "holding").exists():
                token.cancel()
                return
            threading.Event().wait(0.05)

    watcher = threading.Thread(target=cancel_when_held)
    watcher.start()
    with pytest.raises(PipelineCancelled):
        env.service.execute_pipeline(_request(env, _clips(env, count=1), output, pipeline=ProcessingPipeline.TWO_X_THREE_X_RESIZE, target_height=144), cancellation=token)
    watcher.join()

    assert [call["scale"] for call in env.runner_calls()] == [2, 3]
    assert output.read_bytes() == b"previous complete output"
    assert not any(env.manager.root.iterdir())
    assert not tuple(tmp_path.glob(".*.partial.mp4"))


def test_replaced_model_between_review_and_dequeue_is_rejected(tmp_path: Path) -> None:
    """Authoritative preflight compares the recorded inspection with the model now on disk."""

    env = _environment(tmp_path)
    clips = _clips(env, count=1)
    request = _request(env, clips, tmp_path / "queued.mp4", pipeline=ProcessingPipeline.NATIVE, native_scale=NativeScale.TWO, overwrite_mode=OverwriteMode.REPLACE)
    reviewed = env.preflight.execute_preflight(request)
    assert reviewed.ready and reviewed.toolchain is not None and reviewed.plan is not None
    env.preflight.registry.release(reviewed.plan.output_path)
    queued = JobRequest(**{**request.__dict__, "spandrel_inspections": reviewed.toolchain.spandrel_inspections})

    assert env.preflight.execute_preflight(queued).ready
    env.preflight.registry.release(reviewed.plan.output_path)
    env.tools.model_2x.write_bytes(hashlib.sha256(b"replacement").digest())  # type: ignore[union-attr]

    changed = env.preflight.execute_preflight(queued)

    assert not changed.ready and IssueCode.MODEL_CHANGED in {issue.code for issue in changed.issues}


def test_replaced_default_model_between_review_and_dequeue_is_rejected(tmp_path: Path) -> None:
    """A queued job with a blank model freezes the default checkpoint's reviewed record like any other."""

    env = _environment(tmp_path, defaults=True)
    request = _request(env, _clips(env, count=1), tmp_path / "queued-default.mp4", pipeline=ProcessingPipeline.NATIVE, native_scale=NativeScale.TWO, overwrite_mode=OverwriteMode.REPLACE)
    reviewed = env.preflight.execute_preflight(request)
    assert reviewed.ready and reviewed.toolchain is not None and reviewed.plan is not None
    env.preflight.registry.release(reviewed.plan.output_path)
    queued = JobRequest(**{**request.__dict__, "spandrel_inspections": reviewed.toolchain.spandrel_inspections})
    assert env.tools.model_2x is None and len(queued.spandrel_inspections) == 1

    assert env.preflight.execute_preflight(queued).ready
    env.preflight.registry.release(reviewed.plan.output_path)
    (env.root / "models" / spandrel.DEFAULT_SPANDREL_MODELS[2]).write_bytes(hashlib.sha256(b"replacement").digest())

    changed = env.preflight.execute_preflight(queued)

    assert not changed.ready and IssueCode.MODEL_CHANGED in {issue.code for issue in changed.issues}


@pytest.mark.parametrize("scale", [2, 3])
def test_native_upscale_with_no_runner_or_model_configured_uses_the_factory_defaults(tmp_path: Path, scale: int) -> None:
    """The shared service runs the default launcher with the default checkpoint for the scale."""

    env = _environment(tmp_path, defaults=True)
    result = env.service.execute_pipeline(_request(env, _clips(env, count=1), tmp_path / "default.mp4", pipeline=ProcessingPipeline.NATIVE, native_scale=NativeScale(scale)))

    default_name = spandrel.DEFAULT_SPANDREL_MODELS[scale]
    assert [(call["scale"], call["model"]) for call in env.runner_calls()] == [(scale, default_name)]
    plan = result.preflight.plan
    assert plan is not None and plan.upscale_passes[0].model_path == (env.root / "models" / default_name).resolve()


def test_two_pass_pipeline_with_nothing_configured_uses_both_factory_defaults_in_order(tmp_path: Path) -> None:
    """2x then 3x each resolve their own default checkpoint beside the default launcher."""

    env = _environment(tmp_path, defaults=True)
    env.service.execute_pipeline(_request(env, _clips(env, count=1), tmp_path / "default-two-pass.mp4", pipeline=ProcessingPipeline.TWO_X_THREE_X_RESIZE, target_height=144))

    assert [(call["scale"], call["model"]) for call in env.runner_calls()] == [(2, spandrel.DEFAULT_SPANDREL_MODELS[2]), (3, spandrel.DEFAULT_SPANDREL_MODELS[3])]


def test_preflight_rejects_a_missing_default_model_with_its_path_and_the_override(tmp_path: Path) -> None:
    """A missing default checkpoint is a blocking preflight issue that says how to fix it."""

    env = _environment(tmp_path, defaults=True)
    missing = env.root / "models" / spandrel.DEFAULT_SPANDREL_MODELS[3]
    missing.unlink()

    report = env.preflight.execute_preflight(_request(env, _clips(env, count=1), tmp_path / "missing-default.mp4", pipeline=ProcessingPipeline.NATIVE, native_scale=NativeScale.THREE))

    assert not report.ready
    messages = " ".join(issue.message for issue in report.issues)
    assert str(missing) in messages and "--model-3x" in messages


@pytest.mark.parametrize(("scale", "expected", "absent"), [(2, "DAT_x2.safetensors", "realesrgan-x4plus"), (4, "realesrgan-x4plus", "DAT_x")])
def test_the_upscale_log_names_the_model_each_pass_actually_runs(tmp_path: Path, scale: int, expected: str, absent: str) -> None:
    """A Spandrel pass is never logged under the Real-ESRGAN model name."""

    env = _environment(tmp_path)
    messages: list[str] = []
    sink = logger.add(lambda message: messages.append(message.record["message"]), level="INFO")
    try:
        env.service.execute_pipeline(_request(env, _clips(env, count=1), tmp_path / "logged.mp4", pipeline=ProcessingPipeline.NATIVE, native_scale=NativeScale(scale)))
    finally:
        logger.remove(sink)

    starts = [message for message in messages if message.startswith("Starting AI upscale")]
    assert len(starts) == 1 and expected in starts[0] and absent not in starts[0]
