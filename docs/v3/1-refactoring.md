# V3 Phase 1 — Refactoring

## Status

- State: Complete
- Completed: 2026-09-03
- Predecessor: v2 release
- Successor: Phase 2

## Outcome

Made application APIs descriptive and established typed service/worker
boundaries without changing CLI, GUI, media, queue, persistence, or output
behavior.

| Area | Approved form | Examples |
| --- | --- | --- |
| Pipeline/stage operations | `execute_<noun>` | `execute_pipeline`, `execute_preflight`, `execute_extraction` |
| Commands/plans/requests | `create_<noun>` | `create_concat_command`, `create_upscale_plan`, `create_job_request` |
| GUI lifecycle actions | `begin_<noun>` | `begin_preview`, `begin_validation`, `begin_submission` |

The breaking migration replaced generic pipeline/preflight `run`, stage
`execute`, command/plan `build_*`, and GUI controller `start` entry points with
the vocabulary above. All repository callers moved together and no deprecated
aliases remain; framework `run`/`start` APIs were intentionally retained.

Additional completed boundaries:

- `ProgressEmitter` is the production constructor for immutable progress.
- `services.contracts` owns typed stage protocols and `StageContext` carries
  shared workspace, cancellation, progress, and toolchain dependencies.
- `gui.worker_lifecycle` owns one-shot Qt worker completion and shutdown rules.
- Operational failures retain causes and bounded diagnostics; pipeline order,
  cancellation, cleanup, and publication remain unchanged.

## Evidence

- Focused service/frontend tests: 172 passed; FFmpeg integration: 6 passed.
- Final `make check`: 265 passed, 3 opt-in native checks skipped.
- The owner waived native presentation checks because this phase changed no
  presentation, platform, or subprocess behavior.
