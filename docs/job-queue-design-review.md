# Job Queue Job-List Design Review

## Review status

- Review type: Information architecture, visual design, and interaction design
- Date: 2026-08-29
- Scope: Queue Monitoring job list only
- Recommendation state: Proposed; no implementation is implied by this document

## Evidence reviewed

- [`gui/window.py`](../src/advanced_ai_video_tools/gui/window.py): monitoring
  layout, table configuration, selection, actions, and selected-job details
- [`gui/jobs.py`](../src/advanced_ai_video_tools/gui/jobs.py): immutable queue
  snapshots, table columns, accessibility text, and terminal-row actions
- [`tests/test_gui.py`](../tests/test_gui.py): queue rendering, selection,
  progress, cancellation, removal, and navigation coverage
- [Phase 1 GUI audit](v2/1-enhance-gui-audit.md): approved Queue Monitoring
  wireframe and state behavior
- [Phase 1 presentation architecture](v2/1-enhance-gui-presentation-architecture.md):
  Qt ownership, snapshot, focus, and accessibility boundaries

## Current experience

Queue Monitoring currently presents one flat three-column table:

```text
Job Queue
┌──────────────┬──────────────────────────────────────────────┬──────────┐
│ Status       │ Job Name                                     │ Remove   │
├──────────────┼──────────────────────────────────────────────┼──────────┤
│ Running      │ ai-video-...                                 │          │
│ Queued       │ ai-video-...                                 │          │
└──────────────┴──────────────────────────────────────────────┴──────────┘

Selected Job
Job Name: …
Status: …
Stage: …
Message: …
Output: …

Whole-job progress
Stage progress
[Move Up] [Move Down]                         [Cancel Job]
```

The implementation is safe and functionally complete: queue snapshots remain
immutable, the model preserves session order, selection drives the detail
surface, pending jobs can be reordered, and terminal failed/cancelled jobs can
be removed. The weakness is presentation clarity rather than queue behavior.

### Information-architecture findings

1. The table treats the active job, pending jobs, and terminal history as peers,
   although they have different user questions and available actions.
2. Queue position is available in the typed model but is not visible in the
   list. A user cannot quickly answer “what runs next?” without inferring it
   from row order and the separate Move Up/Move Down buttons.
3. Progress and current stage appear only in the selected-job area. Selecting a
   different row hides the active job's progress context.
4. The `Remove` column is usually blank and therefore looks like an incomplete
   table column. Its action meaning is also less obvious than a contextual
   terminal-row action.
5. The selected-job details are visually separated from the row that owns them;
   the relationship depends on selection highlighting.

### Look-and-feel findings

1. The current table has a generic data-grid silhouette inside an otherwise
   deliberately grouped native interface.
2. Status is textual, which is correct, but lacks a compact visual treatment
   that helps scanning without relying on color alone.
3. The fixed table height and large empty space after short queues make the
   queue feel disconnected from the detail and action regions.
4. The action row gives equal visual weight to Move Up, Move Down, and Cancel,
   even though Cancel is an active-job action and reordering is a pending-job
   action.

### Interaction findings

1. The primary interaction is row selection, but the design does not state what
   selection changes beyond the detail panel and message tab.
2. Actions are separated from the selected row, increasing pointer travel and
   making state-dependent availability harder to understand.
3. There is no explicit “next in line” cue, active-job anchor, or terminal-history
   cleanup affordance beyond the sparse Remove column.
4. The existing keyboard/focus behavior is structurally sound but should make
   the selected row, action group, and details relationship more explicit.

## Recommended enhancement: Queue workspace with three semantic regions

Replace the undifferentiated table presentation with a single Queue Monitoring
workspace containing three visually distinct regions:

```text
Queue Monitoring                                      [Clear terminal history]

ACTIVE
┌─────────────────────────────────────────────────────────────────────────────┐
│ ● RUNNING   Job name                                      [Cancel Job]       │
│             Stage: Encoding output                         38%               │
│             [stage progress]                         Output: …               │
└─────────────────────────────────────────────────────────────────────────────┘

UP NEXT                                                [Move Up] [Move Down]
┌────┬──────────────┬─────────────────────────────────────────────────────────┐
│ 1  │ QUEUED       │ Job name                                                  │
│ 2  │ QUEUED       │ Job name                                                  │
└────┴──────────────┴─────────────────────────────────────────────────────────┘

HISTORY
┌──────────────┬──────────────────────────────────────────────────────┬────────┐
│ COMPLETED    │ Job name                                             │        │
│ FAILED       │ Job name                                             │ Remove │
└──────────────┴──────────────────────────────────────────────────────┴────────┘

Selected job details and Job Messages remain below or beside the workspace.
```

This is a presentation change over the same `JobListModel` facts. It does not
create a second queue, reorder snapshots, or move lifecycle ownership into the
GUI.

### Region rules

- **Active:** show at most one job, because the backend permits one active
  processing job. Show state, job name, current stage/message, whole-job and
  stage progress, output, and the Cancel action together.
- **Up Next:** show queued jobs in authoritative FIFO order with an explicit
  one-based position. Reordering controls act only on the selected pending row.
- **History:** show completed, failed, and cancelled jobs in session order.
  Failed and cancelled rows expose Remove; completed rows remain visible without
  a destructive action unless a later decision adds history clearing.
- **Empty regions:** omit a region only if its absence is still explained by a
  concise empty state, such as `No active job` or `No queued jobs`.
- **Selected details:** retain the current detailed surface for the selected
  record, but visually connect it to the selected row/card with a shared
  selection treatment and a clear `Selected job` heading.

## Look-and-feel proposal

- Use the existing dark surfaces, 8 px spacing grid, native system font, and
  accessible contrast palette.
- Give each region a quiet section label (`Active`, `Up Next`, `History`) rather
  than adding a persistent product heading.
- Use 44–48 px rows/cards for comfortable scanning and pointer targeting. Keep
  the existing 32 px controls inside them.
- Render status as text plus a restrained status badge/icon. Never communicate
  state through color alone; preserve the accessible text such as `Status:
  Running`.
- Put progress beside the active job name and stage, not only in a distant
  selected-details panel.
- Make the active card visually primary with a slightly raised surface and a
  thin accent edge; keep queued and history rows flatter and quieter.
- Replace the mostly blank `Remove` table column with a contextual icon button
  or text action only on failed/cancelled history rows. Give it an accessible
  name such as `Remove failed job from session history`.
- Keep long job names elided with a tooltip/full accessible text. Keep output
  paths in selected details where they can wrap or be copied, rather than
  widening every list row.
- Keep the bottom message widget unchanged and preserve its session-only policy.

## Interaction proposal

### Selection and focus

- Selecting an active, pending, or history row updates the existing selected-job
  details and activates `Job Messages` exactly as today.
- The first active job is selected when it appears unless the user already has
  a valid selection; subsequent snapshots must not steal selection.
- Keyboard Up/Down moves through the visible logical order: Active, Up Next,
  then History. The selected row has a non-color-only focus/selection outline.
- Enter or Space selects the focused row without starting or cancelling work.
- Focus order is region label, row/card content, row action, then selected-job
  actions. Hidden-region controls are not tabbable.

### Actions

- Place `Cancel Job` inside the active card and show it only when the selected
  active state is cancellable. It remains disabled or changes to a clear
  cancelling state once cancellation has been requested.
- Place `Move Up` and `Move Down` beside the Up Next heading. Enable them only
  when the selected row is pending and a legal destination exists.
- Keep no-confirmation removal for failed/cancelled history rows, but locate the
  action beside the affected row and retain the existing safe model guard.
- Do not add retry, duplicate, edit, clear-all, or concurrent-processing
  actions in this enhancement.

### State behavior

| State | Primary presentation | Available action |
| --- | --- | --- |
| Queued | Up Next row with position and `Queued` text | Move up/down when legal; Cancel through existing selected-job action if supported by current policy |
| Validating | Active card with indeterminate progress and `Validating` text | Cancel when legal |
| Running | Active card with stage and whole-job progress | Cancel |
| Cancelling | Active card with `Cancelling` text and no competing action | No repeated cancel request |
| Completed | History row with `Completed` text | Select/details only |
| Failed | History row with `Failed` text and concise error indicator | Remove |
| Cancelled | History row with `Cancelled` text | Remove |

The backend remains authoritative for all transitions. The visual regions are
derived from immutable snapshots and must tolerate jobs moving between regions
without losing selection, messages, or details.

## Accessibility and resilience criteria

- Every status is readable as text and available through accessible row/card
  text, including position, job name, stage, and error state where applicable.
- Status badges/icons have meaningful accessible labels and never replace text.
- All state-dependent controls expose why they are disabled through a tooltip or
  adjacent explanation where the reason is not obvious.
- Long names and paths do not change the region hierarchy or push actions out
  of the minimum supported window.
- An empty queue explains the next legal action: `No jobs have been submitted.`
- A preview or message-panel change cannot alter queue ordering or frozen job
  intent.
- Queue updates delivered from worker threads continue through the existing
  queued Qt bridge; no snapshot processing occurs on the GUI thread beyond
  bounded presentation mapping.

## Suggested implementation slices

1. Add a typed presentation grouping for active, pending, and history records
   without changing `JobListModel` ownership or snapshot order.
2. Build the active card and move cancellation/progress presentation into its
   semantic region while retaining the selected-job details contract.
3. Build the Up Next list with visible positions and colocated reorder controls.
4. Build the History list with contextual terminal removal actions.
5. Add keyboard/focus and long-content tests, then run the full GUI and quality
   gates.

## Success measures

- A user can identify the currently running job and its progress without first
  selecting a row.
- A user can identify the next job and its queue position at a glance.
- A user can understand why each visible action is available or unavailable.
- Terminal cleanup is discoverable without a mostly empty action column.
- The queue remains legible at 1400 × 880 and with long generated names.
- Existing queue state transitions, FIFO ordering, cancellation, removal
  safety, message routing, and frozen requests remain unchanged.

## Decision requested

Approve or revise the three-region Queue workspace direction before making
implementation changes. The main unresolved product choice is whether completed
jobs should remain in a dedicated History region indefinitely for the session,
as they do today, or whether a later approved history-retention action should be
introduced. No history-retention action is included in this proposal.
