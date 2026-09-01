"""Tests for the canonical v2 identity map and its runtime consumers."""

from datetime import datetime
from pathlib import Path

from advanced_ai_video_tools import gui_entry
from advanced_ai_video_tools.identity import IDENTITY
from advanced_ai_video_tools.storage.naming import automatic_output_basename
from advanced_ai_video_tools.storage.workspaces import OwnedWorkspace


def test_identity_map_contains_approved_v2_values() -> None:
    """The approved display, package, command, and bundle identities remain fixed."""

    assert IDENTITY.display_name == "Advanced AI Video Tools"
    assert IDENTITY.distribution_name == "advanced-ai-video-tools"
    assert IDENTITY.import_package_name == "advanced_ai_video_tools"
    assert IDENTITY.primary_command == "advanced-ai-video-tools"
    assert IDENTITY.legacy_command == "ai-video-tools"
    assert IDENTITY.bundle_identifier == "com.pastrypersonal5.advancedaivideotools"
    assert IDENTITY.output_prefix == "ai-"
    assert IDENTITY.gui_lock_filename == "advanced-ai-video-tools-gui.lock"


def test_packaging_surfaces_match_identity_map() -> None:
    """Static package and macOS bundle metadata use the canonical identity."""

    repository_root = Path(__file__).parents[1]
    project = (repository_root / "pyproject.toml").read_text(encoding="utf-8")
    plist = (repository_root / "packaging/macos/Info.plist").read_text(encoding="utf-8")

    assert f'name = "{IDENTITY.distribution_name}"' in project
    assert f'{IDENTITY.primary_command} = "{IDENTITY.import_package_name}.cli:main"' in project
    assert f'{IDENTITY.legacy_command} = "{IDENTITY.import_package_name}.cli:main"' in project
    assert f"<string>{IDENTITY.display_name}</string>" in plist
    assert f"<string>{IDENTITY.bundle_identifier}</string>" in plist

    gui_entry_source = (repository_root / "src/advanced_ai_video_tools/gui_entry.py").read_text(encoding="utf-8")
    assert "run_gui()" in gui_entry_source
    assert "cli" not in gui_entry_source

    gui_entry_source = (repository_root / "src/advanced_ai_video_tools/gui_entry.py").read_text(encoding="utf-8")
    assert "run_gui()" in gui_entry_source
    assert "cli" not in gui_entry_source


def test_gui_bundle_entry_point_preserves_and_augments_finder_path(monkeypatch) -> None:
    """Finder launches expose common macOS tool locations without replacing PATH."""

    monkeypatch.setenv("PATH", "/custom/bin:/usr/bin")
    gui_entry._augment_macos_path()  # pylint: disable=protected-access

    path_entries = gui_entry.os.environ["PATH"].split(gui_entry.os.pathsep)
    assert path_entries[:3] == ["/opt/homebrew/bin", "/usr/local/bin", "/opt/local/bin"]
    assert path_entries[-2:] == ["/custom/bin", "/usr/bin"]


def test_runtime_consumers_use_canonical_identity() -> None:
    """Runtime-generated names and ownership markers use canonical values."""

    basename = automatic_output_basename(datetime(2026, 8, 24, 12, 30, 0).astimezone())
    assert basename.startswith(f"{IDENTITY.output_prefix}video-")
    workspace = OwnedWorkspace(Path("/tmp/root"), Path("/tmp/root/job"), "id")
    assert workspace.marker_path.name == IDENTITY.workspace_marker


def test_v1_import_namespace_is_not_used_by_runtime_or_tests() -> None:
    """The old Python import namespace is not an accidental compatibility API."""

    repository_root = Path(__file__).parents[1]
    searched_roots = (repository_root / "src", repository_root / "tests")
    old_import_import = "from " + "ai_video_tools"
    old_import_import_alt = "import " + "ai_video_tools"
    for root in searched_roots:
        for path in root.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            assert old_import_import not in source
            assert old_import_import_alt not in source
