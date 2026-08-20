"""Cancellable shell-free subprocess execution with bounded diagnostics."""

from __future__ import annotations

import os
import signal
import subprocess
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import BinaryIO, Protocol

DIAGNOSTIC_LIMIT_BYTES = 64 * 1024
TERMINATION_GRACE_SECONDS = 5.0


class CancellationToken:
    """Thread-safe cooperative cancellation shared by services and processes."""

    def __init__(self) -> None:
        self._event = Event()

    def cancel(self) -> None:
        """Request cancellation; repeated calls are harmless."""

        self._event.set()

    @property
    def cancelled(self) -> bool:
        """Whether cancellation has been requested."""

        return self._event.is_set()

    def wait(self, timeout: float) -> bool:
        """Wait up to timeout seconds and return whether cancellation occurred."""

        return self._event.wait(timeout)


@dataclass(frozen=True)
class ProcessResult:
    """Successful process result with only bounded output tails retained."""

    command: tuple[str, ...]
    returncode: int
    stdout_tail: str
    stderr_tail: str


class ProcessError(RuntimeError):
    """Base class for translated child-process failures."""

    def __init__(self, message: str, command: Sequence[str], stdout_tail: str = "", stderr_tail: str = "") -> None:
        super().__init__(message)
        self.command = tuple(command)
        self.stdout_tail = stdout_tail
        self.stderr_tail = stderr_tail


class ProcessExecutionError(ProcessError):
    """A child process returned a nonzero exit status."""

    def __init__(self, command: Sequence[str], returncode: int, stdout_tail: str, stderr_tail: str) -> None:
        executable = Path(command[0]).name if command else "process"
        super().__init__(f"{executable} failed with exit code {returncode}", command, stdout_tail, stderr_tail)
        self.returncode = returncode


class ProcessTimeoutError(ProcessError):
    """A child process exceeded its explicit execution deadline."""


class ProcessCancelled(ProcessError):
    """A child process was terminated after cooperative cancellation."""


class ProcessRunner(Protocol):
    """Replaceable process boundary for application-service tests."""

    def run(self, command: Sequence[str], cancellation: CancellationToken, timeout_seconds: float) -> ProcessResult:
        """Execute one command or raise a typed process failure."""


def _read_tail(handle: BinaryIO) -> str:
    handle.flush()
    handle.seek(0, os.SEEK_END)
    size = handle.tell()
    handle.seek(max(0, size - DIAGNOSTIC_LIMIT_BYTES))
    return handle.read().decode("utf-8", errors="replace")


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=TERMINATION_GRACE_SECONDS)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    process.wait(timeout=TERMINATION_GRACE_SECONDS)


class SubprocessRunner:
    """macOS process-group runner that never invokes a command shell."""

    def run(self, command: Sequence[str], cancellation: CancellationToken, timeout_seconds: float) -> ProcessResult:
        """Execute with a deadline and terminate the full group on cancellation."""

        arguments = tuple(str(argument) for argument in command)
        if not arguments:
            raise ValueError("a process command cannot be empty")
        if timeout_seconds <= 0:
            raise ValueError("process timeout must be positive")
        if cancellation.cancelled:
            raise ProcessCancelled("process cancelled before launch", arguments)
        with tempfile.TemporaryFile(mode="w+b") as stdout_file, tempfile.TemporaryFile(mode="w+b") as stderr_file:
            try:
                process_context = subprocess.Popen(arguments, stdin=subprocess.DEVNULL, stdout=stdout_file, stderr=stderr_file, shell=False, start_new_session=True, close_fds=True)
            except OSError as error:
                raise ProcessError(f"could not launch {Path(arguments[0]).name}: {error}", arguments) from error
            with process_context as process:
                deadline = time.monotonic() + timeout_seconds
                while process.poll() is None:
                    if cancellation.wait(0.05):
                        _terminate_process_group(process)
                        raise ProcessCancelled("process cancelled", arguments, _read_tail(stdout_file), _read_tail(stderr_file))
                    if time.monotonic() >= deadline:
                        _terminate_process_group(process)
                        raise ProcessTimeoutError(f"{Path(arguments[0]).name} exceeded its {timeout_seconds:g}-second timeout", arguments, _read_tail(stdout_file), _read_tail(stderr_file))
                stdout_tail = _read_tail(stdout_file)
                stderr_tail = _read_tail(stderr_file)
                if process.returncode != 0:
                    raise ProcessExecutionError(arguments, process.returncode, stdout_tail, stderr_tail)
                return ProcessResult(arguments, process.returncode, stdout_tail, stderr_tail)
