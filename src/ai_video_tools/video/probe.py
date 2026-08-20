"""Safe FFprobe invocation and JSON conversion to typed media models."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Protocol, cast

from ai_video_tools.core.models import (
    AudioStream,
    MediaProbe,
    OtherStream,
    Rational,
    VideoStream,
)


class ProbeError(RuntimeError):
    """FFprobe could not inspect an input or returned invalid data."""


class MediaProber(Protocol):
    """Replaceable probing boundary used by preflight."""

    def probe(self, path: Path) -> MediaProbe:
        """Inspect one media input."""


def _decimal(value: object) -> Decimal | None:
    if value in (None, "", "N/A"):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _integer(value: object) -> int | None:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    integral = parsed.to_integral_value()
    return int(integral) if parsed == integral else None


def _rational(value: object, default: Rational | None = None) -> Rational | None:
    if not isinstance(value, str) or not value:
        return default
    try:
        rational = Rational.parse(value)
    except (TypeError, ValueError):
        return default
    return rational if rational.positive else default


def _rotation(stream: Mapping[str, object]) -> int:
    tags = stream.get("tags")
    if isinstance(tags, Mapping):
        tagged = _integer(tags.get("rotate"))
        if tagged is not None:
            return tagged % 360
    side_data = stream.get("side_data_list")
    if isinstance(side_data, list):
        for item in side_data:
            if isinstance(item, Mapping):
                rotated = _integer(item.get("rotation"))
                if rotated is not None:
                    return rotated % 360
    return 0


def _has_hdr_metadata(stream: Mapping[str, object]) -> bool:
    side_data = stream.get("side_data_list")
    if not isinstance(side_data, list):
        return False
    hdr_markers = (
        "mastering display",
        "content light",
        "dolby vision",
        "dovi",
        "hdr10+",
        "hdr dynamic metadata",
    )
    return any(isinstance(item, Mapping) and any(marker in str(item.get("side_data_type", "")).lower() for marker in hdr_markers) for item in side_data)


def parse_probe_document(path: Path, document: Mapping[str, object]) -> MediaProbe:
    """Convert an FFprobe JSON object into immutable domain models."""

    streams_value = document.get("streams", [])
    if not isinstance(streams_value, list):
        raise ProbeError("FFprobe JSON field 'streams' is not a list")
    videos: list[VideoStream] = []
    audios: list[AudioStream] = []
    others: list[OtherStream] = []
    for raw_stream in streams_value:
        if not isinstance(raw_stream, Mapping):
            raise ProbeError("FFprobe returned a non-object stream")
        stream = cast(Mapping[str, object], raw_stream)
        kind = str(stream.get("codec_type", "unknown"))
        index = _integer(stream.get("index"))
        codec = str(stream.get("codec_name", "unknown"))
        if index is None:
            raise ProbeError("FFprobe stream is missing a numeric index")
        disposition = stream.get("disposition")
        attached_picture = isinstance(disposition, Mapping) and _integer(disposition.get("attached_pic")) == 1
        if kind == "video" and attached_picture:
            others.append(OtherStream(index=index, kind="attachment", codec_name=codec))
        elif kind == "video":
            width = _integer(stream.get("width"))
            height = _integer(stream.get("height"))
            if width is None or height is None or width <= 0 or height <= 0:
                raise ProbeError(f"video stream {index} has invalid dimensions")
            videos.append(
                VideoStream(
                    index=index,
                    codec_name=codec,
                    width=width,
                    height=height,
                    pixel_format=_optional_string(stream.get("pix_fmt")),
                    sample_aspect_ratio=_rational(stream.get("sample_aspect_ratio"), Rational(1, 1)) or Rational(1, 1),
                    real_frame_rate=_rational(stream.get("r_frame_rate")),
                    average_frame_rate=_rational(stream.get("avg_frame_rate")),
                    time_base=_rational(stream.get("time_base")),
                    duration=_decimal(stream.get("duration")),
                    color_space=_optional_string(stream.get("color_space")),
                    color_transfer=_optional_string(stream.get("color_transfer")),
                    color_primaries=_optional_string(stream.get("color_primaries")),
                    color_range=_optional_string(stream.get("color_range")),
                    rotation=_rotation(stream),
                    has_hdr_metadata=_has_hdr_metadata(stream),
                )
            )
        elif kind == "audio":
            audios.append(
                AudioStream(
                    index=index,
                    codec_name=codec,
                    sample_rate=_integer(stream.get("sample_rate")),
                    channels=_integer(stream.get("channels")),
                    channel_layout=_optional_string(stream.get("channel_layout")),
                    duration=_decimal(stream.get("duration")),
                )
            )
        else:
            others.append(OtherStream(index=index, kind=kind, codec_name=codec))
    format_value = document.get("format")
    duration = _decimal(format_value.get("duration")) if isinstance(format_value, Mapping) else None
    chapters = document.get("chapters", [])
    chapter_count = len(chapters) if isinstance(chapters, list) else 0
    return MediaProbe(
        path=path,
        duration=duration,
        video_streams=tuple(videos),
        audio_streams=tuple(audios),
        other_streams=tuple(others),
        chapter_count=chapter_count,
    )


def _optional_string(value: object) -> str | None:
    if value in (None, "", "unknown", "reserved", "unspecified"):
        return None
    return str(value).lower()


class FFprobeClient:
    """Subprocess-backed implementation of the probing boundary."""

    def __init__(self, executable: Path, timeout_seconds: float = 30.0) -> None:
        self._executable = executable
        self._timeout_seconds = timeout_seconds

    def probe(self, path: Path) -> MediaProbe:
        """Run FFprobe once and convert its JSON result."""

        arguments: Sequence[str] = (
            str(self._executable),
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-show_chapters",
            "-of",
            "json",
            str(path),
        )
        try:
            result = subprocess.run(
                arguments,
                check=False,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ProbeError(f"could not run FFprobe for {path}: {error}") from error
        if result.returncode != 0:
            detail = result.stderr.strip() or "no diagnostic output"
            raise ProbeError(f"FFprobe rejected {path}: {detail}")
        try:
            parsed = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise ProbeError(f"FFprobe returned invalid JSON for {path}") from error
        if not isinstance(parsed, Mapping):
            raise ProbeError(f"FFprobe returned a non-object document for {path}")
        return parse_probe_document(path, parsed)
