# V2 Phase 1 — Enhance GUI

## Status

- State: Complete
- Completed: 2026-08-25
- Historical specifications: [interaction audit](1-enhance-gui-audit.md) and
  [presentation architecture](1-enhance-gui-presentation-architecture.md)

## Outcome

- Added a dark 1400 × 880 two-workspace shell with Job Creation, Queue
  Monitoring, persistent session messages, and explicit navigation.
- Added local selected-source playback through `QMediaPlayer`/`QVideoWidget`.
  Preview remains playback-only, never supplies processing intent, and has no
  proxy or remote fallback.
- Added ordered filename-only source rows, file drop, reorder/remove/filesystem
  actions, queue-aware safe Trash handling, target height, output selection,
  native audio controls, and persisted non-safety preview preferences.
- Added typed GUI-thread message/history delivery, clear progress/status text,
  selected-job details, queue actions, accessibility names, and one GUI instance.
- Moved external tools out of the main surface into the then-current
  **Edit → Preferences** dialog.

## Evidence

- Focused GUI, accessibility, lifecycle, file-action, and persistence coverage
  passed throughout the phase; the final recorded full check passed 209 tests.
- Native launch and headless presentation checks passed. Complete native visual
  inspection was security-limited in the original environment and recorded as
  such rather than claimed.

Later v2 phases superseded the queue layout and fullscreen details while
preserving these ownership and safety boundaries.
