"""Tests for bounded, cancellable process-group execution."""

import shlex
import sys
import threading
import time
from pathlib import Path

import pytest
from loguru import logger

from advanced_ai_video_tools.system.processes import CancellationToken, DIAGNOSTIC_LIMIT_BYTES, ProcessCancelled, ProcessExecutionError, ProcessTimeoutError, SubprocessRunner, command_line_for_log, redacted_command


def test_command_redaction_hides_absolute_paths_and_home_fragments() -> None:
    """Diagnostic command arrays retain structure without exposing local paths."""

    home = str(Path.home())
    command = ("ffmpeg", "-i", f"{home}/private/source.mov", "filter=value", "/private/tmp/output.mp4")

    assert redacted_command(command) == ("ffmpeg", "-i", "<absolute-path>", "filter=value", "<absolute-path>")


def test_subprocess_launch_is_logged_at_info_as_exact_shell_quoted_command(tmp_path: Path) -> None:
    """The local diagnostic record retains every argument without changing execution."""

    executable = tmp_path / "ffmpeg"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    command = (str(executable), "-i", str(tmp_path / "clip with spaces.mov"), "-metadata", "comment=it's exact")
    records: list[object] = []
    sink = logger.add(lambda message: records.append(message.record), level="INFO")
    try:
        SubprocessRunner().run(command, CancellationToken(), 5)
    finally:
        logger.remove(sink)

    assert command_line_for_log(command) == shlex.join(command)
    assert any(record["level"].name == "INFO" and record["message"] == f"RUN {shlex.join(command)}" for record in records)  # type: ignore[index]


def test_process_runner_captures_success_output() -> None:
    """Successful output is returned without invoking a shell."""

    result = SubprocessRunner().run((sys.executable, "-c", "import sys; print('out'); print('err', file=sys.stderr)"), CancellationToken(), 5)

    assert result.returncode == 0
    assert result.stdout_tail.strip() == "out"
    assert result.stderr_tail.strip() == "err"


def test_process_runner_rejects_invalid_requests_before_launch() -> None:
    """Request validation remains independent from process lifecycle handling."""

    runner = SubprocessRunner()
    with pytest.raises(ValueError, match="command cannot be empty"):
        runner.run((), CancellationToken(), 5)
    with pytest.raises(ValueError, match="timeout must be positive"):
        runner.run((sys.executable,), CancellationToken(), 0)


def test_process_failure_retains_only_bounded_diagnostics() -> None:
    """Unbounded tool output cannot consume unbounded application memory."""

    with pytest.raises(ProcessExecutionError) as captured:
        SubprocessRunner().run((sys.executable, "-c", "import sys; sys.stderr.write('x' * 100000); raise SystemExit(7)"), CancellationToken(), 5)

    assert captured.value.returncode == 7
    assert len(captured.value.stderr_tail.encode("utf-8")) <= DIAGNOSTIC_LIMIT_BYTES
    assert captured.value.stderr_tail.endswith("x" * 100)


def test_cancellation_terminates_the_process_group(tmp_path: Path) -> None:
    """A spawned descendant cannot outlive cancellation and mutate later."""

    marker = tmp_path / "child-finished"
    child_code = "import pathlib,sys,time; time.sleep(0.5); pathlib.Path(sys.argv[1]).write_text('finished')"
    parent_code = "import subprocess,sys,time; subprocess.Popen([sys.executable, '-c', sys.argv[1], sys.argv[2]]); time.sleep(30)"
    token = CancellationToken()
    timer = threading.Timer(0.1, token.cancel)
    timer.start()
    try:
        with pytest.raises(ProcessCancelled):
            SubprocessRunner().run((sys.executable, "-c", parent_code, child_code, str(marker)), token, 5)
    finally:
        timer.cancel()
    time.sleep(0.6)
    assert not marker.exists()


def test_process_timeout_terminates_work() -> None:
    """Every invocation has an explicit upper execution deadline."""

    with pytest.raises(ProcessTimeoutError):
        SubprocessRunner().run((sys.executable, "-c", "import time; time.sleep(30)"), CancellationToken(), 0.05)
