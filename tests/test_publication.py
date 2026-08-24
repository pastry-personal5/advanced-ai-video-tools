"""Tests for same-filesystem partials and atomic publication semantics."""

from __future__ import annotations

from pathlib import Path

import pytest

from advanced_ai_video_tools.storage.naming import OutputCollisionError
from advanced_ai_video_tools.storage.publication import AtomicOutputPublisher, PartialOutput, PublicationError


def test_replace_preserves_old_destination_until_atomic_publication(tmp_path: Path) -> None:
    """Explicit overwrite never exposes the partial or deletes the old file early."""

    destination = tmp_path / "final.mp4"
    destination.write_bytes(b"old complete output")
    publisher = AtomicOutputPublisher()
    partial = publisher.create_partial(destination)
    partial.path.write_bytes(b"new verified output")

    assert destination.read_bytes() == b"old complete output"
    published = publisher.publish(partial, replace=True)

    assert published == destination
    assert destination.read_bytes() == b"new verified output"
    assert not partial.path.exists()


def test_no_clobber_publication_atomically_creates_a_new_destination(tmp_path: Path) -> None:
    """Generated and no-overwrite paths are committed without a check/write race."""

    destination = tmp_path / "final.mp4"
    publisher = AtomicOutputPublisher()
    partial = publisher.create_partial(destination)
    partial.path.write_bytes(b"verified output")

    publisher.publish(partial, replace=False)

    assert destination.read_bytes() == b"verified output"
    assert not partial.path.exists()


def test_no_clobber_collision_preserves_both_winner_and_unpublished_partial(tmp_path: Path) -> None:
    """A destination appearing during encoding is never overwritten."""

    destination = tmp_path / "final.mp4"
    publisher = AtomicOutputPublisher()
    partial = publisher.create_partial(destination)
    partial.path.write_bytes(b"our verified output")
    destination.write_bytes(b"racing winner")

    with pytest.raises(OutputCollisionError, match="appeared"):
        publisher.publish(partial, replace=False)

    assert destination.read_bytes() == b"racing winner"
    assert partial.path.read_bytes() == b"our verified output"


def test_discard_removes_only_the_allocated_partial(tmp_path: Path) -> None:
    """Cleanup cannot be redirected to an unrelated neighboring file."""

    destination = tmp_path / "final.mp4"
    publisher = AtomicOutputPublisher()
    partial = publisher.create_partial(destination)
    neighbor = tmp_path / "keep.mp4"
    neighbor.write_bytes(b"keep")

    publisher.discard(partial)

    assert not partial.path.exists()
    assert neighbor.read_bytes() == b"keep"


def test_forged_partial_identity_and_empty_partial_are_rejected(tmp_path: Path) -> None:
    """Publication requires both the allocation identity and encoded bytes."""

    destination = tmp_path / "final.mp4"
    publisher = AtomicOutputPublisher()
    partial = publisher.create_partial(destination)
    forged = PartialOutput(destination, tmp_path / "unrelated.partial.mp4", partial.identifier)

    with pytest.raises(PublicationError, match="identity"):
        publisher.discard(forged)
    with pytest.raises(PublicationError, match="empty"):
        publisher.publish(partial, replace=True)

    publisher.discard(partial)
