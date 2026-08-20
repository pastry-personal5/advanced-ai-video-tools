"""Tests for output naming and in-process reservations."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ai_video_tools.core.models import OverwriteMode
from ai_video_tools.storage.naming import (
    OutputCollisionError,
    OutputPathRegistry,
    automatic_output_basename,
)


def test_automatic_name_includes_microseconds_and_numeric_offset() -> None:
    """The default filename freezes an unambiguous local creation time."""

    created = datetime(2026, 8, 21, 14, 30, 52, 123456, tzinfo=timezone(timedelta(hours=9)))
    assert automatic_output_basename(created) == "ai-video-20260821-143052-123456+0900.mp4"


def test_automatic_name_requires_timezone() -> None:
    """Naive datetimes cannot silently produce ambiguous destinations."""

    with pytest.raises(ValueError, match="timezone-aware"):
        automatic_output_basename(datetime(2026, 8, 21))


def test_generated_reservations_avoid_disk_and_queue_collisions(
    tmp_path: Path,
) -> None:
    """Generated outputs never overwrite an existing or queued output."""

    registry = OutputPathRegistry()
    created = datetime(2026, 8, 21, tzinfo=timezone.utc)
    base = tmp_path / automatic_output_basename(created)
    base.touch()

    first = registry.reserve_generated(tmp_path, created)
    second = registry.reserve_generated(tmp_path, created)

    assert first.name.endswith("-01.mp4")
    assert second.name.endswith("-02.mp4")
    registry.release(first)
    assert registry.reserve_generated(tmp_path, created) == first


def test_explicit_destination_defaults_to_replace_but_can_refuse(
    tmp_path: Path,
) -> None:
    """Existing explicit outputs follow the selected overwrite policy."""

    destination = tmp_path / "existing.mp4"
    destination.touch()
    registry = OutputPathRegistry()

    assert registry.reserve_explicit(destination, OverwriteMode.REPLACE) == destination
    registry.release(destination)
    with pytest.raises(OutputCollisionError, match="already exists"):
        registry.reserve_explicit(destination, OverwriteMode.NO_OVERWRITE)
