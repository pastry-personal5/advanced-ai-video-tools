"""Qt-standard application locations and the guarded v1 settings location."""

import sys
from pathlib import Path

LEGACY_MACOS_APPLICATION_DATA_DIRECTORY = Path.home() / "Library" / "Application Support" / "AI Video Tools"


def application_data_directory() -> Path:
    """Return the platform-native persistent application data directory."""

    # pylint: disable-next=import-outside-toplevel,no-name-in-module
    from PySide6.QtCore import QStandardPaths

    location = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    if not location:
        raise RuntimeError("Qt could not resolve an application data directory")
    return Path(location)


def legacy_application_data_directory() -> Path | None:
    """Return the exact v1 macOS settings directory, when applicable."""

    if sys.platform != "darwin":
        return None
    return LEGACY_MACOS_APPLICATION_DATA_DIRECTORY


def job_cache_directory() -> Path:
    """Return the platform-native root for owned temporary job workspaces."""

    # pylint: disable-next=import-outside-toplevel,no-name-in-module
    from PySide6.QtCore import QStandardPaths

    location = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation)
    if not location:
        raise RuntimeError("Qt could not resolve an application cache directory")
    return Path(location) / "jobs"
