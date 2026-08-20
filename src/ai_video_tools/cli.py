"""Thin command-line adapter over the shared preflight service."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ai_video_tools import __version__
from ai_video_tools.core.models import (
    JobRequest,
    OverwriteMode,
    PreflightReport,
    ToolOverrides,
)
from ai_video_tools.services.preflight import PreflightService


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-video-tools",
        description="Validate concat-first, real-image video upscale jobs.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    preflight = commands.add_parser("preflight", help="validate a job without processing media")
    preflight.add_argument("--input", action="append", required=True, type=Path)
    preflight.add_argument("--output-dir", required=True, type=Path)
    preflight.add_argument("--output", type=Path, help="explicit .mp4 destination")
    preflight.add_argument("--height", type=int, default=2160)
    preflight.add_argument("--model", default="realesrgan-x4plus")
    preflight.add_argument("--assume-bt709", action="store_true")
    preflight.add_argument("--acknowledge-dropped-streams", action="store_true")
    preflight.add_argument("--no-overwrite", action="store_true")
    preflight.add_argument("--ffmpeg", type=Path)
    preflight.add_argument("--ffprobe", type=Path)
    preflight.add_argument("--realesrgan", type=Path)
    preflight.add_argument("--model-dir", type=Path)
    preflight.add_argument("--json", action="store_true", dest="as_json")
    return parser


def _request(arguments: argparse.Namespace) -> JobRequest:
    return JobRequest(
        inputs=tuple(arguments.input),
        output_directory=arguments.output_dir,
        explicit_output_path=arguments.output,
        target_height=arguments.height,
        model_name=arguments.model,
        assume_bt709=arguments.assume_bt709,
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
            "output_dimensions": [plan.output_width, plan.output_height],
            "output_frame_rate": str(plan.output_frame_rate),
            "ai_scale": plan.ai_scale,
            "concat_strategy": plan.concat_strategy.value,
            "output_audio_layout": plan.output_audio_layout,
            "assume_bt709": plan.assume_bt709,
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
    return "\n".join(lines)


def main(arguments: list[str] | None = None) -> int:
    """Run the selected CLI adapter and return a process exit code."""

    parsed = _parser().parse_args(arguments)
    if parsed.command != "preflight":
        return 2

    # pylint: disable-next=import-outside-toplevel,no-name-in-module
    from PySide6.QtCore import QCoreApplication

    QCoreApplication.setOrganizationName("AI Video Tools")
    QCoreApplication.setApplicationName("AI Video Tools")
    service = PreflightService()
    report = service.run(_request(parsed))
    rendered = _json_report(report) if parsed.as_json else _text_report(report)
    sys.stdout.write(f"{rendered}\n")
    if report.plan is not None:
        service.registry.release(report.plan.output_path)
    return 0 if report.ready else 2
