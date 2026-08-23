"""Tests for typed, versioned, atomic application settings persistence."""

import json
import os
import stat
from pathlib import Path

import pytest

from ai_video_tools.core.models import OverwriteMode, ToolOverrides
from ai_video_tools.system.settings import (
    ApplicationSettings,
    SettingsError,
    SettingsStore,
    UnsupportedSettingsVersion,
)


def test_missing_settings_file_returns_safe_defaults(tmp_path: Path) -> None:
    """A first launch needs no pre-existing application-data directory."""

    store = SettingsStore(tmp_path / "missing" / "settings.json")

    assert store.load() == ApplicationSettings()
    assert store.load().target_height == 2160
    assert store.load().overwrite_mode is OverwriteMode.REPLACE


def test_settings_round_trip_with_private_atomic_file(tmp_path: Path) -> None:
    """All supported preferences survive JSON serialization with private mode."""

    path = tmp_path / "application-data" / "settings.json"
    settings = ApplicationSettings(
        tools=ToolOverrides(
            ffmpeg=Path("/opt/tools/ffmpeg"),
            ffprobe=Path("/opt/tools/ffprobe"),
            realesrgan=Path("/opt/tools/realesrgan-ncnn-vulkan"),
            model_directory=Path("/opt/tools/models"),
        ),
        recent_input_directory=Path("/media/source clips"),
        recent_output_directory=Path("/media/exports"),
        target_height=1080,
        overwrite_mode=OverwriteMode.NO_OVERWRITE,
        preview_muted=False,
        preview_volume=42,
    )
    store = SettingsStore(path)

    store.save(settings)

    assert store.load() == settings
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["schema_version"] == 1
    assert document["processing"] == {"overwrite_mode": "no_overwrite", "target_height": 1080}
    assert document["preview"] == {"muted": False, "volume": 42}
    assert "acknowledge_dropped_streams" not in path.read_text(encoding="utf-8")
    assert not list(path.parent.glob(".settings.json-*.tmp"))


def test_invalid_json_is_quarantined_and_defaults_are_recovered(tmp_path: Path) -> None:
    """A torn or manually damaged document cannot prevent application startup."""

    path = tmp_path / "settings.json"
    path.write_text('{"schema_version": 1,', encoding="utf-8")
    store = SettingsStore(path)

    assert store.load() == ApplicationSettings()
    assert not path.exists()
    quarantined = list(tmp_path.glob("settings.corrupt-*.json"))
    assert len(quarantined) == 1
    assert quarantined[0].read_text(encoding="utf-8") == '{"schema_version": 1,'


@pytest.mark.parametrize(
    "document",
    [
        {"schema_version": True},
        {"schema_version": 1, "processing": {"target_height": 1079}},
        {"schema_version": 1, "tools": {"ffmpeg": ""}},
        {"schema_version": 1, "recent": []},
        {"schema_version": 1, "preview": {"muted": "false"}},
        {"schema_version": 1, "preview": {"volume": 101}},
    ],
)
def test_schema_violations_are_quarantined(tmp_path: Path, document: object) -> None:
    """Wrong field types and unsafe values recover through the corruption path."""

    path = tmp_path / "settings.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    assert SettingsStore(path).load() == ApplicationSettings()
    assert not path.exists()
    assert len(list(tmp_path.glob("settings.corrupt-*.json"))) == 1


def test_newer_schema_is_preserved_and_rejected(tmp_path: Path) -> None:
    """An older binary must never quarantine or overwrite valid future data."""

    path = tmp_path / "settings.json"
    contents = '{"schema_version": 2, "future": true}\n'
    path.write_text(contents, encoding="utf-8")

    with pytest.raises(UnsupportedSettingsVersion, match="version 2"):
        SettingsStore(path).load()

    assert path.read_text(encoding="utf-8") == contents
    assert not list(tmp_path.glob("settings.corrupt-*.json"))


def test_atomic_replace_failure_preserves_previous_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed commit leaves the prior complete JSON file and no temp debris."""

    path = tmp_path / "settings.json"
    store = SettingsStore(path)
    original = ApplicationSettings(target_height=720)
    store.save(original)

    def fail_replace(_source: object, _destination: object) -> None:
        raise OSError("simulated replacement failure")

    monkeypatch.setattr("ai_video_tools.system.settings.os.replace", fail_replace)
    with pytest.raises(SettingsError, match="atomically save"):
        store.save(ApplicationSettings(target_height=1080))

    assert json.loads(path.read_text(encoding="utf-8"))["processing"]["target_height"] == 720
    assert not list(tmp_path.glob(".settings.json-*.tmp"))


def test_symlink_settings_path_is_rejected(tmp_path: Path) -> None:
    """Persistence cannot be redirected to an unintended file through a symlink."""

    target = tmp_path / "target.json"
    target.write_text('{"schema_version": 1}', encoding="utf-8")
    link = tmp_path / "settings.json"
    os.symlink(target, link)
    store = SettingsStore(link)

    with pytest.raises(SettingsError, match="symbolic link"):
        store.load()
    with pytest.raises(SettingsError, match="symbolic link"):
        store.save(ApplicationSettings())

    assert target.read_text(encoding="utf-8") == '{"schema_version": 1}'


def test_unknown_fields_do_not_break_forward_compatible_minor_changes(tmp_path: Path) -> None:
    """Extra keys within a known schema are ignored without losing known values."""

    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"schema_version": 1, "future_hint": "ignored", "processing": {"target_height": 1440, "future_option": 3}}), encoding="utf-8")

    assert SettingsStore(path).load().target_height == 1440
