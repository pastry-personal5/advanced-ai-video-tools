"""One-time Loguru configuration for local application diagnostics."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from loguru import logger

from ai_video_tools.storage.paths import application_data_directory

_LOG_FORMAT = "{time:YYYY-MM-DD HH:mm:ss.SSS Z} | {level:<8} | job={extra[job_id]} stage={extra[stage]} | {message}"
_CONFIGURATION_LOCK = Lock()
_CONFIGURATION: LoggingConfiguration | None = None
_SINK_IDS: tuple[int, ...] = ()


@dataclass(frozen=True)
class LoggingConfiguration:
    """Resolved local diagnostics destination."""

    log_path: Path


def configure_logging(log_directory: Path | None = None, *, stderr: bool = True) -> LoggingConfiguration:
    """Install bounded production sinks once and return the resolved log path."""

    global _CONFIGURATION, _SINK_IDS  # pylint: disable=global-statement
    with _CONFIGURATION_LOCK:
        if _CONFIGURATION is not None:
            return _CONFIGURATION
        directory = (log_directory or application_data_directory() / "logs").expanduser().resolve(strict=False)
        directory.mkdir(parents=True, exist_ok=True)
        log_path = directory / "ai-video-tools.log"
        logger.remove()
        logger.configure(extra={"job_id": "-", "stage": "-"})
        sinks: list[int] = []
        if stderr:
            sinks.append(logger.add(sys.stderr, level="INFO", format=_LOG_FORMAT, colorize=False, backtrace=False, diagnose=False, enqueue=True))
        sinks.append(logger.add(log_path, level="DEBUG", format=_LOG_FORMAT, rotation="10 MB", retention=5, encoding="utf-8", enqueue=True, backtrace=False, diagnose=False))
        _SINK_IDS = tuple(sinks)
        _CONFIGURATION = LoggingConfiguration(log_path)
        logger.info("Local diagnostics configured at <application-data>/logs/ai-video-tools.log")
        return _CONFIGURATION


def current_log_path() -> Path | None:
    """Return the active file sink path without configuring logging."""

    return _CONFIGURATION.log_path if _CONFIGURATION is not None else None


def shutdown_logging() -> None:
    """Flush and remove application-owned sinks, primarily for isolated tests."""

    global _CONFIGURATION, _SINK_IDS  # pylint: disable=global-statement
    with _CONFIGURATION_LOCK:
        logger.complete()
        for sink_id in _SINK_IDS:
            logger.remove(sink_id)
        _SINK_IDS = ()
        _CONFIGURATION = None
