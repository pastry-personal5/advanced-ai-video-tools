"""Opt-in Phase 6 acceptance on Apple Silicon with the supplied 2x and 3x models.

These checks run the real FFmpeg, the real `spandrel-runner` on MPS, and the
user-supplied `2xPublic_realplksr_dysample_layernorm_real_nn.pth` (2x) and
`DAT_x3_bf16.safetensors` (3x) files. They never run
in the default suite. Enable them with `make phase6-native-test`. The frames are
deliberately tiny to keep the suite short; the 640x360 runs of the selected
checkpoints are recorded in docs/v3/6-customizable-upscaling-pipelines.md.
"""

# Pytest injects fixtures through same-named function parameters.
# pylint: disable=redefined-outer-name

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
from decimal import Decimal
from pathlib import Path

import pytest

from advanced_ai_video_tools.core.models import IssueCode, JobRequest, NativeScale, PipelineStage, ProcessingPipeline, ProgressEvent, ToolOverrides, UpscaleBackend
from advanced_ai_video_tools.services.pipeline import PipelineCancelled, PipelineService
from advanced_ai_video_tools.services.preflight import PreflightService
from advanced_ai_video_tools.storage.workspaces import WorkspaceManager
from advanced_ai_video_tools.system.hardware import apple_silicon_metal_error
from advanced_ai_video_tools.system.processes import CancellationToken
from advanced_ai_video_tools.system.tools import ModelCompatibilityError, ToolDiscovery
from advanced_ai_video_tools.video.probe import FFprobeClient
from tests.test_ffmpeg_integration import _generate_source

pytestmark = pytest.mark.phase6_native

_ENABLE = "ADVANCED_AI_VIDEO_TOOLS_RUN_PHASE6_ACCEPTANCE"
_REPOSITORY = Path(__file__).resolve().parents[1]
_RUNNER = Path(os.environ.get("ADVANCED_AI_VIDEO_TOOLS_SPANDREL_RUNNER", _REPOSITORY / "tools" / "spandrel-runner" / "spandrel-runner"))
_MODEL_2X = Path(os.environ.get("ADVANCED_AI_VIDEO_TOOLS_MODEL_2X", _REPOSITORY / "tools" / "spandrel-runner" / "models" / "2xPublic_realplksr_dysample_layernorm_real_nn.pth"))
_MODEL_3X = Path(os.environ.get("ADVANCED_AI_VIDEO_TOOLS_MODEL_3X", _REPOSITORY / "tools" / "spandrel-runner" / "models" / "DAT_x3_bf16.safetensors"))
_CLI = Path(sys.executable).parent / "advanced-ai-video-tools"


class _Native:
    """Real tools, supplied models, and a private job cache for one test."""

    def __init__(self, root: Path) -> None:
        ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
        if ffmpeg is None or ffprobe is None:
            pytest.skip("FFmpeg and FFprobe are required")
        for required in (_RUNNER, _MODEL_2X, _MODEL_3X):
            if not required.is_file():
                pytest.skip(f"missing Phase 6 acceptance prerequisite: {required}")
        self.root = root
        self.ffmpeg, self.ffprobe = Path(ffmpeg), Path(ffprobe)
        self.tools = ToolOverrides(self.ffmpeg, self.ffprobe, spandrel_runner=_RUNNER, model_2x=_MODEL_2X, model_3x=_MODEL_3X)
        self.manager = WorkspaceManager(root / "jobs")
        self.preflight = PreflightService(workspace_root_provider=lambda: self.manager.root)
        self.service = PipelineService(preflight=self.preflight, workspace_manager=self.manager)

    def clip(self, name: str = "clip.mp4", *, duration: str = "0.3") -> Path:
        """Create one tiny 64x36, 10 fps clip with matching AAC audio."""

        path = self.root / name
        _generate_source(self.ffmpeg, path, Decimal(duration), duration=duration)
        return path

    def request(self, clips: tuple[Path, ...], output: Path | None = None, **changes: object) -> JobRequest:
        """Build a request that uses the supplied runner and models."""

        return JobRequest(clips, self.root, explicit_output_path=output, tools=self.tools, **changes)  # type: ignore[arg-type]

    def probe(self, path: Path):  # type: ignore[no-untyped-def]
        """Probe a published file with the real FFprobe."""

        return FFprobeClient(self.ffprobe).probe(path)


@pytest.fixture()
def native(tmp_path: Path) -> _Native:
    """Skip unless the caller explicitly enabled Phase 6 native acceptance."""

    if os.environ.get(_ENABLE) != "1":
        pytest.skip(f"set {_ENABLE}=1 to run Phase 6 native acceptance")
    error = apple_silicon_metal_error()
    if error is not None:
        pytest.skip(error)
    return _Native(tmp_path)


def test_two_pass_job_with_the_supplied_models_publishes_a_verified_mp4_with_source_audio(native: _Native) -> None:
    """DAT 2x then DAT 3x run on MPS, then one resize, with audio retained through both passes."""

    events: list[ProgressEvent] = []
    result = native.service.execute_pipeline(native.request((native.clip(),), native.root / "two-pass.mp4", pipeline=ProcessingPipeline.TWO_X_THREE_X_RESIZE, target_height=144), progress=events.append)

    plan = result.preflight.plan
    assert plan is not None
    assert [(item.backend, item.scale) for item in plan.upscale_passes] == [(UpscaleBackend.SPANDREL, 2), (UpscaleBackend.SPANDREL, 3)]
    assert [item.inspection.architecture for item in plan.upscale_passes if item.inspection is not None] == ["PLKSR", "DAT"]
    assert all(item.inspection is not None and item.inspection.device == "mps" for item in plan.upscale_passes)
    assert [item.inspection.precision for item in plan.upscale_passes if item.inspection is not None] == ["float32", "bfloat16"]
    video, audio = result.finalization.output_probe.primary_video, result.finalization.output_probe.primary_audio
    assert video is not None and (video.codec_name, video.pixel_format, video.width, video.height) == ("h264", "yuv420p", 256, 144)
    assert audio is not None and audio.codec_name == "aac"
    upscale = [event for event in events if event.stage is PipelineStage.UPSCALE]
    assert [event.completed for event in upscale] == sorted(event.completed for event in upscale)
    assert upscale[-1].completed == upscale[-1].total == 6
    assert not any(native.manager.root.iterdir())


@pytest.mark.parametrize(("scale", "expected"), [(2, (128, 72)), (3, (192, 108))])
def test_native_upscale_with_each_supplied_model(native: _Native, scale: int, expected: tuple[int, int]) -> None:
    """One native pass per supplied model yields the model's exact scale."""

    result = native.service.execute_pipeline(native.request((native.clip(),), native.root / f"native-{scale}.mp4", pipeline=ProcessingPipeline.NATIVE, native_scale=NativeScale(scale), target_height=1))
    video = result.finalization.output_probe.primary_video
    assert video is not None and (video.width, video.height) == expected


def test_cancelling_the_real_second_pass_kills_the_runner_cleans_up_and_keeps_the_old_output(native: _Native) -> None:
    """Cancellation reaches the uv-launched runner's whole process group during pass two."""

    output = native.root / "previous.mp4"
    output.write_bytes(b"previous complete output")
    token = CancellationToken()
    pass_two_started = threading.Event()

    def progress(event: ProgressEvent) -> None:
        # Cancel only after the runner has published a real pass-two frame.
        if event.stage is PipelineStage.UPSCALE and event.pass_index == 2 and event.total is not None and event.completed > event.total // 2:
            pass_two_started.set()
            token.cancel()

    with pytest.raises(PipelineCancelled):
        native.service.execute_pipeline(native.request((native.clip(duration="1.0"),), output, pipeline=ProcessingPipeline.TWO_X_THREE_X_RESIZE, target_height=144), cancellation=token, progress=progress)

    assert pass_two_started.is_set()
    assert output.read_bytes() == b"previous complete output"
    assert not any(native.manager.root.iterdir())
    assert subprocess.run(["pgrep", "-f", str(_RUNNER.parent / "main.py")], check=False, capture_output=True).returncode == 1


def test_runner_and_model_failures_are_actionable_and_never_fall_back(native: _Native, tmp_path: Path) -> None:
    """Pickle, corrupt, wrong-scale, and MPS-unavailable cases fail with stable, specific errors."""

    discovery = ToolDiscovery()
    media = discovery.discover_media(native.tools)

    torchscript = tmp_path / "legacy.pt"
    torchscript.write_bytes(b"not a real checkpoint")
    with pytest.raises(ModelCompatibilityError, match=r"\.safetensors or \.pth"):
        discovery.complete_for_passes(ToolOverrides(native.ffmpeg, native.ffprobe, spandrel_runner=_RUNNER, model_2x=torchscript), media, require_realesrgan=False, spandrel_scales=(2,))

    corrupt_pth = tmp_path / "corrupt.pth"
    corrupt_pth.write_bytes(b"\x00" * 64)
    with pytest.raises(ModelCompatibilityError, match="incompatible_model"):
        discovery.complete_for_passes(ToolOverrides(native.ffmpeg, native.ffprobe, spandrel_runner=_RUNNER, model_2x=corrupt_pth), media, require_realesrgan=False, spandrel_scales=(2,))

    corrupt = tmp_path / "corrupt.safetensors"
    corrupt.write_bytes(b"\x00" * 64)
    with pytest.raises(ModelCompatibilityError, match="incompatible_model"):
        discovery.complete_for_passes(ToolOverrides(native.ffmpeg, native.ffprobe, spandrel_runner=_RUNNER, model_2x=corrupt), media, require_realesrgan=False, spandrel_scales=(2,))

    with pytest.raises(ModelCompatibilityError, match="RGB 2x"):
        discovery.complete_for_passes(ToolOverrides(native.ffmpeg, native.ffprobe, spandrel_runner=_RUNNER, model_2x=_MODEL_3X), media, require_realesrgan=False, spandrel_scales=(2,))

    no_mps = subprocess.run(
        ["uv", "run", "--quiet", "--project", str(_RUNNER.parent), "python", "-c", "import sys; sys.path.insert(0, sys.argv[1]); import main; main.torch.backends.mps.is_available = lambda: False; sys.argv = ['spandrel-runner', *sys.argv[2:]]; main.main()", str(_RUNNER.parent), "inspect", "--model", str(_MODEL_2X), "--protocol-version", "1"],
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
        shell=False,
    )
    assert no_mps.returncode == 4
    assert json.loads(no_mps.stderr.strip().splitlines()[-1])["code"] == "mps_unavailable"
    assert no_mps.stdout == ""


def test_model_replaced_after_review_is_rejected_by_authoritative_preflight(native: _Native, tmp_path: Path) -> None:
    """A real inspection record no longer matches once the model bytes change."""

    model = tmp_path / _MODEL_2X.name
    shutil.copyfile(_MODEL_2X, model)
    tools = ToolOverrides(native.ffmpeg, native.ffprobe, spandrel_runner=_RUNNER, model_2x=model)
    request = native.request((native.clip(),), native.root / "reviewed.mp4", pipeline=ProcessingPipeline.NATIVE, native_scale=NativeScale.TWO)
    request = JobRequest(**{**request.__dict__, "tools": tools})
    reviewed = native.preflight.execute_preflight(request)
    assert reviewed.ready and reviewed.toolchain is not None and reviewed.plan is not None
    native.preflight.registry.release(reviewed.plan.output_path)
    queued = JobRequest(**{**request.__dict__, "spandrel_inspections": reviewed.toolchain.spandrel_inspections})
    with model.open("ab") as handle:
        handle.write(b"\x00")

    report = native.preflight.execute_preflight(queued)

    assert not report.ready
    assert {issue.code for issue in report.issues} & {IssueCode.MODEL_CHANGED, IssueCode.INCOMPATIBLE_MODEL}


@pytest.mark.parametrize("suffix", [".mp4", ".mov"])
def test_cli_concat_only_publishes_stream_copied_mp4_and_mov(native: _Native, suffix: str) -> None:
    """The installed CLI stream-copies the first clip's container without touching the AI backends."""

    clips = (native.clip(f"a{suffix}"), native.clip(f"b{suffix}"))
    destination = native.root / f"cli-concat{suffix}"
    arguments = [str(_CLI), "process", "--pipeline", "concat", "--output-dir", str(native.root), "--output", str(destination), "--json", "--ffmpeg", str(native.ffmpeg), "--ffprobe", str(native.ffprobe)]
    for clip in clips:
        arguments.extend(["--input", str(clip)])
    completed = subprocess.run(arguments, check=False, capture_output=True, text=True, timeout=300, shell=False)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["pipeline"] == "concat" and payload["ai_skipped"] is False and payload["passes"] == []
    video = native.probe(destination).primary_video
    assert video is not None and (video.codec_name, video.width, video.height) == ("h264", 64, 36)
    assert destination.suffix == suffix


def test_cli_native_pipeline_uses_the_supplied_runner_and_model(native: _Native) -> None:
    """The documented CLI flags drive the real runner end to end."""

    destination = native.root / "cli-native.mp4"
    arguments = [str(_CLI), "process", "--pipeline", "native", "--scale", "2", "--input", str(native.clip()), "--output-dir", str(native.root), "--output", str(destination), "--json", "--ffmpeg", str(native.ffmpeg), "--ffprobe", str(native.ffprobe), "--spandrel-runner", str(_RUNNER), "--model-2x", str(_MODEL_2X)]
    completed = subprocess.run(arguments, check=False, capture_output=True, text=True, timeout=900, shell=False)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["pipeline"] == "native" and payload["native_scale"] == 2 and [item["backend"] for item in payload["passes"]] == ["spandrel"]
    video = native.probe(destination).primary_video
    assert video is not None and (video.width, video.height) == (128, 72)
