"""Thin command-line adapters over shared validation and processing services."""

from __future__ import annotations

import argparse
import json
import signal
import sys
from pathlib import Path

from advanced_ai_video_tools import __version__
from advanced_ai_video_tools.core.models import (
    JobPlan,
    JobRequest,
    NativeScale,
    OverwriteMode,
    PipelineStage,
    PreflightReport,
    ProgressEvent,
    ProcessingPipeline,
    ToolOverrides,
)
from advanced_ai_video_tools.services.pipeline import PipelineCancelled, PipelineFailed, PipelineResult, PipelineService
from advanced_ai_video_tools.services.plan_summary import ai_plan_summary, ai_skipped
from advanced_ai_video_tools.services.preflight import PreflightService
from advanced_ai_video_tools.gui.identity import GUI_DISPLAY_NAME, GUI_ORGANIZATION_NAME, LEGACY_CLI_COMMAND
from advanced_ai_video_tools.identity import IDENTITY
from advanced_ai_video_tools.system.diagnostics import configure_logging, current_log_path
from advanced_ai_video_tools.system.processes import CancellationToken
from advanced_ai_video_tools.system.spandrel import DEFAULT_SPANDREL_MODELS


def _add_job_arguments(command: argparse.ArgumentParser) -> None:
    """Add shared immutable job-intent arguments to one CLI command."""

    command.add_argument("--input", action="append", required=True, type=Path)
    command.add_argument("--output-dir", required=True, type=Path)
    command.add_argument("--output", type=Path, help="explicit .mp4 destination, or matching .mov for concat only")
    command.add_argument("--height", type=int, default=2160)
    command.add_argument("--pipeline", choices=tuple(value.value for value in ProcessingPipeline), default=ProcessingPipeline.AUTO.value)
    command.add_argument("--scale", type=int, choices=(2, 3, 4), help="required only for --pipeline native")
    command.add_argument("--model", default="realesrgan-x4plus")
    command.add_argument("--acknowledge-dropped-streams", action="store_true")
    command.add_argument("--allow-mixed-color-tags", action="store_true", help="allow untagged clips to use the agreed declared SDR color profile")
    command.add_argument("--no-overwrite", action="store_true")
    command.add_argument("--ffmpeg", type=Path)
    command.add_argument("--ffprobe", type=Path)
    command.add_argument("--realesrgan", type=Path)
    command.add_argument("--model-dir", type=Path)
    command.add_argument("--spandrel-runner", type=Path, help="Spandrel runner executable (default: the checkout's tools/spandrel-runner/spandrel-runner; PATH is never searched)")
    command.add_argument("--model-2x", type=Path, help=f"2x checkpoint (default: {DEFAULT_SPANDREL_MODELS[2]} in the models directory beside the runner)")
    command.add_argument("--model-3x", type=Path, help=f"3x checkpoint (default: {DEFAULT_SPANDREL_MODELS[3]} in the models directory beside the runner)")
    command.add_argument("--json", action="store_true", dest="as_json")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=IDENTITY.primary_command,
        description="Validate or run concat-first, real-image video upscale jobs.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("gui", help="launch the PySide6 desktop application")
    preflight = commands.add_parser("preflight", help="validate a job without processing media")
    _add_job_arguments(preflight)
    process = commands.add_parser("process", help="validate and process one complete video job")
    _add_job_arguments(process)
    return parser


def _request(arguments: argparse.Namespace) -> JobRequest:
    pipeline = ProcessingPipeline(arguments.pipeline)
    if pipeline is ProcessingPipeline.NATIVE and arguments.scale is None:
        raise ValueError("--scale is required for --pipeline native")
    if pipeline is not ProcessingPipeline.NATIVE and arguments.scale is not None:
        raise ValueError("--scale is valid only with --pipeline native")
    native_scale = NativeScale(arguments.scale) if arguments.scale is not None else None
    uses_spandrel = pipeline is ProcessingPipeline.TWO_X_THREE_X_RESIZE or (pipeline is ProcessingPipeline.NATIVE and native_scale in {NativeScale.TWO, NativeScale.THREE})
    if not uses_spandrel and any(value is not None for value in (arguments.spandrel_runner, arguments.model_2x, arguments.model_3x)):
        raise ValueError("Spandrel runner and model flags are valid only for a pipeline that can execute a 2x or 3x Spandrel pass")
    return JobRequest(
        inputs=tuple(arguments.input),
        output_directory=arguments.output_dir,
        explicit_output_path=arguments.output,
        target_height=arguments.height,
        model_name=arguments.model,
        pipeline=pipeline,
        native_scale=native_scale,
        acknowledge_dropped_streams=arguments.acknowledge_dropped_streams,
        allow_mixed_color_tags=arguments.allow_mixed_color_tags,
        overwrite_mode=(OverwriteMode.NO_OVERWRITE if arguments.no_overwrite else OverwriteMode.REPLACE),
        tools=ToolOverrides(
            ffmpeg=arguments.ffmpeg,
            ffprobe=arguments.ffprobe,
            realesrgan=arguments.realesrgan,
            model_directory=arguments.model_dir,
            spandrel_runner=arguments.spandrel_runner,
            model_2x=arguments.model_2x,
            model_3x=arguments.model_3x,
        ),
    )


def _ai_scale_text(plan: JobPlan) -> str:
    """Keep Auto's historical wording while naming concat only distinctly."""

    if plan.pipeline is ProcessingPipeline.CONCAT:
        return "not used"
    return str(plan.ai_scale) if plan.ai_scale else "skipped"


def _json_report(report: PreflightReport) -> str:
    issues = report.issues
    plan = report.plan
    payload: dict[str, object] = {
        "ready": report.ready,
        "log_path": str(current_log_path()) if current_log_path() is not None else None,
        "issues": [
            {
                "severity": issue.severity.value,
                "code": issue.code.value,
                "message": issue.message,
                "path": str(issue.path) if issue.path else None,
            }
            for issue in issues
        ],
        "plan": None,
    }
    if plan is not None:
        payload["plan"] = {
            "created_at": plan.created_at.isoformat(),
            "output_path": str(plan.output_path),
            "generated_output_name": plan.generated_output_name,
            "output_dimensions": [plan.output_width, plan.output_height],
            "output_frame_rate": str(plan.output_frame_rate),
            "ai_scale": plan.ai_scale,
            "ai_skipped": ai_skipped(plan),
            "ai_summary": ai_plan_summary(plan),
            "pipeline": plan.pipeline.value,
            "native_scale": int(plan.native_scale) if plan.native_scale is not None else None,
            "passes": [
                {
                    "index": item.index,
                    "backend": item.backend.value,
                    "scale": item.scale,
                    "input_dimensions": [item.input_width, item.input_height],
                    "output_dimensions": [item.output_width, item.output_height],
                    "executable": str(item.executable_path),
                    "model": str(item.model_path),
                }
                for item in plan.upscale_passes
            ],
            "model": plan.model_name,
            "concat_strategy": plan.concat_strategy.value,
            "output_audio_layout": plan.output_audio_layout,
            "overwrite_mode": plan.overwrite_mode.value,
            "output_color_profile": {
                "matrix": plan.output_color_profile.matrix.value,
                "transfer": plan.output_color_profile.transfer,
                "primaries": plan.output_color_profile.primaries,
            },
            "acknowledge_dropped_streams": plan.acknowledge_dropped_streams,
            "allow_mixed_color_tags": plan.allow_mixed_color_tags,
            "normalization_reasons": list(plan.normalization_reasons),
            "estimated_peak_bytes": plan.estimated_peak_bytes,
            "required_free_bytes": plan.required_free_bytes,
        }
    return json.dumps(payload, indent=2, sort_keys=True)


def _text_report(report: PreflightReport) -> str:
    plan = report.plan
    lines = ["Preflight ready." if report.ready else "Preflight failed."]
    for issue in report.issues:
        location = f" [{issue.path}]" if issue.path else ""
        lines.append(f"{issue.severity.value.upper()} {issue.code.value}{location}: " f"{issue.message}")
    if plan is not None:
        lines.extend(
            (
                f"Output: {plan.output_path}",
                f"Video: {plan.output_width}x{plan.output_height} " f"at {plan.output_frame_rate}",
                f"AI scale: {_ai_scale_text(plan)}",
                f"AI: {ai_plan_summary(plan)}",
                f"Pipeline: {plan.pipeline.value}",
                "Passes: " + (", ".join(f"{item.index}:{item.backend.value}-{item.scale}x" for item in plan.upscale_passes) or "none"),
                f"Concat strategy: {plan.concat_strategy.value}",
                f"Required workspace free space: {plan.required_free_bytes:,} bytes",
            )
        )
    if current_log_path() is not None:
        lines.append(f"Log: {current_log_path()}")
    return "\n".join(lines)


def _json_processing_result(result: PipelineResult) -> str:
    plan = result.preflight.plan
    if plan is None:
        raise ValueError("a completed processing result has no frozen plan")
    probe = result.finalization.output_probe
    video = probe.primary_video
    payload = {
        "status": "completed",
        "log_path": str(current_log_path()) if current_log_path() is not None else None,
        "output_path": str(result.output_path),
        "output_dimensions": [plan.output_width, plan.output_height],
        "output_frame_rate": str(plan.output_frame_rate),
        "output_color_profile": {
            "matrix": plan.output_color_profile.matrix.value,
            "transfer": plan.output_color_profile.transfer,
            "primaries": plan.output_color_profile.primaries,
        },
        "ai_scale": plan.ai_scale,
        "ai_skipped": ai_skipped(plan),
        "pipeline": plan.pipeline.value,
        "native_scale": int(plan.native_scale) if plan.native_scale is not None else None,
        "passes": [{"index": item.index, "backend": item.backend.value, "scale": item.scale} for item in plan.upscale_passes],
        "concat_strategy": plan.concat_strategy.value,
        "audio_mode": result.finalization.audio_mode.value,
        "duration": str(video.duration) if video is not None and video.duration is not None else None,
        "warnings": [
            {
                "code": issue.code.value,
                "message": issue.message,
                "path": str(issue.path) if issue.path else None,
            }
            for issue in result.preflight.issues
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def _text_processing_result(result: PipelineResult) -> str:
    plan = result.preflight.plan
    if plan is None:
        raise ValueError("a completed processing result has no frozen plan")
    lines = [
        "Processing completed.",
        f"Output: {result.output_path}",
        f"Video: {plan.output_width}x{plan.output_height} at {plan.output_frame_rate}",
        f"Pipeline: {plan.pipeline.value}",
        f"Audio: {result.finalization.audio_mode.value}",
    ]
    if current_log_path() is not None:
        lines.append(f"Log: {current_log_path()}")
    for issue in result.preflight.issues:
        location = f" [{issue.path}]" if issue.path else ""
        lines.append(f"WARNING {issue.code.value}{location}: {issue.message}")
    return "\n".join(lines)


def _progress(event: ProgressEvent) -> None:
    measured = f"{event.completed}/{event.total}" if event.total is not None else str(event.completed)
    pass_label = f" pass={event.pass_index}/{event.pass_count} scale={event.pass_scale}x" if event.pass_index is not None else ""
    sys.stderr.write(f"[{event.stage.value} {measured}{pass_label}] {event.message}\n")


def _processing_error_payload(status: str, error: PipelineFailed | PipelineCancelled) -> str:
    return json.dumps(
        {
            "status": status,
            "stage": error.stage.value,
            "message": str(error),
            "workspace_path": str(error.workspace_path) if error.workspace_path is not None else None,
            "diagnostic_tail": error.diagnostic_tail if isinstance(error, PipelineFailed) and error.diagnostic_tail else None,
            "log_path": str(current_log_path()) if current_log_path() is not None else None,
        },
        indent=2,
        sort_keys=True,
    )


def _with_log_path(message: str) -> str:
    """Append the configured local diagnostic path to human-readable output."""

    return f"{message}\nLog: {current_log_path()}" if current_log_path() is not None else message


def _run_preflight(parsed: argparse.Namespace) -> int:
    service = PreflightService()
    try:
        request = _request(parsed)
    except ValueError as error:
        sys.stderr.write(f"Invalid job arguments: {error}\n")
        return 2
    report = service.execute_preflight(request)
    rendered = _json_report(report) if parsed.as_json else _text_report(report)
    sys.stdout.write(f"{rendered}\n")
    if report.plan is not None:
        service.registry.release(report.plan.output_path)
    return 0 if report.ready else 2


def _run_processing(parsed: argparse.Namespace) -> int:
    token = CancellationToken()
    previous_handler = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, lambda _signum, _frame: token.cancel())
    try:
        try:
            request = _request(parsed)
        except ValueError as error:
            sys.stderr.write(f"Invalid job arguments: {error}\n")
            return 2
        result = PipelineService().execute_pipeline(request, cancellation=token, progress=None if parsed.as_json else _progress)
    except PipelineCancelled as error:
        rendered = _processing_error_payload("cancelled", error) if parsed.as_json else _with_log_path(f"Processing cancelled during {error.stage.value}: {error}")
        (sys.stdout if parsed.as_json else sys.stderr).write(rendered + "\n")
        return 130
    except PipelineFailed as error:
        if error.stage is PipelineStage.VALIDATE and not error.preflight.ready:
            if parsed.as_json:
                payload = json.loads(_json_report(error.preflight))
                payload["status"] = "rejected"
                sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
            else:
                sys.stderr.write(_text_report(error.preflight) + "\n")
            return 2
        rendered = _processing_error_payload("failed", error) if parsed.as_json else _with_log_path(f"Processing failed during {error.stage.value}: {error}")
        (sys.stdout if parsed.as_json else sys.stderr).write(rendered + "\n")
        return 1
    finally:
        signal.signal(signal.SIGINT, previous_handler)
    rendered = _json_processing_result(result) if parsed.as_json else _text_processing_result(result)
    sys.stdout.write(rendered + "\n")
    return 0


def _run_gui() -> int:
    """Lazily import and launch the optional desktop presentation layer."""

    from advanced_ai_video_tools.gui.application import run_gui  # pylint: disable=import-outside-toplevel

    return run_gui()


def main(arguments: list[str] | None = None) -> int:
    """Run the selected CLI adapter and return a process exit code."""

    parsed = _parser().parse_args(arguments)
    # pylint: disable-next=import-outside-toplevel,no-name-in-module
    from PySide6.QtCore import QCoreApplication

    QCoreApplication.setOrganizationName(GUI_ORGANIZATION_NAME)

    if getattr(parsed, "command", None) == "gui":
        # Set the identity before QApplication exists so macOS does not use
        # the interpreter executable (for example, "python3") as the menu title.
        QCoreApplication.setApplicationName(GUI_DISPLAY_NAME)
    else:
        QCoreApplication.setApplicationName(GUI_DISPLAY_NAME)
    if Path(sys.argv[0]).name == LEGACY_CLI_COMMAND:
        sys.stderr.write(f"warning: {LEGACY_CLI_COMMAND} is deprecated; use {IDENTITY.primary_command} instead.\n")
    configure_logging(stderr=not getattr(parsed, "as_json", False))
    if parsed.command == "gui":
        return _run_gui()
    if parsed.command == "preflight":
        return _run_preflight(parsed)
    return _run_processing(parsed)
