"""Cancellable shell-free subprocess execution with bounded diagnostics."""

from __future__ import annotations

import os
import selectors
import shlex
import signal
import subprocess
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import BinaryIO, Protocol

from loguru import logger

DIAGNOSTIC_LIMIT_BYTES = 64 * 1024
INSPECTION_OUTPUT_LIMIT_BYTES = 4 * 1024 * 1024
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


class ProcessOutputLimitError(RuntimeError):
    """A bounded inspection command emitted more output than policy allows."""

    def __init__(self, limit_bytes: int) -> None:
        super().__init__(f"process output exceeded the {limit_bytes:,}-byte limit")
        self.limit_bytes = limit_bytes


class ProcessRunner(Protocol):
    """Replaceable process boundary for application-service tests."""

    def run(self, command: Sequence[str], cancellation: CancellationToken, timeout_seconds: float) -> ProcessResult:
        """Execute one command or raise a typed process failure."""


def redacted_command(command: Sequence[str]) -> tuple[str, ...]:
    """Return a log-safe argument array with absolute paths hidden."""

    home = str(Path.home())
    redacted = []
    for argument in command:
        value = str(argument)
        if os.path.isabs(value):
            redacted.append("<absolute-path>")
        elif home and home in value:
            redacted.append(value.replace(home, "<home>"))
        else:
            redacted.append(value)
    return tuple(redacted)


def command_line_for_log(command: Sequence[str]) -> str:
    """Render an exact, shell-quoted diagnostic copy of an argument vector."""

    return shlex.join(str(argument) for argument in command)


def log_subprocess_launch(command: Sequence[str]) -> None:
    """Record one exact subprocess invocation at INFO before it is launched."""

    logger.info("RUN {}", command_line_for_log(command))


def _read_tail(handle: BinaryIO) -> str:
    handle.flush()
    handle.seek(0, os.SEEK_END)
    size = handle.tell()
    handle.seek(max(0, size - DIAGNOSTIC_LIMIT_BYTES))
    return handle.read().decode("utf-8", errors="replace")


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    process_group = process.pid

    def group_exists() -> bool:
        try:
            os.killpg(process_group, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            # Sandboxed macOS environments can permit termination signals while
            # denying the zero-signal group probe. The parent status is the
            # conservative fallback in that environment.
            return process.poll() is None
        return True

    try:
        os.killpg(process_group, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + TERMINATION_GRACE_SECONDS
    while group_exists() and time.monotonic() < deadline:
        process.poll()
        time.sleep(0.05)
    if not group_exists():
        return
    try:
        os.killpg(process_group, signal.SIGKILL)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + TERMINATION_GRACE_SECONDS
    while group_exists() and time.monotonic() < deadline:
        process.poll()
        time.sleep(0.05)


def _append_bounded_output(captured: bytearray, chunk: bytes, limit_bytes: int) -> bool:
    """Retain up to one output limit while continuing to drain the child pipe."""

    available = limit_bytes - len(captured)
    if available <= 0:
        return bool(chunk)
    captured.extend(chunk[:available])
    return len(chunk) > available


def run_captured_subprocess(command: Sequence[str], timeout_seconds: float, *, output_limit_bytes: int = INSPECTION_OUTPUT_LIMIT_BYTES) -> subprocess.CompletedProcess[str]:
    """Run one shell-free inspection command with bounded stdout and stderr.

    Inspection commands must consume complete output to avoid pipe deadlocks, but
    FFprobe input and configured tools are outside the application's trust
    boundary.  This drains each pipe after its retained limit so a noisy child
    cannot make validation or probing allocate unbounded Python memory.
    """

    arguments = tuple(str(argument) for argument in command)
    if not arguments:
        raise ValueError("a process command cannot be empty")
    if timeout_seconds <= 0:
        raise ValueError("process timeout must be positive")
    if output_limit_bytes <= 0:
        raise ValueError("process output limit must be positive")
    started_at = time.monotonic()
    stdout = bytearray()
    stderr = bytearray()
    truncated = False
    with subprocess.Popen(arguments, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False, start_new_session=True, close_fds=True) as process:
        assert process.stdout is not None
        assert process.stderr is not None
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ, stdout)
            selector.register(process.stderr, selectors.EVENT_READ, stderr)
            while selector.get_map() or process.poll() is None:
                remaining_seconds = timeout_seconds - (time.monotonic() - started_at)
                if remaining_seconds <= 0:
                    _terminate_process_group(process)
                    raise subprocess.TimeoutExpired(arguments, timeout_seconds)
                for key, _events in selector.select(timeout=min(remaining_seconds, 0.05)):
                    chunk = os.read(key.fileobj.fileno(), 64 * 1024)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    truncated = _append_bounded_output(key.data, chunk, output_limit_bytes) or truncated
    if truncated:
        raise ProcessOutputLimitError(output_limit_bytes)
    return subprocess.CompletedProcess(
        arguments,
        process.returncode,
        stdout.decode("utf-8", errors="replace"),
        stderr.decode("utf-8", errors="replace"),
    )


class SubprocessRunner:
    """macOS process-group runner that never invokes a command shell."""

    @staticmethod
    def _validate_request(command: Sequence[str], timeout_seconds: float) -> tuple[str, ...]:
        arguments = tuple(str(argument) for argument in command)
        if not arguments:
            raise ValueError("a process command cannot be empty")
        if timeout_seconds <= 0:
            raise ValueError("process timeout must be positive")
        return arguments

    @staticmethod
    def _wait_for_completion(
        process: subprocess.Popen[bytes],
        *,
        arguments: tuple[str, ...],
        cancellation: CancellationToken,
        timeout_seconds: float,
        started_at: float,
        stdout_file: BinaryIO,
        stderr_file: BinaryIO,
    ) -> None:
        deadline = time.monotonic() + timeout_seconds
        while process.poll() is None:
            if cancellation.wait(0.05):
                _terminate_process_group(process)
                logger.info("Process cancelled executable={} elapsed_seconds={:.3f}", Path(arguments[0]).name, time.monotonic() - started_at)
                raise ProcessCancelled("process cancelled", arguments, _read_tail(stdout_file), _read_tail(stderr_file))
            if time.monotonic() >= deadline:
                _terminate_process_group(process)
                logger.error("Process timed out executable={} elapsed_seconds={:.3f}", Path(arguments[0]).name, time.monotonic() - started_at)
                raise ProcessTimeoutError(f"{Path(arguments[0]).name} exceeded its {timeout_seconds:g}-second timeout", arguments, _read_tail(stdout_file), _read_tail(stderr_file))

    def run(self, command: Sequence[str], cancellation: CancellationToken, timeout_seconds: float) -> ProcessResult:
        """Execute with a deadline and terminate the full group on cancellation."""

        arguments = self._validate_request(command, timeout_seconds)
        if cancellation.cancelled:
            logger.info("Process cancelled before launch executable={}", Path(arguments[0]).name)
            raise ProcessCancelled("process cancelled before launch", arguments)
        started_at = time.monotonic()
        log_subprocess_launch(arguments)
        logger.debug("Launching process executable={} timeout_seconds={}", Path(arguments[0]).name, timeout_seconds)
        with tempfile.TemporaryFile(mode="w+b") as stdout_file, tempfile.TemporaryFile(mode="w+b") as stderr_file:
            try:
                process_context = subprocess.Popen(arguments, stdin=subprocess.DEVNULL, stdout=stdout_file, stderr=stderr_file, shell=False, start_new_session=True, close_fds=True)
            except OSError as error:
                logger.error("Process launch failed executable={} error_type={}", Path(arguments[0]).name, type(error).__name__)
                raise ProcessError(f"could not launch {Path(arguments[0]).name}: {error}", arguments) from error
            with process_context as process:
                self._wait_for_completion(
                    process,
                    arguments=arguments,
                    cancellation=cancellation,
                    timeout_seconds=timeout_seconds,
                    started_at=started_at,
                    stdout_file=stdout_file,
                    stderr_file=stderr_file,
                )
                stdout_tail = _read_tail(stdout_file)
                stderr_tail = _read_tail(stderr_file)
                if process.returncode != 0:
                    logger.error("Process failed executable={} returncode={} elapsed_seconds={:.3f}", Path(arguments[0]).name, process.returncode, time.monotonic() - started_at)
                    raise ProcessExecutionError(arguments, process.returncode, stdout_tail, stderr_tail)
                logger.debug("Process completed executable={} returncode={} elapsed_seconds={:.3f}", Path(arguments[0]).name, process.returncode, time.monotonic() - started_at)
                return ProcessResult(arguments, process.returncode, stdout_tail, stderr_tail)
