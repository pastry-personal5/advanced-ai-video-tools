# Phase 1 GUI Audit and Interaction Specification

## Status

- Phase: 1 — Enhance GUI
- Audit state: Complete
- Date: 2026-08-22
- Implementation state: Specification only; no redesign code is implied by this document

This document records the current v1 GUI audit, concrete usability findings,
approved Phase 1 interaction states, and measurable layout/accessibility
criteria. Product decisions remain governed by [Phase 1 — Enhance GUI](1-enhance-gui.md).

## Audit scope and evidence

The audit inspected the current Qt hierarchy, signal/slot connections, queue
model roles, asynchronous preflight path, settings dialog, and headless GUI
tests in:

- `src/ai_video_tools/gui/window.py`
- `src/ai_video_tools/gui/editor.py`
- `src/ai_video_tools/gui/jobs.py`
- `src/ai_video_tools/gui/submission.py`
- `src/ai_video_tools/gui/preflight.py`
- `src/ai_video_tools/gui/tool_settings.py`
- `src/ai_video_tools/gui/application.py`
- `tests/test_gui.py`
- `tests/test_gui_submission.py`
- `tests/test_gui_tool_settings.py`

## Current v1 hierarchy

The current `MainWindow` is a single vertical stack:

```text
QMainWindow
└── central QWidget / QVBoxLayout
    ├── External Tools… button row
    ├── JobEditor / “Create processing job” group
    │   ├── Ordered input QListWidget
    │   ├── Add, Remove, Move Up, Move Down
    │   ├── Output directory and target-height fields
    │   ├── Fixed model and automatic-name labels
    │   └── Inline status and Preflight & Queue
    ├── Processing jobs QListView
    ├── Selected-job status label
    ├── Output-path label
    ├── Progress bar
    ├── Move Up, Move Down, Cancel Job
    └── Diagnostics-path label
```

Preflight is a worker-thread operation followed by a modal `PreflightDialog`
with an issue list, optional dropped-stream acknowledgement, Queue Job, and
Cancel. External Tools is a separate dialog with asynchronous validation and
atomic settings persistence. Queue updates arrive through a queued Qt signal
and are rendered by `JobListModel`.

The current source has no explicit `setTabOrder` calls, so focus order follows
Qt construction order and must be made deliberate during implementation.

## Current workflows and findings

| Scenario | Current v1 path | Finding carried into Phase 1 |
| --- | --- | --- |
| First launch | Main window opens to the editor, queue, status, progress, and diagnostics in one stack. | Creation and monitoring compete for space; there is no clear mode boundary or persistent message surface. |
| Valid job | Add files, set output directory/height, choose Preflight & Queue, review, then queue. | There is no source preview, file-manager drop target, or clear selected-clip context. |
| Blocked preflight | Worker reports progress; modal review or critical message blocks submission. | Safety gating is correct, but ordinary validation and diagnostic feedback are mixed across labels, dialogs, and message boxes. |
| Dropped-stream acknowledgement | Review dialog exposes a checkbox before Queue Job becomes available. | The safety gate must remain modal and explicit while surrounding status becomes inline and log-like. |
| Queued job | Job appears in one-column `QListView`; selection updates status, output, progress, and queue movement controls. | Status and name are combined in one display string; there is no status column, removal action, selected-job message tab, or whole/stage progress presentation. |
| Active cancellation | Cancel Job delegates to the queue; the model later shows cancelling/cancelled. | Cancellation is available, but terminal-row cleanup and state-specific actions are not visible in the current list. |
| Failure/completion | Terminal state and error/message are rendered below the list. | Failure details are easy to miss; completion has no global message entry and there is no five-line message tail. |
| Tool misconfiguration | External Tools… opens a validation dialog; failed values are not saved. | The behavior is safe, but the action belongs in `Edit` → `Preferences` and should not consume main-window space. |

Additional findings:

- The current minimum window is 880 × 760, below the approved 1536 × 982 Phase 1 minimum.
- Source rows currently display full path text and support picker-based input only.
- There is no dark-theme implementation, navigation rail, source preview, queue table, integrated message widget, or file-manager drop handling.
- The current player/preview boundary does not exist; Phase 1 must keep preview behavior independent from authoritative preflight.
- The current shell exposes no explicit global-versus-job message ownership.

## Approved target shell

```text
┌ rail ┬──────────────────────────── active view ──────────────────────────────┐
│  +   │ Job Creation: editor and selected-source preview at the far right      │
│  ≣   │ or Queue Monitoring: queue table, progress, and selected-job details   │
└──────┴────────────────────────────────────────────────────────────────────────┘
┌────────────────────── Global Messages │ Job Messages ────────────────────────┐
│ five-line read-only log tail; newest line at the bottom                       │
└───────────────────────────────────────────────────────────────────────────────┘
```

- The rail is always visible and switches between mutually exclusive views.
- The message widget is always visible, retains its selected tab and contents,
  and has a user-resizable height.
- The main window opens at 1536 × 982 and cannot shrink below that size.
- Job Creation uses an editor/content region and a far-right preview pane with
  the approved 3:4 default geometry. Queue Monitoring hides creation controls.
- The queue view uses `Status`, `Job Name`, and `Remove` columns. Remove is
  available for cancelled and failed rows without confirmation.

## Approved visual specification

- Native macOS system sans font; 17 pt semibold section headings, 13 pt body
  text, 12 pt secondary text, and 12 pt fixed-width message tails.
- 8 px spacing grid: 4 px icon gaps, 8 px control gaps, 16 px group padding,
  24 px view margins, and 32 px major-region separation.
- Comfortable density: 32 px controls and rows, 32 × 32 px icon hit areas, and
  at least 8 px between adjacent hit targets. No compact mode.
- Codex-created monochrome vector icons cover the two navigation buttons, five
  source-preview controls, and terminal-job Remove action. Source-list actions
  and Preferences remain text-labeled.

## Approved state wireframes

The following wireframes describe observable states, not widget class choices.

| State | Job Creation view | Queue Monitoring view | Message behavior |
| --- | --- | --- | --- |
| Empty | Filename list empty; add/drop affordance; preview placeholder; submit disabled. | Empty queue state. | `Job Messages` shows `No job is selected.` |
| Editing | Ordered filenames, output settings, selected-source preview and icon controls; submit enabled only when fields are locally valid. | Existing queue remains available when switched to. | Selection activates `Job Messages`; output name appears after job start. |
| Validating | Creation fields and conflicting actions disabled; measured preflight progress visible. | Queue view remains navigable but does not start another processing job. | Preflight progress is appended to the job tail. |
| Preflight review | Modal issue/acknowledgement gate; Queue Job is enabled only when safety conditions pass. | Unchanged. | Blocking findings remain associated with the job. |
| Queued | Creation intent is preserved according to the approved view-state policy. | Row shows textual `Queued` status and job name; reorder actions apply only to pending jobs. | Job-specific events appear in the five-line tail. |
| Running | Preview pauses; creation controls cannot mutate the frozen request. | Row shows `Running`; both stage and whole-job progress are visible; cancellation is available. | Stage/progress events update `Job Messages`. |
| Cancelling | No new request can be started from the active request. | Row shows `Cancelling`; cancellation remains a normal state transition. | Cleanup/cancellation events update `Job Messages`. |
| Cancelled / Failed | No retry action. | `Remove` is visible and needs no confirmation. | Terminal details remain until the user removes the row or the application exits. |
| Completed | No retry action. | Completed row remains visible for the session without a Remove action unless later approved. | A completion line is appended to `Global Messages`; job details remain in `Job Messages`. |

## State transitions

```text
Editor:  empty → editing → validating → preflight review → queued
                                      └─ rejected/failed → editing

Queue:   queued → validating → running → completed
                              ├──────→ failed
                              └──────→ cancelling → cancelled

Preview: no source → loading → playing ⇄ paused
                    └──────────────→ unavailable/error
Selection change: stop old source → load new local source asynchronously → autoplay muted
Processing start: pause preview; processing completion never autoplays/resumes it

Preferences: closed → editing → validating → saved/closed
                                      └──────→ inline failure, remain open
```

All transitions preserve frozen job requests, ordered source intent, and the
frontend-independent queue state.

## Focus and accessibility criteria

These are baseline interaction requirements, not new shortcut or VoiceOver
features:

- Focus order follows the visible hierarchy: menu/rail, active-view controls,
  primary content, preview controls, message tabs, then the five-line log tail.
- Every icon-only control has an accessible name and tooltip; the name states
  the action, not merely the glyph (for example, `Next clip`).
- The active rail button, selected source row, selected queue row, and selected
  message tab have a visible non-color-only state.
- Status, progress, errors, and empty states are exposed as text; no workflow
  depends on color alone.
- Hidden-view controls are not reachable in the active view's tab order.
- Inline errors appear adjacent to the relevant control and remain readable at
  the minimum window size.

## Measurable layout and resizing criteria

- Initial and minimum window size are exactly 1536 × 982 logical pixels.
- At the minimum size, the rail, active view, source preview (when applicable),
  queue controls, and message tabs are visible without application-level
  scrolling.
- The message-area splitter responds to user drag and clamps at bounds that
  keep the tab bar and all five log lines readable while leaving the active
  view operable. Exact pixel bounds remain an implementation detail.
- Preview width remains three quarters of its default preview height; resizing
  never crops or stretches the native player output.
- Switching views does not change the main-window size, message-area height,
  selected message tab, selected source, or selected queue row.
- Long filenames, output paths, and translated strings wrap or elide without
  pushing primary controls outside the minimum window.

## Audit completion

This audit completes the Phase 1 “Audit and interaction specification” work:

- Current hierarchy, focus risk, workflows, and state transitions are recorded.
- Concrete usability findings are tied to approved Phase 1 responses.
- Empty, editing, validating, queued, running, failed, cancelled, and completed
  wireframes are defined.
- Accessibility and minimum-window criteria are measurable and testable.
- Typography, spacing, density, and the final icon inventory are approved.
