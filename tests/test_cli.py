"""Tests for the thin command-line presentation adapter."""

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import pytest

from advanced_ai_video_tools import cli
from advanced_ai_video_tools.core.models import (
    ColorMatrix,
    ColorProfile,
    ConcatStrategy,
    IssueCode,
    IssueSeverity,
    JobPlan,
    JobRequest,
    MediaProbe,
    NativeScale,
    PipelineStage,
    PreflightIssue,
    PreflightReport,
    ProcessingPipeline,
    Rational,
    UpscaleBackend,
    UpscalePassPlan,
)
from advanced_ai_video_tools.services.finalization import FinalizationResult
from advanced_ai_video_tools.services.pipeline import PipelineCancelled, PipelineFailed, PipelineResult
from advanced_ai_video_tools.system.processes import ProcessResult
from advanced_ai_video_tools.video.finalization import FinalAudioMode


@pytest.fixture(autouse=True)
def _isolated_logging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep CLI bootstrap diagnostics inside the test boundary."""

    monkeypatch.setattr(cli, "configure_logging", lambda **_kwargs: None)
    monkeypatch.setattr(cli, "current_log_path", lambda: tmp_path / "advanced-ai-video-tools.log")


class FakeRegistry:
    """Record release of a diagnostic-only output reservation."""

    def __init__(self) -> None:
        self.released: list[Path] = []

    def release(self, path: Path) -> None:
        """Record one released destination."""

        self.released.append(path)


class FakeService:
    """Return one prepared report without touching host tools."""

    def __init__(self, report: PreflightReport) -> None:
        self.report = report
        self.registry = FakeRegistry()
        self.request: JobRequest | None = None

    def execute_preflight(self, request: JobRequest) -> PreflightReport:
        """Capture parsed job intent and return the report."""

        self.request = request
        return self.report


class FakePipelineService:
    """Return or raise one configured full-job outcome."""

    def __init__(self, outcome: PipelineResult | Exception) -> None:
        self.outcome = outcome
        self.request: JobRequest | None = None

    def execute_pipeline(self, request: JobRequest, **_kwargs) -> PipelineResult:
        """Capture CLI intent and resolve the configured terminal result."""

        self.request = request
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def _plan(output: Path, *, pipeline: ProcessingPipeline = ProcessingPipeline.AUTO, passes: tuple[UpscalePassPlan, ...] | None = None) -> JobPlan:
    if passes is None:
        passes = (UpscalePassPlan(1, UpscaleBackend.REALESRGAN, 2, 1920, 1080, 3840, 2160, output.parent / "realesrgan", output.parent / "models"),)
    return JobPlan(
        created_at=datetime(2026, 8, 21, tzinfo=timezone.utc),
        output_path=output,
        generated_output_name=True,
        probes=(),
        output_frame_rate=Rational(24, 1),
        output_width=3840,
        output_height=2160,
        ai_scale=math.prod(item.scale for item in passes) if passes else None,
        concat_strategy=ConcatStrategy.STREAM_COPY,
        output_audio_layout=None,
        normalization_reasons=(),
        estimated_peak_bytes=100,
        required_free_bytes=120,
        output_color_profile=ColorProfile(ColorMatrix.BT709, "bt709", "bt709"),
        pipeline=pipeline,
        upscale_passes=passes,
    )


def _processing_result(output: Path) -> PipelineResult:
    plan = _plan(output)
    report = PreflightReport((), plan, None)
    probe = MediaProbe(output, None, (), (), ())
    process = ProcessResult(("ffmpeg",), 0, "", "")
    return PipelineResult(report, FinalizationResult(output, probe, FinalAudioMode.NONE, process, "workspace"))


def test_json_cli_reports_plan_and_releases_reservation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Successful diagnostic output is machine-readable and not held afterward."""

    output = tmp_path / "ai-video.mp4"
    service = FakeService(PreflightReport((), _plan(output), None))
    monkeypatch.setattr(cli, "PreflightService", lambda: service)

    result = cli.main(
        [
            "preflight",
            "--input",
            str(tmp_path / "clip.mp4"),
            "--output-dir",
            str(tmp_path),
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload["ready"] is True
    assert payload["plan"]["concat_strategy"] == "stream_copy"
    assert service.registry.released == [output]
    assert service.request is not None
    assert service.request.target_height == 2160


def test_cli_freezes_allow_mixed_color_tags_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """The opt-in is explicit and defaults to strict behavior elsewhere."""

    output = tmp_path / "ai-video.mp4"
    service = FakeService(PreflightReport((), _plan(output), None))
    monkeypatch.setattr(cli, "PreflightService", lambda: service)

    assert cli.main(["preflight", "--input", str(tmp_path / "clip.mp4"), "--output-dir", str(tmp_path), "--allow-mixed-color-tags"]) == 0
    capsys.readouterr()
    assert service.request is not None and service.request.allow_mixed_color_tags


def test_cli_freezes_phase6_pipeline_scale_and_spandrel_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Phase 6 CLI values reach the typed request without reinterpretation."""

    output = tmp_path / "ai-video.mp4"
    service = FakeService(PreflightReport((), _plan(output), None))
    monkeypatch.setattr(cli, "PreflightService", lambda: service)
    runner = tmp_path / "spandrel-runner"
    model = tmp_path / "DAT_x2.safetensors"

    assert cli.main(["preflight", "--input", str(tmp_path / "clip.mp4"), "--output-dir", str(tmp_path), "--pipeline", "native", "--scale", "2", "--spandrel-runner", str(runner), "--model-2x", str(model)]) == 0
    capsys.readouterr()
    assert service.request is not None
    assert service.request.pipeline is ProcessingPipeline.NATIVE
    assert service.request.native_scale is NativeScale.TWO
    assert service.request.tools.spandrel_runner == runner
    assert service.request.tools.model_2x == model


def test_cli_rejects_scale_and_spandrel_flags_outside_applicable_pipeline(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Pipeline-specific flags fail fast when their pipeline cannot use them."""

    base = ["preflight", "--input", str(tmp_path / "clip.mp4"), "--output-dir", str(tmp_path)]
    assert cli.main([*base, "--scale", "2"]) == 2
    assert "only with --pipeline native" in capsys.readouterr().err
    assert cli.main([*base, "--spandrel-runner", str(tmp_path / "runner")]) == 2
    assert "valid only for a pipeline" in capsys.readouterr().err


def test_cli_help_names_the_spandrel_factory_defaults(capsys: pytest.CaptureFixture[str]) -> None:
    """The flags that can be omitted say what an omitted value means."""

    with pytest.raises(SystemExit) as caught:
        cli.main(["preflight", "--help"])

    assert caught.value.code == 0
    flat = "".join(capsys.readouterr().out.split())
    assert "tools/spandrel-runner/spandrel-runner" in flat and "PATHisneversearched" in flat
    assert "2xPublic_realplksr_dysample_layernorm_real_nn.pth" in flat
    assert "DAT_x3_bf16.safetensors" in flat


def test_text_cli_returns_two_for_blocking_issue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Blocking reports use a stable nonzero status and readable diagnostics."""

    issue = PreflightIssue(
        IssueSeverity.ERROR,
        IssueCode.UNSUPPORTED_HDR,
        "HDR is unsupported.",
        tmp_path / "hdr.mp4",
    )
    service = FakeService(PreflightReport((issue,), None, None))
    monkeypatch.setattr(cli, "PreflightService", lambda: service)

    result = cli.main(
        [
            "preflight",
            "--input",
            str(tmp_path / "hdr.mp4"),
            "--output-dir",
            str(tmp_path),
        ]
    )

    output = capsys.readouterr().out
    assert result == 2
    assert "Preflight failed." in output
    assert "unsupported_hdr" in output
    assert not service.registry.released


def test_process_json_reports_completed_output_and_parsed_policy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """The process command remains a thin machine-readable service adapter."""

    output = tmp_path / "final.mp4"
    service = FakePipelineService(_processing_result(output))
    monkeypatch.setattr(cli, "PipelineService", lambda: service)

    result = cli.main(["process", "--input", str(tmp_path / "clip.mp4"), "--output-dir", str(tmp_path), "--output", str(output), "--no-overwrite", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert result == 0
    assert not captured.err
    assert payload["status"] == "completed"
    assert payload["log_path"] == str(tmp_path / "advanced-ai-video-tools.log")
    assert payload["output_path"] == str(output)
    assert payload["audio_mode"] == "none"
    assert service.request is not None
    assert service.request.explicit_output_path == output
    assert service.request.overwrite_mode.value == "no_overwrite"


def test_process_preflight_rejection_uses_exit_two_and_json_stdout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Blocking validation remains distinguishable from a runtime failure."""

    issue = PreflightIssue(IssueSeverity.ERROR, IssueCode.UNSUPPORTED_HDR, "HDR is unsupported.", tmp_path / "hdr.mp4")
    report = PreflightReport((issue,), None, None)
    service = FakePipelineService(PipelineFailed("HDR is unsupported.", PipelineStage.VALIDATE, preflight=report))
    monkeypatch.setattr(cli, "PipelineService", lambda: service)

    result = cli.main(["process", "--input", str(tmp_path / "hdr.mp4"), "--output-dir", str(tmp_path), "--json"])

    captured = capsys.readouterr()
    assert result == 2
    assert json.loads(captured.out)["status"] == "rejected"
    assert not captured.err


def test_process_runtime_failure_reports_stage_workspace_and_exit_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """A retained backend failure is actionable to a shell user."""

    workspace = tmp_path / "job"
    report = PreflightReport((), _plan(tmp_path / "final.mp4"), None)
    service = FakePipelineService(PipelineFailed("synthetic failure", PipelineStage.UPSCALE, preflight=report, workspace_path=workspace, diagnostic_tail="details"))
    monkeypatch.setattr(cli, "PipelineService", lambda: service)

    result = cli.main(["process", "--input", str(tmp_path / "clip.mp4"), "--output-dir", str(tmp_path)])

    captured = capsys.readouterr()
    assert result == 1
    assert not captured.out
    assert "Processing failed during upscale" in captured.err
    assert "synthetic failure" in captured.err
    assert f"Log: {tmp_path / 'advanced-ai-video-tools.log'}" in captured.err


def test_process_cancellation_returns_shell_status_130(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Cooperative Ctrl-C cancellation has a conventional terminal status."""

    service = FakePipelineService(PipelineCancelled("cancelled cleanly", PipelineStage.EXTRACT, workspace_path=tmp_path / "job"))
    monkeypatch.setattr(cli, "PipelineService", lambda: service)

    result = cli.main(["process", "--input", str(tmp_path / "clip.mp4"), "--output-dir", str(tmp_path)])

    captured = capsys.readouterr()
    assert result == 130
    assert not captured.out
    assert "Processing cancelled during extract" in captured.err


def test_gui_command_dispatches_desktop_entry_point(monkeypatch: pytest.MonkeyPatch) -> None:
    """The CLI exposes the native shell without requiring media arguments."""

    monkeypatch.setattr(cli, "_run_gui", lambda: 17)

    assert cli.main(["gui"]) == 17


def test_legacy_cli_alias_emits_deprecation_warning_on_stderr(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """The v1 command remains usable without contaminating stdout."""

    monkeypatch.setattr(cli, "_run_gui", lambda: 17)
    monkeypatch.setattr("sys.argv", ["/venv/bin/ai-video-tools"])

    assert cli.main(["gui"]) == 17
    assert "ai-video-tools is deprecated" in capsys.readouterr().err


def test_cli_discloses_pipeline_ordered_passes_paths_and_skip_in_json_and_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Both CLI renderings carry the same Phase 6 sizing and skip decisions."""

    output = tmp_path / "ai-video.mp4"
    runner = tmp_path / "spandrel-runner"
    passes = (
        UpscalePassPlan(1, UpscaleBackend.SPANDREL, 2, 1920, 1080, 3840, 2160, runner, tmp_path / "x2.safetensors"),
        UpscalePassPlan(2, UpscaleBackend.SPANDREL, 3, 3840, 2160, 11520, 6480, runner, tmp_path / "x3.safetensors"),
    )
    plans = {
        "ordered": _plan(output, pipeline=ProcessingPipeline.TWO_X_THREE_X_RESIZE, passes=passes),
        "skipped": _plan(output, pipeline=ProcessingPipeline.FOUR_X_RESIZE, passes=()),
        "concat": _plan(output, pipeline=ProcessingPipeline.CONCAT, passes=()),
    }
    arguments = ["preflight", "--input", str(tmp_path / "clip.mp4"), "--output-dir", str(tmp_path)]
    for name, plan in plans.items():
        monkeypatch.setattr(cli, "PreflightService", lambda plan=plan: FakeService(PreflightReport((), plan, None)))
        assert cli.main([*arguments, "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)["plan"]
        assert payload["pipeline"] == plan.pipeline.value
        assert payload["ai_skipped"] is (name == "skipped")
        assert [item["model"] for item in payload["passes"]] == [str(item.model_path) for item in plan.upscale_passes]
        assert cli.main(arguments) == 0
        text = capsys.readouterr().out
        assert f"AI: {payload['ai_summary']}" in text
        if name == "ordered":
            assert payload["ai_summary"] == "2× Spandrel → 3× Spandrel"
            assert "AI scale: 6" in text
        if name == "skipped":
            assert "AI scale: skipped" in text
        if name == "concat":
            assert "AI scale: not used" in text
