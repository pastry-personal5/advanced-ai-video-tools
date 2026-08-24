"""Narrow macOS hardware checks for opt-in native acceptance tests."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Mapping, Sequence

from advanced_ai_video_tools.system.platform import PlatformInfo, platform_error

CommandRunner = Callable[[Sequence[str], float], subprocess.CompletedProcess[str]]

_METAL_PROFILE_COMMAND = ("system_profiler", "SPDisplaysDataType", "-json")


def _default_runner(arguments: Sequence[str], timeout: float) -> subprocess.CompletedProcess[str]:
    """Run the read-only macOS display capability query without a shell."""

    return subprocess.run(list(arguments), check=False, capture_output=True, text=True, timeout=timeout, shell=False)


def _metal_value_is_supported(value: object) -> bool:
    """Recognize the supported forms emitted by ``system_profiler``."""

    if isinstance(value, bool):
        return value
    if not isinstance(value, str):
        return False
    normalized = value.strip().lower()
    return bool(normalized) and "not supported" not in normalized and "unsupported" not in normalized and normalized != "none"


def _reports_metal_support(value: object) -> bool:
    """Find an affirmative Metal capability in a display-profiler payload."""

    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized_key = key.lower() if isinstance(key, str) else ""
            is_metal_key = "metal" in normalized_key or ("mtl" in normalized_key and "gpu" in normalized_key)
            if is_metal_key and _metal_value_is_supported(child):
                return True
            if _reports_metal_support(child):
                return True
    elif isinstance(value, (list, tuple)):
        return any(_reports_metal_support(child) for child in value)
    return False


def apple_silicon_metal_error(*, info: PlatformInfo | None = None, runner: CommandRunner = _default_runner) -> str | None:
    """Return why native Metal acceptance cannot run, or ``None`` when ready.

    This capability check is intentionally separate from the application runtime
    policy: it only gates opt-in local acceptance tests and never changes
    preflight or tool discovery.
    """

    target_error = platform_error(info or PlatformInfo.current())
    if target_error is not None:
        return target_error
    try:
        result = runner(_METAL_PROFILE_COMMAND, 15.0)
    except (OSError, subprocess.TimeoutExpired) as error:
        return f"could not inspect Metal support: {error}"
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        suffix = f": {detail[0]}" if detail else ""
        return "system_profiler could not inspect Metal support" + suffix
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        return f"system_profiler returned invalid Metal data: {error.msg}"
    if not _reports_metal_support(payload):
        return "Apple Silicon Metal support was not reported by system_profiler."
    return None
