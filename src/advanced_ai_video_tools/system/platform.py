"""Version 1 platform policy."""

from __future__ import annotations

import platform
import re
from dataclasses import dataclass

MINIMUM_MACOS = (26, 5, 2)


@dataclass(frozen=True)
class PlatformInfo:
    """Host properties that determine v1 support."""

    system: str
    machine: str
    macos_version: str

    @classmethod
    def current(cls) -> PlatformInfo:
        """Read the current host without mutating global process state."""

        return cls(platform.system(), platform.machine(), platform.mac_ver()[0])


def parse_version(value: str) -> tuple[int, ...]:
    """Parse the numeric prefix of an operating-system version."""

    match = re.match(r"^(\d+(?:\.\d+)*)", value)
    if not match:
        raise ValueError(f"invalid macOS version: {value!r}")
    return tuple(int(part) for part in match.group(1).split("."))


def platform_error(info: PlatformInfo) -> str | None:
    """Return an actionable reason when the host is outside the v1 target."""

    if info.system != "Darwin":
        return "Version 1 requires macOS; this host is not Darwin."
    if info.machine.lower() not in {"arm64", "aarch64"}:
        return "Version 1 requires an Apple Silicon (arm64) Mac."
    try:
        version = parse_version(info.macos_version)
    except ValueError as error:
        return str(error)
    padded = version + (0,) * (len(MINIMUM_MACOS) - len(version))
    if padded < MINIMUM_MACOS:
        required = ".".join(str(part) for part in MINIMUM_MACOS)
        return f"Version 1 requires macOS {required} or later."
    return None
