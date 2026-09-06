# V3 Phase 2 — Clip File Deletion Rules

## Status

- State: Complete
- Completed: 2026-09-03
- Predecessor: Phase 1
- Successor: Phase 3

## Outcome

Added GUI-only, ordered rules that can move related files to Trash after a
source clip itself moves successfully. Settings schema 2 stores nullable rules:
`None` selects built-in defaults, while an empty tuple disables all rules.

- `DeletionRule` matches case-insensitive immediate-directory basenames.
- The first enabled matching source rule wins. Targets support safe one-pass
  `{source_stem}`, `{source_name}`, and `{source_suffix}` substitution plus glob
  syntax; unknown placeholders and path traversal are rejected.
- Only immediate sibling regular files are eligible. Duplicates are suppressed;
  each target failure is reported without rolling back the source move.
- The default `*.mov → {source_stem}-last-frame.png` rule is enabled and can be
  edited, disabled, deleted, reordered, or restored.
- Schema-1 documents migrate on the next save. Malformed individual rules are
  skipped with warnings; malformed documents and newer-schema handling retain
  the existing safe persistence contract.
- Saving rules reconfigures the current editor for future Trash actions; queued
  requests and CLI behavior are unaffected.

## Evidence and limitations

- Focused settings, matching, Trash, and GUI coverage passed.
- Final `make check`: 281 passed, 3 opt-in native checks skipped.
- Directory/workspace rules, confirmation previews, output-file cleanup, and
  additional built-in source extensions remain deferred.
