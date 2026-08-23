"""Typed, versioned, atomic persistence for non-secret application settings."""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import dataclass, field
from json import JSONDecodeError
from pathlib import Path
from typing import Mapping

from loguru import logger

from ai_video_tools.core.models import OverwriteMode, ToolOverrides
from ai_video_tools.storage.paths import application_data_directory

SETTINGS_SCHEMA_VERSION = 1
DEFAULT_TARGET_HEIGHT = 2160
DEFAULT_PREVIEW_VOLUME = 100


class SettingsError(RuntimeError):
    """Application settings could not be loaded or saved safely."""


class UnsupportedSettingsVersion(SettingsError):
    """The settings file belongs to a schema this application cannot read."""


class _InvalidSettings(ValueError):
    """The settings document is corrupt or violates its declared schema."""


@dataclass(frozen=True)
class ApplicationSettings:
    """Persistent user preferences shared by the GUI and other frontends."""

    tools: ToolOverrides = field(default_factory=ToolOverrides)
    recent_input_directory: Path | None = None
    recent_output_directory: Path | None = None
    target_height: int = DEFAULT_TARGET_HEIGHT
    overwrite_mode: OverwriteMode = OverwriteMode.REPLACE
    preview_muted: bool = True
    preview_volume: int = DEFAULT_PREVIEW_VOLUME

    def __post_init__(self) -> None:
        if not isinstance(self.tools, ToolOverrides):
            raise TypeError("tools must be a ToolOverrides instance")
        if not isinstance(self.overwrite_mode, OverwriteMode):
            raise TypeError("overwrite mode must be an OverwriteMode")
        if not isinstance(self.preview_muted, bool):
            raise TypeError("preview muted must be a boolean")
        if isinstance(self.preview_volume, bool) or not isinstance(self.preview_volume, int) or not 0 <= self.preview_volume <= 100:
            raise ValueError("preview volume must be an integer from 0 to 100")
        for path in (
            self.tools.ffmpeg,
            self.tools.ffprobe,
            self.tools.realesrgan,
            self.tools.model_directory,
            self.recent_input_directory,
            self.recent_output_directory,
        ):
            if path is not None and not isinstance(path, Path):
                raise TypeError("persisted paths must be pathlib.Path instances or None")
        if isinstance(self.target_height, bool) or self.target_height <= 0 or self.target_height % 2:
            raise ValueError("target height must be a positive even integer")


class SettingsStore:
    """Load and atomically save one local JSON settings document."""

    def __init__(self, path: Path | None = None) -> None:
        selected = path if path is not None else application_data_directory() / "settings.json"
        self._path = selected.expanduser().absolute()

    @property
    def path(self) -> Path:
        """Return the settings document location."""

        return self._path

    def load(self) -> ApplicationSettings:
        """Load settings, returning defaults when no document exists.

        Malformed documents are quarantined beside the settings file. Documents
        from an unsupported schema are left untouched and rejected explicitly.
        """

        self._reject_symlink()
        if not self._path.exists():
            return ApplicationSettings()
        try:
            document = json.loads(self._path.read_text(encoding="utf-8"))
            settings = _decode_document(document)
        except (JSONDecodeError, UnicodeError, _InvalidSettings):
            quarantined = self._quarantine_invalid_document()
            logger.warning("Invalid application settings quarantined as {}", quarantined.name)
            return ApplicationSettings()
        except OSError as error:
            raise SettingsError("could not read application settings") from error
        logger.debug("Application settings loaded")
        return settings

    def save(self, settings: ApplicationSettings) -> None:
        """Durably replace the settings document without exposing a partial file."""

        if not isinstance(settings, ApplicationSettings):
            raise TypeError("settings must be an ApplicationSettings instance")
        self._reject_symlink()
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            descriptor, raw_temporary = tempfile.mkstemp(prefix=f".{self._path.name}-", suffix=".tmp", dir=self._path.parent)
        except OSError as error:
            raise SettingsError("could not prepare application settings storage") from error
        temporary = Path(raw_temporary)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(_encode_document(settings), stream, ensure_ascii=False, indent=2, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self._path)
        except (OSError, TypeError, ValueError) as error:
            try:
                os.close(descriptor)
            except OSError:
                pass
            temporary.unlink(missing_ok=True)
            raise SettingsError("could not atomically save application settings") from error
        logger.debug("Application settings saved")

    def _reject_symlink(self) -> None:
        if self._path.is_symlink():
            raise SettingsError("application settings path must not be a symbolic link")

    def _quarantine_invalid_document(self) -> Path:
        quarantined = self._path.with_name(f"{self._path.stem}.corrupt-{uuid.uuid4().hex}{self._path.suffix}")
        try:
            os.replace(self._path, quarantined)
        except OSError as error:
            raise SettingsError("could not quarantine invalid application settings") from error
        return quarantined


def _encode_document(settings: ApplicationSettings) -> dict[str, object]:
    return {
        "schema_version": SETTINGS_SCHEMA_VERSION,
        "processing": {"overwrite_mode": settings.overwrite_mode.value, "target_height": settings.target_height},
        "preview": {"muted": settings.preview_muted, "volume": settings.preview_volume},
        "recent": {"input_directory": _encode_path(settings.recent_input_directory), "output_directory": _encode_path(settings.recent_output_directory)},
        "tools": {
            "ffmpeg": _encode_path(settings.tools.ffmpeg),
            "ffprobe": _encode_path(settings.tools.ffprobe),
            "model_directory": _encode_path(settings.tools.model_directory),
            "realesrgan": _encode_path(settings.tools.realesrgan),
        },
    }


def _decode_document(value: object) -> ApplicationSettings:
    document = _mapping(value, "settings")
    version = document.get("schema_version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise _InvalidSettings("schema_version must be an integer")
    if version != SETTINGS_SCHEMA_VERSION:
        raise UnsupportedSettingsVersion(f"settings schema version {version} is unsupported; expected {SETTINGS_SCHEMA_VERSION}")
    tools = _mapping(document.get("tools", {}), "tools")
    recent = _mapping(document.get("recent", {}), "recent")
    processing = _mapping(document.get("processing", {}), "processing")
    preview = _mapping(document.get("preview", {}), "preview")
    height = processing.get("target_height", DEFAULT_TARGET_HEIGHT)
    if isinstance(height, bool) or not isinstance(height, int):
        raise _InvalidSettings("processing.target_height must be an integer")
    raw_overwrite = processing.get("overwrite_mode", OverwriteMode.REPLACE.value)
    if not isinstance(raw_overwrite, str):
        raise _InvalidSettings("processing.overwrite_mode must be a string")
    muted = preview.get("muted", True)
    volume = preview.get("volume", DEFAULT_PREVIEW_VOLUME)
    if not isinstance(muted, bool):
        raise _InvalidSettings("preview.muted must be a boolean")
    if isinstance(volume, bool) or not isinstance(volume, int) or not 0 <= volume <= 100:
        raise _InvalidSettings("preview.volume must be an integer from 0 to 100")
    try:
        overwrite = OverwriteMode(raw_overwrite)
        return ApplicationSettings(
            tools=ToolOverrides(
                ffmpeg=_optional_path(tools.get("ffmpeg"), "tools.ffmpeg"),
                ffprobe=_optional_path(tools.get("ffprobe"), "tools.ffprobe"),
                realesrgan=_optional_path(tools.get("realesrgan"), "tools.realesrgan"),
                model_directory=_optional_path(tools.get("model_directory"), "tools.model_directory"),
            ),
            recent_input_directory=_optional_path(recent.get("input_directory"), "recent.input_directory"),
            recent_output_directory=_optional_path(recent.get("output_directory"), "recent.output_directory"),
            target_height=height,
            overwrite_mode=overwrite,
            preview_muted=muted,
            preview_volume=volume,
        )
    except ValueError as error:
        raise _InvalidSettings(str(error)) from error


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise _InvalidSettings(f"{field_name} must be an object")
    return value


def _optional_path(value: object, field_name: str) -> Path | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or "\0" in value:
        raise _InvalidSettings(f"{field_name} must be null or a non-empty path string")
    return Path(value)


def _encode_path(path: Path | None) -> str | None:
    return str(path) if path is not None else None
