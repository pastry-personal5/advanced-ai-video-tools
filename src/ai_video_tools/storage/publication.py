"""Same-filesystem partial output creation and atomic MP4 publication."""

from __future__ import annotations

import os
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from ai_video_tools.storage.naming import OutputCollisionError


class PublicationError(RuntimeError):
    """A verified partial output could not be safely published or discarded."""


@dataclass(frozen=True)
class PartialOutput:
    """Identity proving that a temporary path was allocated for one destination."""

    destination: Path
    path: Path
    identifier: str


class AtomicOutputPublisher:
    """Publish verified files without exposing incomplete or clobbered output."""

    @staticmethod
    def create_partial(destination: Path) -> PartialOutput:
        """Reserve an empty random partial beside the destination."""

        resolved_destination = destination.expanduser().resolve(strict=False)
        parent = resolved_destination.parent
        if resolved_destination.suffix.lower() != ".mp4" or not parent.is_dir():
            raise PublicationError(f"final destination must be an MP4 in an existing directory: {resolved_destination}")
        identifier = uuid.uuid4().hex
        try:
            descriptor, raw_path = tempfile.mkstemp(prefix=f".{resolved_destination.name}.{identifier}-", suffix=".partial.mp4", dir=parent)
            os.close(descriptor)
        except OSError as error:
            raise PublicationError(f"could not create partial output beside {resolved_destination}") from error
        return PartialOutput(resolved_destination, Path(raw_path).resolve(), identifier)

    @staticmethod
    def _validate(partial: PartialOutput) -> tuple[Path, Path]:
        destination = partial.destination.resolve(strict=False)
        path = partial.path.resolve(strict=False)
        expected_prefix = f".{destination.name}.{partial.identifier}-"
        if path.parent != destination.parent or not path.name.startswith(expected_prefix) or not path.name.endswith(".partial.mp4"):
            raise PublicationError(f"partial output identity does not match its destination: {path}")
        return path, destination

    def discard(self, partial: PartialOutput) -> None:
        """Remove only the exact partial allocated by this publisher."""

        path, _destination = self._validate(partial)
        try:
            path.unlink(missing_ok=True)
        except OSError as error:
            raise PublicationError(f"could not remove partial output: {path}") from error

    def publish(self, partial: PartialOutput, *, replace: bool) -> Path:
        """Atomically replace, or atomically create without replacement."""

        path, destination = self._validate(partial)
        if path.is_symlink() or not path.is_file() or path.stat().st_size <= 0:
            raise PublicationError(f"partial output is missing, unsafe, or empty: {path}")
        try:
            with path.open("rb") as partial_file:
                os.fsync(partial_file.fileno())
            if replace:
                os.replace(path, destination)
            else:
                os.link(path, destination, follow_symlinks=False)
                path.unlink()
        except FileExistsError as error:
            raise OutputCollisionError(f"destination appeared before publication: {destination}") from error
        except OSError as error:
            raise PublicationError(f"could not atomically publish output to {destination}") from error
        return destination
