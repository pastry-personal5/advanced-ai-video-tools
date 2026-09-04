# Phase 2: Clip File Deletion Rules

## Status

- Phase: 2
- State: Complete
- Target: v3
- Depends on: Phase 1 (Refactoring) — Complete

## Objective

When a user moves a source clip to the OS trash from the GUI editor, automatically move
related files (configured by the user) to the trash as well. The first rule to implement
is: deleting `video-20260902-190157-1788343317349979302.mov` also deletes
`video-20260902-190157-1788343317349979302-last-frame.png` in the same directory.

## Summary

This phase adds a configurable deletion-rule system to the existing `SourceClipTrashService`.
When a source file is successfully moved to trash, the service consults user-defined rules
to find and move related files (e.g., `-last-frame.png` files) from the same directory.
Rules are stored in `ApplicationSettings` under a new schema version. A built-in default
rule for `-last-frame.png` ships enabled by default but can be disabled. Failed deletions
of related files are logged in the Global Messages tab without aborting the source file's
trash operation.

## Key Design Decisions

### From initial interview

| Decision | Choice | Rationale |
| --- | --- | --- |
| Config location | In `ApplicationSettings` | Consistent with existing settings architecture; schema version increment required. |
| Rule format | Explicit rule list with full glob patterns | Flexible enough for future rules (e.g., preview thumbnails, sidecar files) while remaining explicit and validateable. |
| Trigger scope | Source clip trash only | Narrowest scope; only when a user moves a source clip from the editor to trash. |
| User feedback | Message in Global Messages tab | Visible but non-blocking; does not interrupt the user workflow. |
| Schema version | Increment from 1 to 2 | Old settings files without the new key use the built-in default rule. |
| Error handling | Log and continue | Partial deletion is acceptable; don't roll back the source file's trash. |

### From follow-up interview

| Decision | Choice | Rationale |
| --- | --- | --- |
| Glob semantics | `fnmatch` on basename | Simple, predictable, no path traversal. Matches on the filename only, not the full path. |
| Built-in defaults | Built-in default rule, enabled by default | Ships with a pre-configured rule for `-last-frame.png` that users can disable. Low friction for the stated use case. |
| CLI support | GUI only | Deletion rules are a GUI-only feature. CLI users handle cleanup manually. |
| Result detail | Detailed list in `TrashMoveResult` | Add a list of successfully/failed related file paths. More data but useful for debugging and logging. |

## Important Changes or Additions

### 1. New settings schema key

`ApplicationSettings` gains a new field:

```python
@dataclass(frozen=True)
class ApplicationSettings:
    # ... existing fields ...
    deletion_rules: tuple[DeletionRule, ...] | None = None
```

- `SETTINGS_SCHEMA_VERSION` increments from `1` to `2`.
- `_decode_document` gains a `deletion_rules` key that reads a list of rule objects.
- Missing rules mean `None` and select the built-in default. An explicit empty
  list disables all rules. Malformed individual rules are skipped with a concise
  settings-load warning while valid rules remain active.

### 2. New data model: `DeletionRule`

```python
@dataclass(frozen=True)
class DeletionRule:
    """One deletion rule: a source pattern and target patterns."""
    source_pattern: str  # fnmatch glob matching source basenames (e.g., "*.mov")
    target_patterns: tuple[str, ...]  # fnmatch globs and source placeholders for related basenames
    enabled: bool = True  # Whether this rule is active
```

- `source_pattern` is a `fnmatch`-style glob matching the **basename** of source files.
- `target_patterns` are `fnmatch`-style globs matching the **basename** of related files.
  They may include `{source_stem}`, `{source_name}`, or `{source_suffix}`. The
  placeholder value is treated literally before the remaining glob is matched.
  Patterns without a placeholder remain independent globs for advanced rules.
- `{source_stem}` is the source basename without its final suffix;
  `{source_name}` includes that suffix; and `{source_suffix}` includes its
  leading dot. Unknown placeholders are rejected in both persistence and the
  rule editor so a typo cannot silently broaden or disable cleanup.
- Placeholder expansion is one-pass and escapes glob metacharacters from the
  actual source filename. Custom rules may therefore safely combine a source
  placeholder with `?` or character-class target glob syntax.
- `enabled` allows users to disable individual rules without deleting them.
- Rules are evaluated in order; only enabled rules are considered.

### 3. Built-in default rule

The application ships with one built-in rule:

```python
DEFAULT_DELETION_RULES: tuple[DeletionRule, ...] = (
    DeletionRule(
        source_pattern="*.mov",
        target_patterns=("{source_stem}-last-frame.png",),
        enabled=True,
    ),
)
```

- This rule matches any `.mov` file and maps its stem to the corresponding
  `-last-frame.png` in the same directory. For example, deleting `foo-bar.mov`
  can move `foo-bar-last-frame.png`, but not `bar-bar-last-frame.png`.
- A custom example, `source_pattern="render-*.mkv"` with
  `target_patterns=("{source_stem}-preview-?{source_suffix}",)`, matches
  `render-foo-preview-a.mkv` for source `render-foo.mkv`.
- Users can disable this rule by setting `enabled=False` in their settings file.
- Future built-in rules can be added (e.g., for `.mp4` → `-last-frame.png`, or
  preview thumbnails) without changing the schema.

### 4. Extension to `SourceClipTrashService`

The service gains a new method and a constructor parameter:

```python
class SourceClipTrashService:
    def __init__(
        self,
        mover: Callable[[str], bool] | None = None,
        deletion_rules: tuple[DeletionRule, ...] | None = None,
    ) -> None:
        self._deletion_rules = deletion_rules

    def move_to_trash(self, path: Path, queued_inputs: Iterable[Path] = ()) -> TrashMoveResult:
        # ... existing logic ...
        if moved:
            related_result = self._move_related_to_trash(path)
            result = TrashMoveResult(
                moved=result.moved,
                message=result.message,
                related_deleted=related_result.successful,
                related_failed=related_result.failed,
            )
        return result
```

- After the source file is successfully moved, `_move_related_to_trash(path)` is called.
- It iterates over all rules (including built-in defaults), checks if the source basename
  matches any enabled rule's `source_pattern`, and for the first match, collects files
  in the **same directory** matching any `target_pattern`.
- Each matching file is moved to trash via `QFile.moveToTrash()`.
- Failures are logged to the Global Messages tab (via a new callback or signal) and
  silently ignored for the purpose of the source file's result.

### 5. Updated `TrashMoveResult`

```python
@dataclass(frozen=True)
class TrashMoveResult:
    moved: bool
    message: str
    related_deleted: tuple[Path, ...] = ()
    related_failed: tuple[Path, ...] = ()
```

- `related_deleted`: list of related files successfully moved to trash.
- `related_failed`: list of related files that could not be moved (e.g., not found,
  permission denied).

### 6. `JobEditor` wiring

`JobEditor` passes `deletion_rules` from `ApplicationSettings` to `SourceClipTrashService`:

```python
self._trash_service = SourceClipTrashService(
    deletion_rules=settings.deletion_rules,
)
```

### 7. Global Messages integration

A new signal or callback on `SourceClipTrashService` (or a thin adapter) emits
deletion messages:

```
"Also moved video-xxx-last-frame.png to Trash."
"Failed to move video-xxx-thumbnail.jpg to Trash: file not found."
```

These are emitted to the existing `message` signal (or a dedicated
`deletion_message` signal) which the `JobEditor` routes to the Global Messages tab.

## Implementation Changes

### Files to modify

1. **`src/advanced_ai_video_tools/system/settings.py`**
   - Increment `SETTINGS_SCHEMA_VERSION` to `2`.
   - Add `deletion_rules: tuple[DeletionRule, ...] | None = None` to `ApplicationSettings`.
   - Add validation in `__post_init__` (each rule is a `DeletionRule` instance).
   - Update `_encode_document` and `_decode_document` to handle the new key.

2. **`src/advanced_ai_video_tools/system/settings.py`**
   - Add `DeletionRule` dataclass (frozen, with `source_pattern: str`,
     `target_patterns: tuple[str, ...]`, and `enabled: bool = True`).

3. **`src/advanced_ai_video_tools/gui/source_clip_actions.py`**
   - Add `deletion_rules` parameter to `SourceClipTrashService.__init__`.
   - Add `_move_related_to_trash(self, source_path: Path)` method.
   - Call `_move_related_to_trash` after successful source file move.
   - Add a `deletion_message` signal (or callback) for emitting deletion results.
   - Update `TrashMoveResult` to include `related_deleted` and `related_failed`.

4. **`src/advanced_ai_video_tools/gui/editor.py`**
   - Pass `settings.deletion_rules` to `SourceClipTrashService` constructor.
   - Wire `deletion_message` signal to the Global Messages tab (or existing `message` signal).

### Files to add

None required. All changes fit within existing modules.

## Test Plan

### Unit tests (in `tests/test_gui_submission.py` or new `tests/test_deletion_rules.py`)

1. **No rules configured** — moving a source file to trash succeeds; no related files
   are touched.

2. **Single rule matches** — a rule with `source_pattern="*.mov"` and
   `target_patterns=("{source_stem}-last-frame.png",)` correctly finds and moves
   `video-xxx-last-frame.png` when `video-xxx.mov` is trashed.

3. **Rule does not match** — a source file whose basename does not match any
   `source_pattern` is trashed; no related files are touched.

4. **Multiple matching targets** — a rule with multiple `target_patterns` collects
   all matching files in the same directory.

5. **Related file not found** — a target file referenced by a rule does not exist;
   the failure is logged but does not abort the source file's trash.

6. **Related file is a directory** — directories are skipped (not moved to trash).

7. **Related file is in a different directory** — files outside the source file's
   directory are not touched.

8. **Multiple rules, first match wins** — when multiple rules match, only the first
   rule's targets are collected.

9. **Source file is queued** — the existing guard (source already in active queue
   intent) blocks trash; no related-file deletion is attempted.

10. **Settings schema migration** — a v1 settings file (no `deletion_rules` key)
    loads successfully with `deletion_rules = None` and migrates on save.

11. **Invalid rule in settings** — a malformed rule (missing fields, invalid glob)
    is skipped with a concise warning; the rest of the rules are applied.

12. **Built-in default rule is active** — the shipped `-last-frame.png` rule is
    applied by default when no user rules are configured.

13. **Built-in default rule can be disabled** — a user can set `enabled=False` on
    the built-in rule, and it is not applied.

14. **TrashMoveResult includes related file lists** — successful and failed related
    file paths are included in the result.

### Integration / GUI tests

15. **Deletion messages appear in Global Messages tab** — moving a source file with
    matching related files produces visible messages in the Global Messages tab.

16. **Deletion messages do not appear when no rules match** — moving a source file
    with no matching related files produces no deletion messages.

## Assumptions

- The `-last-frame.png` files are user-generated (not produced by the pipeline) and
  reside in the same directory as their corresponding source video files.
- Users manage FFmpeg, FFprobe, Real-ESRGAN, Vulkan, and model files; similarly,
  users manage these related files. The app only assists with cleanup.
- `QFile.moveToTrash()` is the same OS-level operation used for source files; no
  cross-platform trash handling is needed (macOS only).
- The existing `SourceClipTrashService._mover` (defaulting to `QFile.moveToTrash`)
  is reused for related files.
- Rules are evaluated per-source-file; there is no batch or cross-file analysis.
- The first matching rule wins; if no rule matches, no related files are touched.
- A rule's `source_pattern` and `target_patterns` use `fnmatch` semantics on the
  **basename** (not the full path).
- The built-in default rule is shipped with `enabled=True` and can be disabled by
  setting `enabled=False` in the user's settings file.
- CLI does not support deletion rules (GUI only).

## Completion evidence

- [x] GUI-only source Trash rules are persisted atomically in schema 2, including
  migration, malformed-rule diagnostics, explicit disablement, and legacy-default
  correction.
- [x] Immediate same-directory regular-file-only cleanup honors source-aware
  templates, ordering, first-enabled-rule selection, duplicate suppression,
  independent advanced globs, per-target continuation, and result ordering.
- [x] Preferences provide ordered add/edit/delete, enablement, reordering,
  restore-defaults, live validation, source/related sample preview, cancellation,
  and atomic save for future Trash actions.
- [x] Global Messages receive one related-file success or failure event, and saved
  settings reconfigure the existing editor without restart.
- [x] Focused settings and GUI tests passed, followed by `make check` with 281
  passed tests and three opt-in native acceptance checks skipped.

## Deferred follow-ons

- Directory/workspace matching.
- Per-source disabling or confirmation previews.
- Output-file deletion rules.
- Built-in defaults for source extensions other than `.mov`.
