# Phase 4 — Refactoring

## Status

Complete. Phase 4 was approved after Phase 3 stabilization and proceeded from
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

### Media preparation boundary — completed

- Extracted sequential normalization execution from the preparation
  orchestrator while preserving concat-first ordering, cancellation, progress,
  diagnostics, and workspace ownership.
- Focused validation: `tests/test_media_preparation.py` — 8 passed.

### Pipeline workspace boundary — completed

- Extracted validated workspace creation from the full-job orchestration path
  while preserving lifecycle transitions, typed failures, and ownership.
- Focused validation: `tests/test_pipeline.py` — 9 passed.

### Queue worker boundaries — completed

- Extracted pending-job activation and runner-outcome translation from the
  single-worker loop while preserving FIFO order, callback isolation, terminal
  outcomes, cancellation, and destination claims.
- Focused validation: `tests/test_queue.py` — 8 passed.

### GUI snapshot boundaries — completed

- Extracted insertion and refresh operations from the Qt queue snapshot bridge,
  preserving Qt-thread mutation, revision filtering, model ordering, and
  notifications.
- Focused validation: GUI tests — 42 passed.

### Top-down GUI presentation naming and selection boundaries — completed

- Split `MainWindow` selected-job rendering into explicit empty-state,
  progress-rendering, and selected-row presentation helpers.
- Renamed GUI private handlers to domain actions such as
  `_handle_queue_snapshot`, `_refresh_selected_job`, `_open_preferences`, and
  `_append_job_message`.
- Renamed GUI attributes and Qt object names to consistent queue, selected-job,
  source, message, and preferences terminology; updated theme/test consumers
  where applicable.
- Preserved Qt thread affinity, signal wiring, selection behavior, progress
  calculations, accessibility labels, and user-visible text.
- Focused validation: GUI tests — 42 passed.

## Completion validation

- Full quality gate: `make check` — 234 passed, 2 native-only tests skipped.
- Black, Pylint, pycodestyle, and `git diff --check` passed.
- No product features, media-policy changes, public CLI changes, or
  compatibility removals were introduced.

## Remaining work

- Phase 5 GUI Enhancement Including Fullscreen Preview is complete; Phase 7
  remains provisional and requires separate approval before release
  stabilization or artifact work begins.
