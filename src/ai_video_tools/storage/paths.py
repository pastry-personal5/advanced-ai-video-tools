"""Qt-standard application locations without hard-coded home directories."""

from pathlib import Path


def application_data_directory() -> Path:
    """Return the platform-native persistent application data directory."""

    # pylint: disable-next=import-outside-toplevel,no-name-in-module
    from PySide6.QtCore import QStandardPaths

    location = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    if not location:
        raise RuntimeError("Qt could not resolve an application data directory")
    return Path(location)


def job_cache_directory() -> Path:
    """Return the platform-native root for owned temporary job workspaces."""

    # pylint: disable-next=import-outside-toplevel,no-name-in-module
    from PySide6.QtCore import QStandardPaths

    location = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation)
    if not location:
        raise RuntimeError("Qt could not resolve an application cache directory")
    return Path(location) / "jobs"
