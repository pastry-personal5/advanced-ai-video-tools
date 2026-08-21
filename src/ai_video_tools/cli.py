"""Thin command-line adapters over shared validation and processing services."""

from __future__ import annotations

import argparse
import json
import signal
import sys
from pathlib import Path

from ai_video_tools import __version__
from ai_video_tools.core.models import (
    JobRequest,
    OverwriteMode,
    PipelineStage,
    PreflightReport,
    ProgressEvent,
    ToolOverrides,
)
from ai_video_tools.services.pipeline import PipelineCancelled, PipelineFailed, PipelineResult, PipelineService
from ai_video_tools.services.preflight import PreflightService
from ai_video_tools.system.diagnostics import configure_logging, current_log_path
from ai_video_tools.system.processes import CancellationToken


def _add_job_arguments(command: argparse.ArgumentParser) -> None:
    """Add shared immutable job-intent arguments to one CLI command."""

    command.add_argument("--input", action="append", required=True, type=Path)
    command.add_argument("--output-dir", required=True, type=Path)
    command.add_argument("--output", type=Path, help="explicit .mp4 destination")
    command.add_argument("--height", type=int, default=2160)
    command.add_argument("--model", default="realesrgan-x4plus")
    command.add_argument("--acknowledge-dropped-streams", action="store_true")
    command.add_argument("--no-overwrite", action="store_true")
    command.add_argument("--ffmpeg", type=Path)
    command.add_argument("--ffprobe", type=Path)
    command.add_argument("--realesrgan", type=Path)
    command.add_argument("--model-dir", type=Path)
    command.add_argument("--json", action="store_true", dest="as_json")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-video-tools",
        description="Validate or run concat-first, real-image video upscale jobs.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    preflight = commands.add_parser("preflight", help="validate a job without processing media")
    _add_job_arguments(preflight)
    process = commands.add_parser("process", help="validate and process one complete video job")
    _add_job_arguments(process)
    return parser


def _request(arguments: argparse.Namespace) -> JobRequest:
    return JobRequest(
        inputs=tuple(arguments.input),
        output_directory=arguments.output_dir,
        explicit_output_path=arguments.output,
        target_height=arguments.height,
        model_name=arguments.model,
        acknowledge_dropped_streams=arguments.acknowledge_dropped_streams,
        overwrite_mode=(OverwriteMode.NO_OVERWRITE if arguments.no_overwrite else OverwriteMode.REPLACE),
        tools=ToolOverrides(
            ffmpeg=arguments.ffmpeg,
            ffprobe=arguments.ffprobe,
            realesrgan=arguments.realesrgan,
            model_directory=arguments.model_dir,
        ),
    )


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
                f"AI scale: {plan.ai_scale or 'skipped'}",
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
    sys.stderr.write(f"[{event.stage.value} {measured}] {event.message}\n")


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
    report = service.run(_request(parsed))
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
        result = PipelineService().run(_request(parsed), cancellation=token, progress=None if parsed.as_json else _progress)
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


def main(arguments: list[str] | None = None) -> int:
    """Run the selected CLI adapter and return a process exit code."""

    parsed = _parser().parse_args(arguments)
    # pylint: disable-next=import-outside-toplevel,no-name-in-module
    from PySide6.QtCore import QCoreApplication

    QCoreApplication.setOrganizationName("AI Video Tools")
    QCoreApplication.setApplicationName("AI Video Tools")
    configure_logging(stderr=not parsed.as_json)
    if parsed.command == "preflight":
        return _run_preflight(parsed)
    return _run_processing(parsed)
