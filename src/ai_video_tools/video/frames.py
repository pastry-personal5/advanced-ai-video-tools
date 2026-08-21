"""Shared deterministic RGB PNG frame-inventory validation."""

from __future__ import annotations

import re
from pathlib import Path

FRAME_FILENAME_TEMPLATE = "frame-%09d.png"
_FRAME_NAME = re.compile(r"^frame-(\d{9})\.png$")
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class FrameInventoryError(RuntimeError):
    """A frame directory is missing, malformed, or unexpectedly numbered."""


class FrameInventoryVerifier:
    """Validate deterministic names and lightweight PNG image contracts."""

    @staticmethod
    def _verify_png(path: Path, expected_width: int, expected_height: int) -> None:
        if path.is_symlink() or not path.is_file():
            raise FrameInventoryError(f"frame is not a regular file: {path.name}")
        try:
            with path.open("rb") as frame_file:
                header = frame_file.read(26)
        except OSError as error:
            raise FrameInventoryError(f"could not read frame: {path.name}") from error
        if len(header) != 26 or header[:8] != _PNG_SIGNATURE or header[8:12] != b"\x00\x00\x00\r" or header[12:16] != b"IHDR":
            raise FrameInventoryError(f"frame has an invalid PNG header: {path.name}")
        width = int.from_bytes(header[16:20], "big")
        height = int.from_bytes(header[20:24], "big")
        bit_depth = header[24]
        color_type = header[25]
        if (width, height) != (expected_width, expected_height):
            raise FrameInventoryError(f"frame dimensions differ from the expected dimensions: {path.name}")
        if bit_depth != 8 or color_type != 2:
            raise FrameInventoryError(f"frame is not 8-bit RGB PNG: {path.name}")

    def verify(self, directory: Path, expected_width: int, expected_height: int, expected_count: int, *, count_tolerance: int = 0) -> int:
        """Return the contiguous count when names, PNGs, and count are valid."""

        if expected_width <= 0 or expected_height <= 0 or expected_count <= 0 or count_tolerance < 0:
            raise ValueError("frame inventory expectations must be positive")
        if not directory.is_dir() or directory.is_symlink():
            raise FrameInventoryError("frame output directory is missing or unsafe")
        count = 0
        lowest: int | None = None
        highest: int | None = None
        try:
            entries = directory.iterdir()
            for entry in entries:
                match = _FRAME_NAME.fullmatch(entry.name)
                if match is None:
                    raise FrameInventoryError(f"unexpected frame output: {entry.name}")
                number = int(match.group(1))
                self._verify_png(entry, expected_width, expected_height)
                count += 1
                lowest = number if lowest is None else min(lowest, number)
                highest = number if highest is None else max(highest, number)
        except OSError as error:
            raise FrameInventoryError("could not inventory frames") from error
        if count == 0:
            raise FrameInventoryError("frame processing produced no images")
        if lowest != 1 or highest != count:
            raise FrameInventoryError("frame numbering is not contiguous from frame 1")
        if abs(count - expected_count) > count_tolerance:
            raise FrameInventoryError(f"frame count differs from the expected inventory: found {count}, expected {expected_count}")
        return count
