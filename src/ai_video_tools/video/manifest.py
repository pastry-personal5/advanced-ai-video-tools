"""Safe FFmpeg concat-demuxer manifest generation."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path


def _quote_concat_path(path: Path) -> str:
    value = str(path.resolve(strict=False))
    if any(character in value for character in ("\x00", "\n", "\r")):
        raise ValueError("concat paths cannot contain NUL or newline characters")
    return "'" + value.replace("'", "'\\''") + "'"


def concat_manifest_text(inputs: Iterable[Path]) -> str:
    """Render ordered absolute paths using concat-demuxer token escaping."""

    paths = tuple(inputs)
    if not paths:
        raise ValueError("a concat manifest requires at least one input")
    lines = ["ffconcat version 1.0"]
    lines.extend(f"file {_quote_concat_path(path)}" for path in paths)
    return "\n".join(lines) + "\n"


def write_concat_manifest(path: Path, inputs: Iterable[Path]) -> None:
    """Write one UTF-8 concat manifest into an already-owned workspace."""

    path.write_text(concat_manifest_text(inputs), encoding="utf-8", newline="\n")
