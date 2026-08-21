"""Tests for one-time bounded local Loguru configuration."""

from pathlib import Path

from loguru import logger

from ai_video_tools.system.diagnostics import configure_logging, current_log_path, shutdown_logging


def test_logging_configuration_is_idempotent_and_writes_bound_context(tmp_path: Path) -> None:
    """One file sink receives stable job and stage context without diagnostics exposure."""

    shutdown_logging()
    try:
        first = configure_logging(tmp_path, stderr=False)
        second = configure_logging(tmp_path / "ignored", stderr=False)
        with logger.contextualize(job_id="job-123", stage="verify"):
            logger.info("Synthetic diagnostic")
        logger.complete()

        assert first is second
        assert current_log_path() == tmp_path / "ai-video-tools.log"
        contents = first.log_path.read_text(encoding="utf-8")
        assert "job=job-123 stage=verify" in contents
        assert "Synthetic diagnostic" in contents
    finally:
        shutdown_logging()
