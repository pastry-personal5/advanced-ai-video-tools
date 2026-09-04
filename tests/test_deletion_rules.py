"""Focused coverage for GUI related-file Trash rules."""

import os
from pathlib import Path

import yaml

from advanced_ai_video_tools.gui.source_clip_actions import SourceClipTrashService
from advanced_ai_video_tools.system.settings import DeletionRule, SettingsStore


def test_default_rule_deletes_only_the_source_specific_last_frame(tmp_path: Path) -> None:
    """The built-in rule cannot remove an unrelated sibling last-frame file."""
    source = tmp_path / "foo-bar.MOV"
    first = tmp_path / "foo-bar-last-frame.PNG"
    second = tmp_path / "bar-bar-last-frame.png"
    source.touch()
    first.touch()
    second.touch()
    calls: list[Path] = []

    result = SourceClipTrashService(lambda value: calls.append(Path(value)) or True).move_to_trash(source)

    assert result.related_deleted == (first,)
    assert calls == [source, first]


def test_custom_target_globs_remain_independent_when_no_source_placeholder(tmp_path: Path) -> None:
    """Advanced explicit globs retain their original same-directory behavior."""

    source = tmp_path / "foo-bar.mov"
    first = tmp_path / "foo-bar-last-frame.png"
    second = tmp_path / "bar-bar-last-frame.png"
    source.touch()
    first.touch()
    second.touch()
    calls: list[Path] = []
    rule = DeletionRule("*.mov", ("*-last-frame.png",))

    result = SourceClipTrashService(lambda value: calls.append(Path(value)) or True, deletion_rules=(rule,)).move_to_trash(source)

    assert result.related_deleted == (second, first)
    assert calls == [source, second, first]


def test_source_placeholder_expansion_treats_glob_characters_literally() -> None:
    """A source basename cannot turn a safe placeholder into a broader glob."""

    rule = DeletionRule("*.mov", ("{source_stem}-last-frame.png",))

    assert rule.matches_target("foo[1]?.mov", "foo[1]?-last-frame.png")
    assert not rule.matches_target("foo[1]?.mov", "foo1x-last-frame.png")


def test_custom_source_placeholders_expand_once_and_preserve_remaining_globs() -> None:
    """Custom rules combine literal source fields with ordinary target globs."""

    rule = DeletionRule("render-*.mkv", ("{source_stem}-preview-?{source_suffix}", "{source_name}.json"))

    assert rule.matches_source("render-foo.mkv")
    assert rule.matches_target("render-foo.mkv", "render-foo-preview-a.mkv")
    assert rule.matches_target("render-foo.mkv", "render-foo.mkv.json")
    assert not rule.matches_target("render-foo.mkv", "other-preview-a.mkv")
    assert DeletionRule("*.mov", ("{source_stem}-last.png",)).matches_target("foo{source_suffix}.mov", "foo{source_suffix}-last.png")


def test_unknown_source_placeholder_is_rejected() -> None:
    """A typo cannot silently create a rule that never matches."""

    try:
        DeletionRule("*.mov", ("{source_title}-last-frame.png",))
    except ValueError as error:
        assert str(error) == "target pattern contains an unsupported source placeholder"
    else:
        raise AssertionError("unknown source placeholder was accepted")


def test_empty_rules_disable_related_cleanup_and_source_failure_short_circuits(tmp_path: Path) -> None:
    """An explicit empty rule set disables cleanup and source failure stops it."""
    source = tmp_path / "clip.mov"
    related = tmp_path / "clip-last-frame.png"
    source.touch()
    related.touch()
    calls: list[Path] = []

    disabled = SourceClipTrashService(lambda value: calls.append(Path(value)) or True, deletion_rules=()).move_to_trash(source)
    assert not disabled.related_deleted
    assert calls == [source]

    calls.clear()
    failed = SourceClipTrashService(lambda value: calls.append(Path(value)) or False).move_to_trash(source)
    assert not failed.moved
    assert calls == [source]


def test_first_enabled_source_rule_wins_and_disabled_rules_are_skipped(tmp_path: Path) -> None:
    """Only the first enabled source match controls sibling selection."""

    source = tmp_path / "clip.mov"
    first = tmp_path / "clip-first.png"
    second = tmp_path / "clip-second.png"
    source.touch()
    first.touch()
    second.touch()
    calls: list[Path] = []
    rules = (
        DeletionRule("*.mov", ("{source_stem}-second.png",), enabled=False),
        DeletionRule("*.mov", ("{source_stem}-first.png",)),
        DeletionRule("*.mov", ("{source_stem}-second.png",)),
    )

    result = SourceClipTrashService(lambda value: calls.append(Path(value)) or True, deletion_rules=rules).move_to_trash(source)

    assert result.related_deleted == (first,)
    assert calls == [source, first]


def test_target_failure_continues_in_deterministic_order_and_reports_each_result(tmp_path: Path) -> None:
    """One related Trash failure does not prevent later sibling cleanup."""

    source = tmp_path / "clip.mov"
    failed_target = tmp_path / "clip-a.png"
    moved_target = tmp_path / "clip-b.png"
    source.touch()
    failed_target.touch()
    moved_target.touch()
    calls: list[Path] = []
    messages: list[str] = []

    def mover(value: str) -> bool:
        path = Path(value)
        calls.append(path)
        return path != failed_target

    rule = DeletionRule("*.mov", ("{source_stem}-*.png",))
    result = SourceClipTrashService(mover, deletion_rules=(rule,), message_callback=messages.append).move_to_trash(source)

    assert result.related_deleted == (moved_target,)
    assert result.related_failed == (failed_target,)
    assert calls == [source, failed_target, moved_target]
    assert messages == ["Could not move related file to Trash: clip-a.png: Trash provider rejected the request", "Also moved related file to Trash: clip-b.png"]


def test_only_immediate_regular_nonlink_siblings_are_eligible(tmp_path: Path) -> None:
    """Directories, symlinks, and files outside the source directory stay untouched."""

    source = tmp_path / "clip.mov"
    regular = tmp_path / "clip-last.png"
    directory = tmp_path / "clip-directory.png"
    linked_target = tmp_path / "clip-linked.png"
    outside = tmp_path / "outside" / "clip-outside.png"
    source.touch()
    regular.touch()
    directory.mkdir()
    outside.parent.mkdir()
    outside.touch()
    os.symlink(regular, linked_target)
    calls: list[Path] = []
    rule = DeletionRule("*.mov", ("{source_stem}-*.png",))

    result = SourceClipTrashService(lambda value: calls.append(Path(value)) or True, deletion_rules=(rule,)).move_to_trash(source)

    assert result.related_deleted == (regular,)
    assert calls == [source, regular]
    assert directory.exists() and linked_target.is_symlink() and outside.exists()


def test_invalid_persisted_rule_is_skipped_and_schema_migrates_on_save(tmp_path: Path) -> None:
    """One invalid rule does not discard valid settings and save upgrades schema."""
    path = tmp_path / "settings.yaml"
    path.write_text(yaml.safe_dump({"schema_version": 1, "deletion_rules": [{"source_pattern": "*.mov", "target_patterns": ["ok-*"], "enabled": True}, {"source_pattern": "../*", "target_patterns": ["bad"]}]}), encoding="utf-8")

    store = SettingsStore(path)
    report = store.load_report()

    assert report.settings.deletion_rules == (DeletionRule("*.mov", ("ok-*",)),)
    assert len(report.warnings) == 1
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["schema_version"] == 1
    store.save(report.settings)
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["schema_version"] == 2


def test_legacy_broad_default_is_migrated_to_the_source_specific_default(tmp_path: Path) -> None:
    """Existing Phase 2 defaults become safe before the next settings save."""

    path = tmp_path / "settings.yaml"
    path.write_text(yaml.safe_dump({"schema_version": 2, "deletion_rules": [{"source_pattern": "*.mov", "target_patterns": ["*-last-frame.png"], "enabled": True}]}), encoding="utf-8")

    report = SettingsStore(path).load_report()

    assert report.settings.deletion_rules == (DeletionRule("*.mov", ("{source_stem}-last-frame.png",)),)
    assert report.warnings == ("Updated the legacy broad last-frame rule to the source-specific default.",)


def test_malformed_rule_collection_does_not_quarantine_other_preferences(tmp_path: Path) -> None:
    """A bad rules collection remains a warning, not a settings-file failure."""

    path = tmp_path / "settings.yaml"
    path.write_text(yaml.safe_dump({"schema_version": 2, "processing": {"target_height": 1080}, "deletion_rules": "not-a-list"}), encoding="utf-8")

    report = SettingsStore(path).load_report()

    assert report.settings.target_height == 1080
    assert report.settings.deletion_rules == ()
    assert report.warnings == ("Skipped deletion rules because the saved value is not a list.",)
    assert path.exists()
    assert not list(tmp_path.glob("settings.corrupt-*.yaml"))


def test_finder_alias_is_skipped_even_when_it_matches_a_target(tmp_path: Path, monkeypatch) -> None:
    """Finder aliases are not eligible related regular files on macOS."""

    source = tmp_path / "clip.mov"
    alias = tmp_path / "clip-last-frame.png"
    source.touch()
    alias.touch()
    calls: list[Path] = []

    class AliasInfo:
        """Minimal native-file metadata fake reporting a Finder alias."""

        @staticmethod
        def isAlias() -> bool:  # pylint: disable=invalid-name
            """Report this test fixture as a Finder alias."""

            return True

    monkeypatch.setattr("advanced_ai_video_tools.gui.source_clip_actions.QFileInfo", lambda _path: AliasInfo())

    result = SourceClipTrashService(lambda value: calls.append(Path(value)) or True).move_to_trash(source)

    assert not result.related_deleted
    assert calls == [source]
