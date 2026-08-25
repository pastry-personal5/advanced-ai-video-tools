# Phase 4 — Refactoring

## Status

In progress. Phase 4 is approved after Phase 3 stabilization and proceeds from
the bottom layer upward. This phase is refactoring-only: approved behavior,
media contracts, public CLI behavior, compatibility aliases, and safety
invariants must remain unchanged.

## Approved scope

- Refactor foundational/core code first, followed by application services,
  queue and pipeline orchestration, and finally GUI presentation.
- Internal API renames are allowed when public and documented compatibility is
  preserved.
- No numeric complexity budgets apply; each slice must be small, typed,
  reviewable, and covered by focused regression tests.
- Do not add product features or change approved behavior.

## Implementation evidence

### Subprocess lifecycle boundary — completed

- Extracted request validation and process-completion polling from
  `SubprocessRunner.run` into private helpers.
- Kept shell-free argument-array execution, cancellation, timeout handling,
  bounded diagnostics, process-group cleanup, and typed exceptions unchanged.
- Added regression coverage for invalid requests before process launch.
- Focused validation: `tests/test_processes.py` — 7 passed.
- Full validation: `make check` — 234 passed, 2 native-only tests skipped;
  Black, Pylint, and pycodestyle passed.

### Settings persistence boundary — completed

- Extracted current YAML loading and atomic document writing from
  `SettingsStore.load` and `SettingsStore.save` into focused private helpers.
- Kept v1-settings cleanup, legacy JSON migration, schema validation,
  corruption quarantine, symlink refusal, private permissions, and atomic
  replacement behavior unchanged.
- Focused validation: `tests/test_settings.py` — 17 passed.
- Full validation: `make check` — 234 passed, 2 native-only tests skipped;
  Black, Pylint, and pycodestyle passed.

## Remaining work

- Continue with small application-service refactorings from the bottom layer
  upward while preserving the Phase 3 stabilization evidence.
- Re-run the full quality gate after each refactoring slice.
- Mark the phase complete only after the approved refactoring scope has been
  addressed and final documentation review is complete.
