# Phase 6 — Information Architecture Update and GUI Enhancement

## Status

- Phase: 6
- State: In progress
- Predecessor: [Phase 5 — GUI Enhancement Including Fullscreen Preview](5-gui-enhancement.md)
- Successor: Phase 7 — Stabilization and Release
- Planning input: [Archived 2026-08-29 job-queue design review](../archive/2026-08-29-job-queue-design-review.md)

Phase 6 is approved and in progress. The first presentation-only grouping
slice is implemented; remaining interaction and responsive slices are tracked
below.

## Objective

Improve how the desktop GUI groups, names, prioritizes, and connects its
existing job-creation, queue-monitoring, preview, message, and action surfaces.
The primary Phase 6 focus is a more user-friendly Queue Monitoring information
architecture. The outcome should make the current task, selected object, job
state, queue order, and legal next action easier to understand without changing
media processing behavior.

## Scope

- Review the information architecture of Job Creation and Queue Monitoring as
  one coherent workspace, with Queue Monitoring as the first implementation
  priority.
- Reorganize Queue Monitoring so users can quickly distinguish active work,
  what will run next, terminal history, selected-job context, progress, and
  the actions that are legal for each state.
- Clarify the relationship among selected source clips or jobs, their details,
  previews, progress, messages, and available actions.
- Improve visual hierarchy, labels, empty states, focus order, and responsive
  layout where they obscure the current task.
- Refine existing GUI presentation components and add narrowly scoped
  presentation-only components when an approved information-architecture
  decision requires them.
- Preserve and extend accessible names, keyboard navigation, visible focus, and
  text alternatives for state that is not conveyed by color alone.

## Proposed Queue Monitoring design

The archived review's three-region queue workspace is the Phase 6 planning
baseline. It is adapted to the implemented tall far-right Queue Preview and
the shared left-side message splitter; neither is removed, repurposed, or moved.

```text
Queue Monitoring                                      Far-right Queue Preview
┌──────────────────────── left workspace ────────────────────────┐
│ ACTIVE                              │ HISTORY                  │
│ Running job, progress, and cancel   │ Completed, failed, and   │
│                                     │ cancelled jobs in session│
│ UP NEXT              [Up] [Down]    │ order; terminal removal  │
│ Ordered pending jobs with positions │ remains contextual.      │
│                                     │ This region scrolls at   │
│                                     │ 1400 × 880.              │
│                                                                 │
│ Selected job details                                            │
├────────────────────────────────────────────────────────────────┤
│ Global Messages | Job Messages                                  │
└────────────────────────────────────────────────────────────────┘
```

### Information architecture

- **Active** occupies the top-left region and contains at most one validating,
  running, or cancelling job. It
  keeps the job identity, current state, stage/message, measured progress,
  output summary, and legal cancellation affordance together so progress
  remains visible even when another job is selected.
- **Up Next** occupies the bottom-left region and contains queued jobs in
  authoritative FIFO order. Each row shows
  a one-based position, textual state, and job name. Move controls operate only
  on the selected pending job and retain the existing queue legality rules.
- **History** occupies the right region and spans the combined Active/Up Next
  height. It contains completed, failed, and cancelled jobs in existing session
  order. Completed jobs remain selectable but do not gain a destructive action.
  Failed and cancelled rows retain their existing no-confirmation, model-guarded
  removal behavior as contextual row actions.
- **Selected job details** remain the single detailed record surface and keep
  their existing message routing. They appear inline beneath the selected
  Active, Up Next, or History region, using a shared heading and selection
  treatment to make the owning row clear.
- **Queue Preview** remains the dedicated far-right presentation surface. It
  continues to follow the selected job and must not be folded into a queue row,
  moved, or made authoritative over queue state. Its **Original**, **Upscaled**,
  and **Final Video** tabs, including their existing sampling and completed
  output behavior, remain unchanged.
- **Integrated messages** remain in the shared bottom splitter beneath the
  left queue workspace. The session-only **Global Messages** and **Job
  Messages** tabs, their geometry, and their existing routing behavior remain
  unchanged.

### Visual and interaction design

- Use quiet `Active`, `Up Next`, and `History` section labels, the existing
  dark theme, 8 px spacing grid, native system font, and accessible contrast.
- Give Active modest emphasis through grouping and progress placement; queued
  and history rows remain visually quieter. Status remains text-only; no badge
  or icon is added.
- Replace the mostly empty table-wide Remove column with contextual actions only
  on eligible History rows. Long job names remain elided visually while full
  text stays available through tooltips and accessible names.
- Selecting any visible record updates selected-job details, Job Messages, and
  Queue Preview as it does today. Incoming snapshots must not steal a valid
  user selection.
- Keyboard Up/Down follows the visible logical order—Active, Up Next, then
  History. Enter or Space selects the focused record only; it never starts,
  cancels, reorders, or removes a job. Hidden-region controls are not tabbable.
- At the supported 1400 × 880 minimum, Active and Up Next remain visible while
  History is vertically scrollable. Empty regions remain visually quiet without
  explanatory labels.

## Non-goals and invariants

- Do not change the typed job request, queue ordering and execution model,
  preflight authority, media pipeline, output publication, or safety policy.
- Do not add timeline editing, media trimming, filters, proxy generation, or
  output-preview processing.
- Do not move long-running work onto the GUI thread or make presentation state
  authoritative over queue state.
- Maintain the far-right three-tab Queue Preview and the bottom integrated
  message area while reorganizing the left Queue Monitoring workspace.
- Preserve the established dark theme, user preview preferences, fullscreen
  keyboard-only control boundary, and session-only messages unless a later
  approved decision explicitly supersedes one of them.
- Keep the CLI and GUI thin adapters over the same typed application service.

## Approved design decisions

1. Use the **Active / Up Next / History** Queue Monitoring layout.
2. Keep completed jobs visible in History for the session. Phase 6 does not add
   clear-all, retry, duplicate, edit, or concurrent-processing actions.
3. At 1400 × 880, keep Active/Up Next in the left column, make History span the
   right column, and make History vertically scrollable.
4. Use text-only status; do not add status badges or icons.
5. Show selected-job details inline beneath the selected region.

## Work breakdown

1. Add a presentation-only grouping layer derived from immutable
   `JobListModel` snapshots; it must not create a second queue, reorder
   snapshots, or change lifecycle ownership.
2. Build the Active region and colocate existing progress and cancellation
   presentation while retaining selected-job details and Queue Preview behavior.
3. Build Up Next with visible FIFO positions and colocated existing reorder
   controls, then build History with contextual existing terminal removal.
4. Refine selection, keyboard focus, accessible names, empty states, long-name
   handling, and 1400 × 880 layout behavior.
5. Add regression coverage for grouping, state transitions, selection
   retention, actions, focus order, accessibility, and Queue Preview isolation;
   run focused GUI checks and `make check`.
6. Update the README, architecture document, changelog, and this phase record
   only when an approved decision changes implemented behavior.

## Acceptance criteria

- Users can identify the current view, selected object, its current state, and
  its available action without relying on color alone.
- Queue Monitoring makes active work, next queued work, terminal history,
  selected-job details, progress, and state-dependent actions easy to locate
  without changing the authoritative queue model.
- The active job's state and progress stay visible without requiring selection;
  pending position is visible; and terminal cleanup is discoverable without a
  mostly empty action column.
- At 1400 × 880, Active and Up Next remain visible in the left column while
  History fills and scrolls in the right column; status remains understandable
  through text alone; and selected details remain inline with their owning
  region.
- Job Creation and Queue Monitoring preserve the same queue, preflight, media,
  and fullscreen contracts after the presentation changes.
- The layout remains usable at 1400 × 880 and scales without overlapping or
  hiding essential controls.
- Focus order, keyboard operation, accessible names, and disabled-action
  behavior remain covered by regression tests.
- Focused checks and `make check` pass; required supported-macOS manual
  verification is recorded before the phase becomes complete.

## Completion evidence

### Queue region grouping slice — in progress

- Added Active, Up Next, and History proxy views derived from the existing
  immutable `JobListModel`.
- Reflowed the visible workspace so Active sits top-left, Up Next sits
  bottom-left, and vertically scrollable History fills the right column across
  their combined height.
- Preserved the hidden compatibility table and canonical selection path while
  visible region selections map back to the same source index.
- Kept the far-right three-tab Queue Preview and bottom integrated messages
  unchanged.
- Added focused GUI coverage for region counts, empty states, and selection
  mapping.
- Validation: `UV_CACHE_DIR=/private/tmp/ai-video-tools-uv-cache make check` —
  260 passed, 2 native-only tests skipped; Black, Pylint, and pycodestyle passed.

Remaining Active/Up Next/History action placement, focus, long-name, and
responsive-layout slices remain before Phase 6 can be marked complete.
