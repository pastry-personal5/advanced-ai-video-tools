"""Tests for cancellable Real-ESRGAN orchestration and bounded retries."""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from advanced_ai_video_tools.core.models import ColorMatrix, ColorProfile, ConcatStrategy, FileIdentity, JobPlan, PipelineStage, ProcessingPipeline, ProgressEvent, Rational, SpandrelInspection, ToolInfo, Toolchain, UpscaleBackend, UpscalePassPlan
from advanced_ai_video_tools.services.frame_extraction import FrameExtractionResult
from advanced_ai_video_tools.services import upscaling as upscaling_module
from advanced_ai_video_tools.services.upscaling import LIVE_PREVIEW_FRAME_INTERVAL, UpscalingCancelled, UpscalingExecutor, UpscalingFailed
from advanced_ai_video_tools.storage.workspaces import OwnedWorkspace, WorkspaceManager
from advanced_ai_video_tools.system.processes import CancellationToken, ProcessCancelled, ProcessExecutionError, ProcessResult, SubprocessRunner
from advanced_ai_video_tools.upscaling.realesrgan import MEMORY_RETRY_TILE_SIZES, REAL_IMAGE_MODEL
from advanced_ai_video_tools.video.frames import FRAME_FILENAME_TEMPLATE


def _png_header(width: int, height: int) -> bytes:
    return b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + width.to_bytes(4, "big") + height.to_bytes(4, "big") + bytes((8, 2))


def _fixture(tmp_path: Path, *, scale: int | None = 2, output_height: int = 72) -> tuple[WorkspaceManager, OwnedWorkspace, FrameExtractionResult, JobPlan, Toolchain]:
    manager = WorkspaceManager(tmp_path / "jobs")
    workspace = manager.create()
    frames = workspace.path / "frames"
    frames.mkdir()
    for number in range(1, 4):
        (frames / f"frame-{number:09d}.png").write_bytes(_png_header(64, 36))
    audio = workspace.path / "merged.mkv"
    audio.write_bytes(b"media")
    extraction_process = ProcessResult(("ffmpeg",), 0, "", "")
    extracted = FrameExtractionResult(frames, frames / FRAME_FILENAME_TEMPLATE, 3, 3, 64, 36, audio, extraction_process, workspace.identifier)
    models = tmp_path / "models"
    models.mkdir()
    (models / f"{REAL_IMAGE_MODEL}.param").touch()
    (models / f"{REAL_IMAGE_MODEL}.bin").touch()
    generic = ToolInfo(tmp_path / "tool", "version")
    tools = Toolchain(generic, generic, ToolInfo(tmp_path / "realesrgan-ncnn-vulkan", "usage"), models)
    passes = () if scale is None else (UpscalePassPlan(1, UpscaleBackend.REALESRGAN, scale, 64, 36, 64 * scale, 36 * scale, tools.realesrgan.path, models),)  # type: ignore[union-attr]
    job = JobPlan(datetime(2026, 8, 21, tzinfo=timezone.utc), tmp_path / "output.mp4", True, (), Rational(10, 1), 128, output_height, scale, ConcatStrategy.NORMALIZE, "mono", (), 100, 120, ColorProfile(ColorMatrix.BT709, "bt709", "bt709"), upscale_passes=passes)
    return manager, workspace, extracted, job, tools


class RecordingUpscaleRunner:
    """Simulate directory inference, allocation errors, and cancellation."""

    def __init__(self, actions: Sequence[str] = ("success",)) -> None:
        self.actions = list(actions)
        self.commands: list[tuple[str, ...]] = []

    @staticmethod
    def _write_outputs(arguments: tuple[str, ...], *, short: bool = False) -> None:
        input_directory = Path(arguments[arguments.index("-i") + 1])
        output_directory = Path(arguments[arguments.index("-o") + 1])
        scale = int(arguments[arguments.index("-s") + 1])
        inputs = sorted(input_directory.glob("*.png"))
        if short:
            inputs = inputs[:-1]
        for source in inputs:
            (output_directory / source.name).write_bytes(_png_header(64 * scale, 36 * scale))

    def run(self, command: Sequence[str], cancellation: CancellationToken, _timeout_seconds: float) -> ProcessResult:
        """Apply the next scripted backend outcome."""

        arguments = tuple(command)
        self.commands.append(arguments)
        action = self.actions.pop(0)
        output_directory = Path(arguments[arguments.index("-o") + 1])
        if action == "memory":
            (output_directory / "partial.png").write_bytes(b"partial")
            raise ProcessExecutionError(arguments, 1, "", "vkAllocateMemory failed -2")
        if action == "failure":
            raise ProcessExecutionError(arguments, 1, "", "failed to load model")
        if action == "cancel":
            cancellation.cancel()
            raise ProcessCancelled("cancelled", arguments)
        self._write_outputs(arguments, short=action == "short")
        return ProcessResult(arguments, 0, "", "")


def test_upscale_success_uses_one_directory_invocation_and_retains_audio(tmp_path: Path) -> None:
    """One successful AI pass returns verified scaled frames for encoding."""

    manager, workspace, extracted, job, tools = _fixture(tmp_path)
    runner = RecordingUpscaleRunner()
    events: list[ProgressEvent] = []

    result = UpscalingExecutor(manager, runner, command_timeout_seconds=5).execute_upscaling(extracted, job, tools, workspace=workspace, progress=events.append)

    assert not result.skipped
    assert result.scale == 2
    assert result.frame_count == 3
    assert (result.frame_width, result.frame_height) == (128, 72)
    assert result.audio_source_path == extracted.audio_source_path
    assert len(runner.commands) == 1
    assert result.attempts[0].tile_size == 0 and result.attempts[0].succeeded
    assert [(event.stage, event.completed, event.total) for event in events] == [(PipelineStage.UPSCALE, 0, 3), (PipelineStage.UPSCALE, 3, 3)]


def test_upscale_live_preview_uses_the_latest_sixteen_frame_sample(tmp_path: Path) -> None:
    """The queue can receive only completed image samples at fixed intervals."""

    directory = tmp_path / "upscaled"
    directory.mkdir()
    initial_sample = directory / "frame-000000001.png"
    first_sample = directory / "frame-000000016.png"
    latest_sample = directory / "frame-000000032.png"
    initial_sample.write_bytes(_png_header(128, 72))
    first_sample.write_bytes(_png_header(128, 72))
    latest_sample.write_bytes(_png_header(128, 72))

    assert LIVE_PREVIEW_FRAME_INTERVAL == 16
    assert UpscalingExecutor._sampled_preview_frame(directory, 0) is None  # pylint: disable=protected-access
    assert UpscalingExecutor._sampled_preview_frame(directory, 1) == initial_sample  # pylint: disable=protected-access
    assert UpscalingExecutor._sampled_preview_frame(directory, 15) == initial_sample  # pylint: disable=protected-access
    assert UpscalingExecutor._sampled_preview_frame(directory, 16) == first_sample  # pylint: disable=protected-access
    assert UpscalingExecutor._sampled_preview_frame(directory, 31) == first_sample  # pylint: disable=protected-access
    assert UpscalingExecutor._sampled_preview_frame(directory, 32) == latest_sample  # pylint: disable=protected-access


def test_upscale_skip_reuses_verified_extracted_frames_without_process(tmp_path: Path) -> None:
    """Inputs already at target height bypass AI without copying frames."""

    manager, workspace, extracted, job, tools = _fixture(tmp_path, scale=None, output_height=36)
    runner = RecordingUpscaleRunner()

    result = UpscalingExecutor(manager, runner).execute_upscaling(extracted, job, tools, workspace=workspace)

    assert result.skipped
    assert result.scale is None
    assert result.frames_directory == extracted.frames_directory
    assert not result.attempts
    assert not runner.commands
    assert not (workspace.path / "upscaled").exists()


def test_pre_cancelled_skip_is_still_a_cancelled_stage(tmp_path: Path) -> None:
    """A pending cancellation wins even when no external AI process is needed."""

    manager, workspace, extracted, job, tools = _fixture(tmp_path, scale=None, output_height=36)
    token = CancellationToken()
    token.cancel()

    with pytest.raises(UpscalingCancelled, match="before launch"):
        UpscalingExecutor(manager, RecordingUpscaleRunner()).execute_upscaling(extracted, job, tools, workspace=workspace, cancellation=token)


def test_vulkan_memory_failure_retries_after_resetting_only_output(tmp_path: Path) -> None:
    """An allocation error moves from auto to 512 tiles without stale files."""

    manager, workspace, extracted, job, tools = _fixture(tmp_path)
    runner = RecordingUpscaleRunner(("memory", "success"))

    result = UpscalingExecutor(manager, runner).execute_upscaling(extracted, job, tools, workspace=workspace)

    assert [attempt.tile_size for attempt in result.attempts] == [0, 512]
    assert [command[command.index("-t") + 1] for command in runner.commands] == ["0", "512"]
    assert not (result.frames_directory / "partial.png").exists()
    assert extracted.frames_directory.is_dir()


def test_non_memory_failure_does_not_retry_and_preserves_diagnostics(tmp_path: Path) -> None:
    """Configuration and model failures are terminal on their first attempt."""

    manager, workspace, extracted, job, tools = _fixture(tmp_path)
    runner = RecordingUpscaleRunner(("failure",))

    with pytest.raises(UpscalingFailed) as captured:
        UpscalingExecutor(manager, runner).execute_upscaling(extracted, job, tools, workspace=workspace)

    assert len(runner.commands) == 1
    assert captured.value.diagnostic_tail == "failed to load model"
    assert isinstance(captured.value.__cause__, ProcessExecutionError)
    assert len(captured.value.attempts) == 1
    assert workspace.path.is_dir()


def test_memory_retries_are_bounded_and_record_every_attempt(tmp_path: Path) -> None:
    """Persistent allocation failure exhausts the documented finite sequence."""

    manager, workspace, extracted, job, tools = _fixture(tmp_path)
    runner = RecordingUpscaleRunner(("memory",) * 6)

    with pytest.raises(UpscalingFailed) as captured:
        UpscalingExecutor(manager, runner).execute_upscaling(extracted, job, tools, workspace=workspace)

    assert [attempt.tile_size for attempt in captured.value.attempts] == [0, *MEMORY_RETRY_TILE_SIZES]
    assert len(runner.commands) == 6


def test_upscale_output_must_match_the_input_frame_set_exactly(tmp_path: Path) -> None:
    """A missing output frame fails without retrying an unrelated error."""

    manager, workspace, extracted, job, tools = _fixture(tmp_path)
    runner = RecordingUpscaleRunner(("short",))

    with pytest.raises(UpscalingFailed, match="frame count differs"):
        UpscalingExecutor(manager, runner).execute_upscaling(extracted, job, tools, workspace=workspace)

    assert len(runner.commands) == 1


def test_upscale_cancellation_preserves_caller_owned_workspace(tmp_path: Path) -> None:
    """Cancellation is typed and leaves final cleanup to the job owner."""

    manager, workspace, extracted, job, tools = _fixture(tmp_path)
    runner = RecordingUpscaleRunner(("cancel",))

    with pytest.raises(UpscalingCancelled) as captured:
        UpscalingExecutor(manager, runner).execute_upscaling(extracted, job, tools, workspace=workspace)

    assert captured.value.workspace_path == workspace.path
    assert workspace.path.is_dir()
    assert len(captured.value.attempts) == 1


def test_fake_executable_contract_runs_through_cancellable_process_boundary(tmp_path: Path) -> None:
    """The real process adapter can drive a lightweight directory-mode backend."""

    manager, workspace, extracted, job, tools = _fixture(tmp_path)
    executable = tmp_path / "fake-realesrgan"
    executable.write_text(
        """#!/usr/bin/env python3
import pathlib
import sys
arguments = sys.argv[1:]
if any(flag in arguments for flag in ('-g', '-j', '-x')):
    raise SystemExit(9)
required = ('-i', '-o', '-m', '-n', '-s', '-t', '-f')
if any(flag not in arguments for flag in required) or arguments[arguments.index('-n') + 1] != 'realesrgan-x4plus' or arguments[arguments.index('-f') + 1] != 'png':
    raise SystemExit(8)
source_directory = pathlib.Path(arguments[arguments.index('-i') + 1])
output_directory = pathlib.Path(arguments[arguments.index('-o') + 1])
scale = int(arguments[arguments.index('-s') + 1])
for source in source_directory.glob('frame-*.png'):
    data = bytearray(source.read_bytes())
    width = int.from_bytes(data[16:20], 'big') * scale
    height = int.from_bytes(data[20:24], 'big') * scale
    data[16:20] = width.to_bytes(4, 'big')
    data[20:24] = height.to_bytes(4, 'big')
    (output_directory / source.name).write_bytes(data)
""",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    tools = Toolchain(tools.ffmpeg, tools.ffprobe, ToolInfo(executable, "fake"), tools.model_directory)
    job = replace(job, upscale_passes=(replace(job.upscale_passes[0], executable_path=executable),))

    result = UpscalingExecutor(manager, SubprocessRunner(), command_timeout_seconds=5).execute_upscaling(extracted, job, tools, workspace=workspace)

    assert result.frame_count == 3
    assert (result.frame_width, result.frame_height) == (128, 72)


def _spandrel_fixture(tmp_path: Path) -> tuple[WorkspaceManager, OwnedWorkspace, FrameExtractionResult, JobPlan, Toolchain, tuple[Path, Path]]:
    """Build a frozen 2x then 3x Spandrel job over three 64x36 frames."""

    manager, workspace, extracted, legacy_job, tools = _fixture(tmp_path)
    model_2x = tmp_path / "DAT_x2.safetensors"
    model_3x = tmp_path / "DAT_x3.safetensors"
    model_2x.write_bytes(b"2x-model")
    model_3x.write_bytes(b"3x-model")

    def identity(path: Path) -> FileIdentity:
        stat = path.stat()
        return FileIdentity(path.resolve(), stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest())

    def inspection(path: Path, scale: int) -> SpandrelInspection:
        return SpandrelInspection(1, "0.4.0", identity(path), "DAT", "SR", 3, 3, scale, 1, 1, False, 1_000_000, "mps", "float32")

    runner_path = tmp_path / "spandrel-runner"
    passes = (
        UpscalePassPlan(1, UpscaleBackend.SPANDREL, 2, 64, 36, 128, 72, runner_path, model_2x, identity(model_2x), inspection(model_2x, 2)),
        UpscalePassPlan(2, UpscaleBackend.SPANDREL, 3, 128, 72, 384, 216, runner_path, model_3x, identity(model_3x), inspection(model_3x, 3)),
    )
    job = replace(legacy_job, ai_scale=None, pipeline=ProcessingPipeline.TWO_X_THREE_X_RESIZE, upscale_passes=passes)
    return manager, workspace, extracted, job, tools, (model_2x, model_3x)


def _manifest(arguments: Sequence[str]) -> dict[str, object]:
    return json.loads(Path(arguments[arguments.index("--manifest") + 1]).read_text(encoding="utf-8"))


class ManifestRunner:
    """Emulate manifest-driven Spandrel invocations, optionally pausing mid-pass."""

    def __init__(self, *, fail_on_pass: int | None = None, cancel_on_pass: int | None = None, stderr: str = "") -> None:
        self.scales: list[int] = []
        self.manifests: list[dict[str, object]] = []
        self.fail_on_pass = fail_on_pass
        self.cancel_on_pass = cancel_on_pass
        self.stderr = stderr
        self.pause: dict[int, threading.Event] = {}
        self.resume: dict[int, threading.Event] = {}

    def run(self, command: Sequence[str], cancellation: CancellationToken, _timeout_seconds: float) -> ProcessResult:
        """Create every output declared in the runner manifest."""

        arguments = tuple(command)
        manifest = _manifest(arguments)
        scale = 2 if "x2" in arguments[arguments.index("--model") + 1] else 3
        self.scales.append(scale)
        self.manifests.append(manifest)
        index = len(self.scales)
        if index == self.cancel_on_pass:
            cancellation.cancel()
            raise ProcessCancelled("cancelled", arguments)
        if index == self.fail_on_pass:
            raise ProcessExecutionError(arguments, 4, "", self.stderr)
        for position, item in enumerate(manifest["jobs"]):  # type: ignore[arg-type]
            output = item["output"]
            Path(output["path"]).write_bytes(_png_header(output["width"], output["height"]))
            if position == 0 and index in self.pause:
                self.pause[index].set()
                assert self.resume[index].wait(5), "test never released the paused runner"
        return ProcessResult(arguments, 0, "", "")


def test_two_spandrel_passes_use_exact_manifests_and_aggregate_progress(tmp_path: Path) -> None:
    """Ordered Spandrel passes consume manifests and report one progress range."""

    manager, workspace, extracted, job, tools, _models = _spandrel_fixture(tmp_path)
    runner = ManifestRunner()
    events: list[ProgressEvent] = []
    result = UpscalingExecutor(manager, runner).execute_upscaling(extracted, job, tools, workspace=workspace, progress=events.append)
    assert runner.scales == [2, 3]
    assert (result.frame_width, result.frame_height, result.scale) == (384, 216, 6)
    assert [event.completed for event in events] == [0, 3, 3, 6]
    assert [event.pass_scale for event in events] == [2, 2, 3, 3]
    first = runner.manifests[0]
    assert [item["input"]["width"] for item in first["jobs"]] == [64, 64, 64]  # type: ignore[index]
    assert all(Path(item["output"]["path"]).parent == workspace.path / "upscaled-pass-1" for item in first["jobs"])  # type: ignore[index,arg-type]
    second = runner.manifests[1]
    assert all(Path(item["input"]["path"]).parent == workspace.path / "upscaled-pass-1" for item in second["jobs"])  # type: ignore[index,arg-type]


def test_live_progress_is_monotonic_across_passes_and_previews_only_the_final_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Observed frames advance one aggregate range; only the last pass previews a matched frame."""

    monkeypatch.setattr(upscaling_module, "UPSCALE_PROGRESS_POLL_SECONDS", 0.01)
    manager, workspace, extracted, job, tools, _models = _spandrel_fixture(tmp_path)
    runner = ManifestRunner()
    runner.pause = {1: threading.Event(), 2: threading.Event()}
    runner.resume = {1: threading.Event(), 2: threading.Event()}
    events: list[ProgressEvent] = []

    def watch(index: int, aggregate: int) -> None:
        assert runner.pause[index].wait(5)
        deadline = threading.Event()
        for _ in range(500):
            if any(event.completed == aggregate and event.pass_index == index for event in list(events)):
                break
            deadline.wait(0.01)
        runner.resume[index].set()

    watchers = [threading.Thread(target=watch, args=(1, 1)), threading.Thread(target=watch, args=(2, 4))]
    for watcher in watchers:
        watcher.start()
    result = UpscalingExecutor(manager, runner).execute_upscaling(extracted, job, tools, workspace=workspace, progress=events.append)
    for watcher in watchers:
        watcher.join()

    assert result.frame_count == 3
    completed = [event.completed for event in events]
    assert completed == sorted(completed)
    assert 1 in completed and 4 in completed and completed[-1] == 6
    assert all(event.total == 6 for event in events)
    first_pass = [event for event in events if event.pass_index == 1]
    assert all(event.original_preview_image_path is None and event.upscaled_preview_image_path is None for event in first_pass)
    previews = [event for event in events if event.upscaled_preview_image_path is not None]
    assert previews and all(event.pass_index == 2 for event in previews)
    for event in previews:
        assert event.original_preview_image_path is not None
        assert event.original_preview_image_path.name == event.upscaled_preview_image_path.name  # type: ignore[union-attr]
        assert event.original_preview_image_path.parent == extracted.frames_directory
        assert event.upscaled_preview_image_path.parent == workspace.path / "upscaled-pass-2"  # type: ignore[union-attr]


def test_explicit_resize_skip_reports_the_skip_without_launching_or_fabricating_frames(tmp_path: Path) -> None:
    """A frozen empty pass list reuses verified frames and starts no backend."""

    manager, workspace, extracted, job, tools = _fixture(tmp_path, scale=None, output_height=36)
    job = replace(job, pipeline=ProcessingPipeline.FOUR_X_RESIZE)
    runner = RecordingUpscaleRunner()
    events: list[ProgressEvent] = []

    result = UpscalingExecutor(manager, runner).execute_upscaling(extracted, job, tools, workspace=workspace, progress=events.append)

    assert result.skipped and result.scale is None
    assert not runner.commands
    assert [(event.completed, event.total) for event in events] == [(0, 3), (3, 3)]
    assert all(event.pass_index is None for event in events)
    assert not list(workspace.path.glob("upscaled*"))


def test_spandrel_pass_failure_is_actionable_and_does_not_retry(tmp_path: Path) -> None:
    """MPS and model failures surface the runner's stable code once, never retried or run on CPU."""

    manager, workspace, extracted, job, tools, _models = _spandrel_fixture(tmp_path)
    stderr = '{"code": "mps_unavailable", "event": "error", "message": "MPS is unavailable; the runner does not fall back to CPU"}\n'
    runner = ManifestRunner(fail_on_pass=1, stderr=stderr)

    with pytest.raises(UpscalingFailed) as captured:
        UpscalingExecutor(manager, runner).execute_upscaling(extracted, job, tools, workspace=workspace)

    assert runner.scales == [2]
    assert "pass 1" in str(captured.value) and "mps_unavailable" in str(captured.value) and "does not fall back to CPU" in str(captured.value)
    assert captured.value.diagnostic_tail == stderr
    assert len(captured.value.attempts) == 1
    assert workspace.path.is_dir()


def test_cancellation_during_the_second_pass_keeps_the_workspace_and_recorded_attempts(tmp_path: Path) -> None:
    """Cancelling pass two is typed, leaves cleanup to the job owner, and keeps pass one's evidence."""

    manager, workspace, extracted, job, tools, _models = _spandrel_fixture(tmp_path)
    runner = ManifestRunner(cancel_on_pass=2)

    with pytest.raises(UpscalingCancelled) as captured:
        UpscalingExecutor(manager, runner).execute_upscaling(extracted, job, tools, workspace=workspace)

    assert runner.scales == [2, 3]
    assert captured.value.workspace_path == workspace.path
    assert len(captured.value.attempts) == 2
    assert (workspace.path / "upscaled-pass-1").is_dir()


def test_replaced_model_is_rejected_before_the_runner_launches(tmp_path: Path) -> None:
    """The frozen file identity guards against a model replaced after review."""

    manager, workspace, extracted, job, tools, (model_2x, _model_3x) = _spandrel_fixture(tmp_path)
    model_2x.write_bytes(b"different model bytes")
    runner = ManifestRunner()

    with pytest.raises(UpscalingFailed, match="model identity changed"):
        UpscalingExecutor(manager, runner).execute_upscaling(extracted, job, tools, workspace=workspace)

    assert not runner.scales


def test_pass_input_dimensions_must_match_the_verified_inventory(tmp_path: Path) -> None:
    """A plan that disagrees with extraction is rejected instead of guessing."""

    manager, workspace, extracted, job, tools, _models = _spandrel_fixture(tmp_path)
    wrong = replace(job.upscale_passes[0], input_width=66, output_width=132)
    job = replace(job, upscale_passes=(wrong, *job.upscale_passes[1:]))

    with pytest.raises(UpscalingFailed, match="input dimensions"):
        UpscalingExecutor(manager, ManifestRunner()).execute_upscaling(extracted, job, tools, workspace=workspace)
