# Phase 1 Presentation Architecture

## Status

- Phase: 1 — Enhance GUI
- Specification state: Complete
- Implementation state: In progress
- Date: 2026-08-22

This document defines the presentation-layer boundaries for the approved Phase 1
GUI. It is a planning specification, not evidence that the redesigned widgets
or view-models already exist.

## Responsibilities and boundaries

```text
Backend services / queue
        │ immutable snapshots and typed events
        ▼
Qt event bridge → presentation state/model → declarative widgets
        ▲                                         │ user intents
        └──────────── typed controller signals ────┘
```

- Widgets collect intent, render state, and emit typed user actions. They do not
  probe media, build FFmpeg commands, launch tools, or mutate queued requests.
- `JobSubmissionController`, `GuiPreflightController`, and the queue remain the
  owners of asynchronous work and safety gates.
- Queue snapshots are immutable facts. Presentation state may select and filter
  them, but may not rewrite them.
- The preview is a convenience presentation boundary. It consumes the selected
  local source path and never contributes to authoritative preflight or plans.

## Durable and ephemeral state

The redesigned window should separate a typed presentation state from widget
construction. The planned state is session-scoped unless explicitly marked as a
preference:

| State | Owner | Persistence |
| --- | --- | --- |
| Active view (`Job Creation` or `Queue Monitoring`) | Main-window presentation state | Session only |
| Selected source row and preview playback state | Job-editor/preview state | Session only |
| Selected job ID and selected message tab | Queue/message presentation state | Session only |
| Five-line global/job message tails | Message presentation state | Session only |
| Message-area height and splitter positions | Main-window presentation state | Session only unless later approved |
| Mute and volume | Typed application preferences | Persist as non-safety settings |
| Tool overrides, recent directories, target height, overwrite mode | `ApplicationSettings` / `SettingsStore` | Existing typed atomic persistence |
| Job request, queue state, progress, outcomes | Core models / `JobQueue` | Queue ownership; never UI-owned |

Queued requests retain frozen settings and tool overrides. Changing the view,
selection, message tab, or preview cannot mutate a queued or running request.

## Presentation state shape

The implementation should use typed enums/dataclasses (or an equivalent typed
Qt model) rather than widget inspection or unstructured dictionaries:

- `MainView`: `JOB_CREATION`, `QUEUE_MONITORING`.
- `MessageTab`: `GLOBAL_MESSAGES`, `JOB_MESSAGES`.
- `PreviewState`: `NO_SOURCE`, `LOADING`, `PLAYING`, `PAUSED`, `UNAVAILABLE`.
- `selected_source_index: int | None` and `selected_job_id: str | None`.
- `message_tails: global_tail` plus job-keyed tails, each bounded to five lines.
- `message_area_height` and the approved preview/layout metrics.

Widget construction reads this state and binds signals; it does not become the
state store. Selection changes update only the relevant state field and emit a
typed event for the preview or queue presenter.

## Identity, metrics, and semantics

Centralize brand and UI constants in planned presentation resources before the
later rename. The implementation may use separate typed sources for:

- Temporary display identity: `Advanced AI Video Tools`.
- Brand-neutral labels and menu names: `Job Creation`, `Queue Monitoring`,
  `Global Messages`, `Job Messages`, and `Preferences`.
- Typography roles, the 8 px spacing grid, comfortable 32 px controls/rows,
  and 32 × 32 px icon hit areas defined in the visual specification.
- Icon semantics: the approved navigation, preview, and terminal-job removal
  glyphs, each with an accessible action name.
- Status semantics: textual job states and stage/progress text; no severity
  filtering or color-only meaning.

Identity constants must remain independent from media-policy constants so Phase 2
can rename the product without changing processing behavior.

## Qt ownership and thread rules

- `QApplication` owns the main window lifetime. `GuiRuntime` continues to own
  settings, preview, tool validation, queue, model, and submission services.
- The GUI entry point acquires one process-wide Qt lock; a second application
  launch exits before runtime/window creation.
- The Qt model is mutated only on the GUI thread. Cross-thread queue callbacks
  use the existing queued signal bridge.
- Preflight and tool validation remain worker-thread operations; their results
  return through queued signals before any widget mutation.
- Preview loading and media-player signals are presentation events only. They
  must not call backend probing or command builders synchronously.
- Every worker has an explicit owner, a bounded shutdown path, and no widget
  reference that outlives the window.
- Shutdown order remains: stop preview/validation workers, request queue
  shutdown, join owned workers, then release the window and application objects.
- View switching only changes visibility and presentation selection. It never
  starts a second processing job or bypasses FIFO ownership.

## State-to-view binding

| Presentation state | Visible surface | Hidden surface |
| --- | --- | --- |
| `JOB_CREATION` | Editor, ordered filenames, selected-source preview, preview controls | Queue table and queue-only actions |
| `QUEUE_MONITORING` | Queue table, progress, selected-job details, reorder/cancel/remove actions | Editor-only controls and source preview |
| Any active view | Bottom `QTabWidget`, selected message tab, five-line read-only tail | Nothing in the message area |
| No selected job | `Job Messages` tab with `No job is selected.` | Stale job details |

The active view button remains visibly selected. Hidden widgets are removed from
the active tab order rather than merely disabled.

## Architecture checklist completion

This specification completes the Presentation architecture planning tasks:

- Durable presentation state is separated conceptually from declarative widget
  construction.
- Identity, metrics, icon, and status semantics are centralized and rename-ready.
- Qt ownership, queued signal delivery, worker boundaries, and shutdown are
  explicit.

Exact splitter proportions and internal spacing remain the only open visual
implementation details recorded by Phase 1.
