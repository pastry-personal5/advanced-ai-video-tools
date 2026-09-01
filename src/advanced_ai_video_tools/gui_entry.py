"""Standalone GUI entry point for the macOS application bundle."""

from __future__ import annotations

import os

from advanced_ai_video_tools.gui.application import run_gui

_COMMON_MACOS_TOOL_PATHS = ("/opt/homebrew/bin", "/usr/local/bin", "/opt/local/bin")


def _augment_macos_path() -> None:
    """Make standard user-managed macOS tool locations visible to Finder launches."""

    current_entries = [path for path in os.environ.get("PATH", "").split(os.pathsep) if path]
    entries = [path for path in _COMMON_MACOS_TOOL_PATHS if path not in current_entries]
    entries.extend(current_entries)
    os.environ["PATH"] = os.pathsep.join(entries)


if __name__ == "__main__":
    _augment_macos_path()
    raise SystemExit(run_gui())
