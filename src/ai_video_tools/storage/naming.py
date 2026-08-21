"""Timezone-aware output naming and process-local path reservation."""

from __future__ import annotations

import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from secrets import randbits
from uuid import UUID

from ai_video_tools.core.models import OverwriteMode


class OutputCollisionError(FileExistsError):
    """Raised when no-overwrite publication targets an occupied path."""


_AUTOMATIC_BASENAME = re.compile(r"ai-video-(\d{8})-(\d{6})-([0-9a-f]{32})(?:-\d{2,})?\.mp4")


def automatic_output_basename(created_at: datetime) -> str:
    """Build the canonical local-time basename with a compact UUIDv7."""

    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise ValueError("created_at must be timezone-aware")
    identifier = _uuid7(created_at)
    return f"{created_at.strftime('ai-video-%Y%m%d-%H%M%S')}-{identifier.hex}.mp4"


def automatic_output_basename_matches(basename: str, created_at: datetime) -> bool:
    """Return whether a frozen basename is safe and belongs to its creation instant."""

    if created_at.tzinfo is None or created_at.utcoffset() is None:
        return False
    match = _AUTOMATIC_BASENAME.fullmatch(basename)
    if match is None or f"{match.group(1)}-{match.group(2)}" != created_at.strftime("%Y%m%d-%H%M%S"):
        return False
    identifier = UUID(hex=match.group(3))
    return identifier.version == 7 and identifier.int >> 62 & 0b11 == 0b10 and identifier.int >> 80 == _unix_milliseconds(created_at)


def _uuid7(created_at: datetime) -> UUID:
    """Create an RFC 9562 UUIDv7 using the frozen job-creation instant."""

    timestamp_ms = _unix_milliseconds(created_at)
    if not 0 <= timestamp_ms < 1 << 48:
        raise ValueError("created_at is outside the UUIDv7 timestamp range")
    random_a = randbits(12)
    random_b = randbits(62)
    value = timestamp_ms << 80 | 0x7 << 76 | random_a << 64 | 0b10 << 62 | random_b
    return UUID(int=value)


def _unix_milliseconds(created_at: datetime) -> int:
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    delta = created_at.astimezone(timezone.utc) - epoch
    return delta.days * 86_400_000 + delta.seconds * 1_000 + delta.microseconds // 1_000


class OutputPathRegistry:
    """Reserve destinations across jobs in the current application process."""

    def __init__(self) -> None:
        self._reserved: set[Path] = set()
        self._lock = threading.Lock()

    @staticmethod
    def _key(path: Path) -> Path:
        return path.expanduser().resolve(strict=False)

    def reserve_generated(self, directory: Path, created_at: datetime) -> Path:
        """Reserve a generated name, adding monotonically increasing suffixes."""

        base_path = directory / automatic_output_basename(created_at)
        with self._lock:
            candidate = base_path
            counter = 0
            while candidate.exists() or self._key(candidate) in self._reserved:
                counter += 1
                candidate = base_path.with_name(f"{base_path.stem}-{counter:02d}{base_path.suffix}")
            self._reserved.add(self._key(candidate))
            return candidate

    def reserve_frozen_generated(self, directory: Path, basename: str) -> Path:
        """Reserve an already frozen generated name without silently changing it."""

        candidate = directory / basename
        key = self._key(candidate)
        with self._lock:
            if candidate.exists() or key in self._reserved:
                raise OutputCollisionError(f"generated destination is no longer available: {candidate}")
            self._reserved.add(key)
        return candidate

    def reserve_explicit(self, path: Path, mode: OverwriteMode) -> Path:
        """Reserve an explicit path according to its overwrite policy."""

        key = self._key(path)
        with self._lock:
            if key in self._reserved:
                raise OutputCollisionError(f"destination is reserved by another job: {path}")
            if mode is OverwriteMode.NO_OVERWRITE and path.exists():
                raise OutputCollisionError(f"destination already exists: {path}")
            self._reserved.add(key)
        return path

    def release(self, path: Path) -> None:
        """Release a path when a job terminates or diagnostic preflight ends."""

        with self._lock:
            self._reserved.discard(self._key(path))
