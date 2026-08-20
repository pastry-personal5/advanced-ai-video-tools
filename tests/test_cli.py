"""Tests for the thin command-line presentation adapter."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ai_video_tools import cli
from ai_video_tools.core.models import (
    ConcatStrategy,
    IssueCode,
    IssueSeverity,
    JobPlan,
    JobRequest,
    PreflightIssue,
    PreflightReport,
    Rational,
)


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

    def run(self, request: JobRequest) -> PreflightReport:
        """Capture parsed job intent and return the report."""

        self.request = request
        return self.report


def _plan(output: Path) -> JobPlan:
    return JobPlan(
        created_at=datetime(2026, 8, 21, tzinfo=timezone.utc),
        output_path=output,
        generated_output_name=True,
        probes=(),
        output_frame_rate=Rational(24, 1),
        output_width=3840,
        output_height=2160,
        ai_scale=2,
        concat_strategy=ConcatStrategy.STREAM_COPY,
        output_audio_layout=None,
        normalization_reasons=(),
        estimated_peak_bytes=100,
        required_free_bytes=120,
    )


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
