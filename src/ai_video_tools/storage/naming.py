"""Timezone-aware output naming and process-local path reservation."""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from pathlib import Path
from secrets import randbits
from uuid import UUID

from ai_video_tools.core.models import OverwriteMode


class OutputCollisionError(FileExistsError):
    """Raised when no-overwrite publication targets an occupied path."""


def automatic_output_basename(created_at: datetime) -> str:
    """Build the canonical local-time basename with a compact UUIDv7."""

    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise ValueError("created_at must be timezone-aware")
    identifier = _uuid7(created_at)
    return f"{created_at.strftime('ai-video-%Y%m%d-%H%M%S')}-{identifier.hex}.mp4"


def _uuid7(created_at: datetime) -> UUID:
    """Create an RFC 9562 UUIDv7 using the frozen job-creation instant."""

    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    delta = created_at.astimezone(timezone.utc) - epoch
    timestamp_ms = delta.days * 86_400_000 + delta.seconds * 1_000 + delta.microseconds // 1_000
    if not 0 <= timestamp_ms < 1 << 48:
        raise ValueError("created_at is outside the UUIDv7 timestamp range")
    random_a = randbits(12)
    random_b = randbits(62)
    value = timestamp_ms << 80 | 0x7 << 76 | random_a << 64 | 0b10 << 62 | random_b
    return UUID(int=value)


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
