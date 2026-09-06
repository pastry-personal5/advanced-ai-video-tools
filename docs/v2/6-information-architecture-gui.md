# V2 Phase 6 — Queue Information Architecture

## Status

- State: Complete
- Predecessor: Phase 5

## Outcome

- Replaced the visible flat queue with Active, Up Next, and History regions
  derived from the same immutable `JobListModel`; no second queue or lifecycle
  owner was introduced.
- Kept Active/Up Next on the left, scrollable History on the right, selected-job
  details inline, the far-right Queue Preview, and bottom message area.
- Colocated active cancellation, pending reorder/removal, and terminal history
  removal while preserving backend state guards.
- Kept status textual, action/status columns fixed, Job Name flexible/elided,
  selection mapped to the canonical model, and cross-region keyboard navigation
  selection-only for Enter/Space.

## Evidence

- Final `make check`: 261 passed, two native-only checks skipped.
- Populated Queue Monitoring native capture/layout acceptance: 2 passed,
  1 deselected on the supported interactive macOS desktop.
