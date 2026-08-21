"""Tests for output naming and in-process reservations."""

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest

from ai_video_tools.core.models import OverwriteMode
from ai_video_tools.storage.naming import (
    OutputCollisionError,
    OutputPathRegistry,
    automatic_output_basename,
    automatic_output_basename_matches,
)


def test_automatic_name_includes_local_second_and_compact_uuid7() -> None:
    """The basename combines readable local time with an RFC 9562 identifier."""

    created = datetime(2026, 8, 21, 14, 30, 52, 123456, tzinfo=timezone(timedelta(hours=9)))
    name = automatic_output_basename(created)

    match = re.fullmatch(r"ai-video-20260821-143052-([0-9a-f]{32})\.mp4", name)
    assert match is not None
    identifier = UUID(hex=match.group(1))
    assert identifier.version == 7
    assert identifier.int >> 80 == 1_787_290_252_123
    assert identifier.int >> 62 & 0b11 == 0b10


def test_automatic_names_use_fresh_uuid_payloads() -> None:
    """Jobs created in the same clock tick still receive distinct basenames."""

    created = datetime(2026, 8, 21, tzinfo=timezone.utc)

    assert automatic_output_basename(created) != automatic_output_basename(created)


def test_frozen_name_validation_binds_timestamp_and_safe_compact_form() -> None:
    """A queued basename cannot change its local or absolute creation identity."""

    created = datetime(2026, 8, 21, 14, 30, 52, 123456, tzinfo=timezone(timedelta(hours=9)))
    basename = automatic_output_basename(created)

    assert automatic_output_basename_matches(basename, created)
    assert automatic_output_basename_matches(basename.replace(".mp4", "-01.mp4"), created)
    assert not automatic_output_basename_matches(basename, created + timedelta(seconds=1))
    assert not automatic_output_basename_matches(f"../{basename}", created)


def test_automatic_name_requires_timezone() -> None:
    """Naive datetimes cannot silently produce ambiguous destinations."""

    with pytest.raises(ValueError, match="timezone-aware"):
        automatic_output_basename(datetime(2026, 8, 21))


def test_generated_reservations_avoid_disk_and_queue_collisions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Generated outputs never overwrite an existing or queued output."""

    registry = OutputPathRegistry()
    created = datetime(2026, 8, 21, tzinfo=timezone.utc)
    basename = "ai-video-20260821-000000-0198ca56c40070008000000000000000.mp4"
    monkeypatch.setattr("ai_video_tools.storage.naming.automatic_output_basename", lambda _created_at: basename)
    base = tmp_path / basename
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
