"""Tests for bounded, cancellable process-group execution."""

import sys
import threading
import time
from pathlib import Path

import pytest

from ai_video_tools.system.processes import CancellationToken, DIAGNOSTIC_LIMIT_BYTES, ProcessCancelled, ProcessExecutionError, ProcessTimeoutError, SubprocessRunner


def test_process_runner_captures_success_output() -> None:
    """Successful output is returned without invoking a shell."""

    result = SubprocessRunner().run((sys.executable, "-c", "import sys; print('out'); print('err', file=sys.stderr)"), CancellationToken(), 5)

    assert result.returncode == 0
    assert result.stdout_tail.strip() == "out"
    assert result.stderr_tail.strip() == "err"


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
