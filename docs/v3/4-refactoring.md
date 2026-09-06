# V3 Phase 4 — Modularity Refactoring

## Status

- State: Complete
- Completed: 2026-09-06
- Predecessor: Phase 3
- Successor: [Phase 5 — Unified Settings Dialog](5-settings-dialog.md)

## Outcome

Verified ownership and dependency direction without changing behavior. Core,
services, video, storage, system, and upscaling policy remain independent of Qt
widgets; GUI modules own presentation and Qt lifecycles.

| Boundary | Result |
| --- | --- |
| `core`, `services`, `video`, `system`, `upscaling` | No Qt dependency |
| `storage`, `cli.py` | Function-local lazy Qt imports only |
| `gui` | Qt presentation dependency expected |

No concrete cycle or mixed-policy defect justified a speculative abstraction or
broad rewrite. Existing typed stage contracts, worker ownership, media outputs,
queue behavior, settings persistence, and safety rules were preserved.

## Evidence

- Dependency audit and source inspection completed.
- Test suite: 281 passed, 3 opt-in native checks skipped.
