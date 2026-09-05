# GUI UX Review

> Archived 2026-08-31. This is historical proposal material; current decisions
> and implementation status are maintained in `docs/v2` and `docs/ARCHITECTURE.md`.

## Review status

- Review type: Information architecture, visual design, and interaction design
- Date: 2026-08-29
- Scope: Current macOS GUI, including Job Creation, source preview, fullscreen
  preview, Queue Monitoring, Preferences, preflight review, and messages
- Recommendation state: Proposed; this document does not authorize or claim
  implementation

## Purpose

This document reviews the current GUI as a coherent user experience rather than
as a collection of widgets. It identifies what is working, where the interface
creates avoidable interpretation or interaction cost, and which enhancements
would provide the most value without changing the media pipeline or safety
contracts.

The separate [Job Queue Job-List Design Review](2026-08-29-job-queue-design-review.md)
contains a deeper proposal for Queue Monitoring. This review references that
proposal but does not duplicate its full design.

## Evidence reviewed

- [`gui/window.py`](../../src/advanced_ai_video_tools/gui/window.py): application
  shell, navigation, Queue Monitoring, selection, progress, and actions
- [`gui/editor.py`](../../src/advanced_ai_video_tools/gui/editor.py): source list,
  per-row actions, settings, and preflight entry
- [`gui/preview.py`](../../src/advanced_ai_video_tools/gui/preview.py): embedded and
  fullscreen preview, playback controls, shortcuts, help, and lifecycle
- [`gui/messages.py`](../../src/advanced_ai_video_tools/gui/messages.py): Global
  Messages and Job Messages presentation
- [`gui/submission.py`](../../src/advanced_ai_video_tools/gui/submission.py):
  preflight review and queue-submission flow
- [`gui/preferences.py`](../../src/advanced_ai_video_tools/gui/preferences.py):
  Preferences and external-tool validation
- [`gui/theme.py`](../../src/advanced_ai_video_tools/gui/theme.py): spacing,
  typography, colors, controls, tables, and progress styling
- [`tests/test_gui.py`](../../tests/test_gui.py) and related GUI tests: observable
  behavior and accessibility contracts
- [Phase 1 GUI audit](../v2/1-enhance-gui-audit.md) and
  [presentation architecture](../v2/1-enhance-gui-presentation-architecture.md):
  approved design intent and boundaries

## Reference framework

The review applies the following authoritative guidance:

- Apple recommends using macOS's spacious desktop environment to present more
  content with fewer nested levels, supporting window flexibility, familiar
  full-screen behavior, and keyboard workflows. See
  [Designing for macOS](https://developer.apple.com/design/human-interface-guidelines/designing-for-macos/).
- Apple describes a sidebar as navigation among peer sections and recommends
  familiar symbols, succinct labels, and the ability to reclaim content space
  where appropriate. See
  [Sidebars](https://developer.apple.com/design/human-interface-guidelines/sidebars).
- Apple recommends accurate determinate progress when measurable, concise
  context for long-running work, a consistent progress location, and safe
  cancellation when feasible. See
  [Progress indicators](https://developer.apple.com/design/human-interface-guidelines/progress-indicators).
- WCAG 2.2 requires logical focus order, visible focus, labels that identify
  purpose, non-obscured focus, programmatic name/role/value, and perceivable
  status updates. See
  [Understanding WCAG 2.2](https://www.w3.org/WAI/WCAG22/understanding/).
- WCAG 2.2's minimum target-size guidance uses 24 by 24 CSS pixels or sufficient
  spacing as the baseline. The application's 32 by 32 logical-pixel controls
  exceed that reference target. See
  [Understanding Target Size (Minimum)](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum).
- Qt's model/view architecture separates data from presentation and supports
  multiple views over one model, which is appropriate for the immutable queue
  snapshot boundary. See
  [Qt Model/View Tutorial](https://doc.qt.io/qtforpython-6/overviews/qtwidgets-modelview.html)
  and [QTableView](https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QTableView.html).

These references inform the recommendations; they are not treated as a claim of
formal WCAG conformance or native AppKit equivalence.

## Executive assessment

The GUI has a sound product structure and strong safety boundaries. Job
Creation and Queue Monitoring are separated, the selected-source preview cannot
change processing intent, long-running work stays off the presentation thread,
and preflight remains an explicit safety gate. The dark theme, 8 px spacing
grid, 32 px controls, accessible names, progress text, and session messages give
the application a coherent base.

The principal UX problem is that the interface exposes implementation-shaped
surfaces more clearly than task-shaped outcomes. Users must learn which panel
owns feedback, infer relationships between selected rows and distant details,
and distinguish similar icon actions through tooltips. The application is
usable, but its hierarchy and interaction grammar could better answer four
questions at a glance:

1. What am I preparing?
2. Is it valid and safe to queue?
3. What is processing now and what happens next?
4. What action can I take in the current state?

## Current information architecture

```text
Main window
├── Edit menu
│   └── Preferences
├── Persistent navigation rail
│   ├── Job Creation
│   │   ├── Basic Settings
│   │   ├── Source Clips
│   │   └── Selected-source Preview
│   └── Queue Monitoring
│       ├── Job Queue table
│       ├── Selected Job details
│       ├── Whole-job and stage progress
│       └── Move / Cancel actions
└── Persistent message splitter
    ├── Global Messages
    └── Job Messages

Secondary surfaces
├── Preferences / external-tool validation
├── Preflight review and dropped-stream acknowledgement
└── Fullscreen selected-source preview and shortcut help
```

### Information-architecture strengths

- Creation and monitoring are peer workspaces rather than one overfilled page.
- Preferences are separated from ordinary job intent.
- Global and job-specific messages have explicit ownership.
- Preflight review remains a distinct safety decision instead of being diluted
  into ordinary inline validation.
- Source preview and fullscreen preview are presentation-only and never become
  an alternate processing path.

### Information-architecture findings

#### High priority: the feedback hierarchy is fragmented

Validation, preflight progress, queue lifecycle, selected-job details, progress
bars, Global Messages, and Job Messages are all legitimate surfaces, but the
user must learn their ownership. The same job can be represented in the queue
row, Selected Job group, two progress bars, and Job Messages simultaneously.

Recommendation: establish one primary status location per task stage:

- Draft validation belongs adjacent to Job Creation and the Preflight action.
- Preflight findings belong in the review surface.
- Active execution status and progress belong with the active job in Queue
  Monitoring.
- Global Messages remain for application-level events and recovery context.
- Job Messages remain the chronological detail trail, not the primary current
  status.

This follows Apple's guidance to keep progress in a consistent, predictable
location and WCAG's principle that status updates should be perceivable without
forcing disruptive context changes.

#### High priority: Queue Monitoring does not mirror queue semantics

The current flat table presents active, pending, and terminal jobs as equivalent
rows even though their meaning and actions differ. Adopt the three-region
Active / Up Next / History proposal in the
[queue design review](2026-08-29-job-queue-design-review.md). It can remain a presentation
over the same typed snapshots and Qt model/view boundary.

#### Medium priority: source-row actions compete with source identity

Each source row combines filename, fullscreen, remove, and overflow controls.
This is functional but visually action-heavy for the primary task of confirming
clip order.

Recommendation:

- Keep filename and order as the dominant row content.
- Keep one high-frequency row action visible only if evidence shows it is used
  often; place lower-frequency filesystem and destructive actions in the
  overflow menu.
- Use one consistent fullscreen glyph, tooltip, hit area, and accessible name
  across the source row and embedded preview.
- Preserve selection when opening a menu or preview, and ensure per-row actions
  do not accidentally initiate drag/reorder behavior.

#### Medium priority: navigation rail meaning depends on icons and tooltips

The rail has only two destinations, which is structurally simple, but icon-only
navigation requires recall. Apple's sidebar guidance favors familiar symbols
and succinct descriptive labels, especially for peer sections.

Recommendation: retain the compact rail at the minimum width, but consider a
user-revealable labeled state or persistent short labels when space permits.
The active destination should remain apparent through shape, text/accessibility
state, and focus—not color alone.

## Visual-design review

### Strengths

- The dark theme uses a restrained neutral palette and a consistent surface
  hierarchy.
- The 8 px spacing grid and 32 px control system create predictable rhythm.
- Group boxes give Job Creation strong section boundaries.
- Textual statuses and progress labels avoid color-only state communication.
- Source preview uses aspect-preserving native video rendering.

### Findings and recommendations

#### High priority: reduce equal visual weight

Many groups, borders, buttons, and headings use similar contrast and weight.
When everything is framed, users spend more time locating the primary action.

Recommendation:

- Define three surface levels: window background, section surface, and active or
  selected surface.
- Use strong borders only for focus, selection, validation, or a safety gate.
- Keep passive explanatory groups quieter than interactive lists and primary
  actions.
- Give `Preflight`, active-job progress, and the currently legal destructive
  action clear but distinct emphasis.

#### High priority: make selected context unmistakable

Source selection, queue selection, active navigation, and message-tab selection
all use related dark-blue treatments. This is consistent, but the connection
between a selected item and its details is not always visually direct.

Recommendation:

- Use a shared selection edge/accent and align selected details directly with
  the owning list or card.
- Preserve a visible keyboard-focus ring distinct from selection state, in line
  with WCAG focus-visible guidance.
- Verify selected, hovered, focused, disabled, and pressed states separately in
  increased-contrast mode.

#### Medium priority: simplify typography roles

The interface has section titles, group titles, body labels, secondary labels,
table headers, messages, and button text. The roles are individually reasonable
but need a documented hierarchy to prevent drift.

Recommendation: freeze a small semantic scale:

| Role | Intended use |
| --- | --- |
| Window/workspace title | Optional, one per active workspace |
| Section title | Basic Settings, Source Clips, Preview, Job Queue |
| Body | Labels, values, status, ordinary buttons |
| Secondary | Guidance, metadata, disabled explanations |
| Monospace | Message history and exact technical identifiers only |

#### Medium priority: use responsive space rather than fixed visual islands

The 1400 by 880 minimum provides room, but fixed panel and table dimensions can
leave empty areas or constrain long content. Apple encourages Mac interfaces to
take advantage of large displays while remaining adaptable.

Recommendation:

- Let semantically important content—source list, preview, active job, and job
  name—absorb additional width.
- Keep action columns and icon hit areas fixed.
- Use elision with full tooltips/accessibility text for names and wrapping for
  paths in detail surfaces.
- Preserve the user-resizable message splitter and ensure neither side can
  obscure focus or primary actions.

## Interaction-design review

### Strengths

- Selection-driven source preview does not reorder clips or mutate the request.
- Queue actions are guarded by typed state and illegal actions are disabled.
- Processing start pauses preview and does not unexpectedly resume it.
- Fullscreen preview supports keyboard-only playback and a `?` help surface.
- Cancellation, cleanup, and shutdown have explicit ownership.

### Findings and recommendations

#### High priority: keep action availability close to its object

Move Up, Move Down, Cancel, and terminal Remove are state-specific, but some are
physically separated from the row they affect.

Recommendation: colocate actions by semantic region:

- Reorder beside the pending queue.
- Cancel beside the active job.
- Remove on the failed/cancelled history row.
- Keep Preflight beside draft readiness and validation feedback.

This reduces reliance on remembered selection and makes disabled-state logic
easier to understand.

#### High priority: formalize keyboard and focus behavior

The GUI uses native Qt traversal and accessible names, but an app-wide keyboard
model is not presented to users outside fullscreen preview.

Recommendation:

- Document tab order for each workspace and dialog.
- Ensure hidden workspace and hidden fullscreen controls are absent from tab
  traversal.
- Preserve selection while focus moves to details or actions.
- Add standard menu commands for major workspace actions where appropriate, as
  Mac users expect keyboard-accessible commands in the menu bar.
- Never allow a valid shortcut to trigger a different action because a child
  control happened to own focus.

#### Medium priority: fullscreen control discovery is unconventional

Fullscreen playback controls are hidden by default and appear after an
unrecognized key; the top-right close control follows the same lifecycle. This
minimizes visual distraction but differs from common media behavior, where
pointer movement or initial entry reveals controls.

Recommendation: test the current rule with users. If users fail to discover
exit, seeking, or help, consider showing controls briefly on entry and on pointer
movement, then auto-hiding. Preserve `Esc` as an immediate exit and `?` as help.
Any change must remain presentation-only.

#### Medium priority: errors need recovery-oriented wording

The application correctly keeps detailed diagnostics outside the GUI and uses
concise messages. Review every visible error against a consistent pattern:

```text
What happened → What remains safe → What the user can do next
```

For example, preview failure already follows this well by explaining that
preflight can still inspect the clip. Extend that pattern to tool validation,
preflight rejection, queue failure, and settings-save failure.

#### Low priority: avoid accidental destructive activation

Source removal changes only list intent, while Move to Trash changes the
filesystem and has queue guards. Keep those actions visually and verbally
distinct. Destructive filesystem actions should remain in the overflow menu,
state the affected filename, and preserve current fail-closed behavior.

## Proposed target information architecture

```text
Application shell
├── Menu bar
│   ├── Edit → Preferences
│   └── View → Job Creation / Queue Monitoring / message-area visibility
├── Adaptive labeled navigation rail
│   ├── Job Creation
│   │   ├── Basic Settings
│   │   ├── Source Clips and row actions
│   │   ├── Selected-source Preview
│   │   └── Draft readiness + Preflight
│   └── Queue Monitoring
│       ├── Active job + progress + Cancel
│       ├── Up Next + positions + reorder
│       ├── History + contextual removal
│       └── Selected-job details
└── Persistent contextual messages
    ├── Global Messages
    └── Job Messages

Secondary surfaces
├── Preferences with validation state
├── Preflight safety review
└── Fullscreen source preview + shortcut help
```

The target preserves the current two-workspace model while making current state
and legal actions more local and easier to scan.

## Prioritized enhancement plan

### Priority 0 — protect existing contracts

- Preserve one shared typed application service for CLI and GUI.
- Preserve concat-first, upscale-at-most-once processing.
- Preserve immutable queued requests and authoritative queue state.
- Keep all long-running work off the GUI thread.
- Preserve explicit preflight acknowledgement and safe cancellation/cleanup.

### Priority 1 — clarify monitoring and status

1. Implement the Active / Up Next / History queue workspace.
2. Put active progress and Cancel with the active job.
3. Make queue position visible and reorder controls local to pending jobs.
4. Reduce duplicate current-status presentation between details, progress, and
   messages.

### Priority 2 — strengthen hierarchy and focus

1. Define surface, typography, selection, and focus roles as reusable semantics.
2. Distinguish selection from keyboard focus and verify increased contrast.
3. Document and test focus order for both workspaces and all dialogs.
4. Add a responsive labeled navigation option without increasing the minimum
   window requirement.

### Priority 3 — simplify creation and preview actions

1. Reassess which source-row actions need persistent visibility.
2. Validate fullscreen control discoverability with user observation.
3. Standardize recovery-oriented messages and next-action wording.
4. Review long filenames, long paths, and localization expansion at minimum and
   larger window sizes.

## Validation approach

Automated checks should verify:

- Typed state-to-view mapping for every queue state.
- Selection preservation across snapshots and workspace switching.
- Legal/illegal action availability and accessible names.
- Focus order, visible focus styling, and hidden-control exclusion.
- Long-content elision/wrapping and minimum-window geometry.
- Determinate versus indeterminate progress presentation.
- Preview and queue interactions cannot mutate frozen job intent.

Manual checks on the supported macOS target should cover:

- Native appearance, increased contrast, multiple displays, and window resizing.
- Keyboard-only completion of Job Creation and Queue Monitoring tasks.
- VoiceOver reading order, names, states, status updates, and action discovery.
- Fullscreen entry/exit, shortcut help, hidden-control discovery, and display
  restoration.
- Pointer targeting and accidental activation around dense source-row actions.

## Success criteria

- A first-time user can identify where to create a job, where to monitor it, and
  where to find application versus job-specific messages without instruction.
- The current job, next queued job, progress, and available action are visible
  without changing selection.
- Every state and action remains understandable without color.
- Keyboard focus is always visible, ordered, and unobscured.
- Primary controls meet or exceed the application's 32 by 32 logical-pixel
  target and retain adequate spacing.
- The GUI remains usable at 1400 by 880 and takes advantage of larger Mac
  windows without leaving semantically important content constrained.
- No UX enhancement changes media policy, queue ownership, processing intent,
  publication safety, or network behavior.

## Decisions requested before implementation

1. Approve or revise the Active / Up Next / History queue structure.
2. Decide whether the navigation rail may expose labels when space permits.
3. Decide whether fullscreen controls should remain discoverable only through
   invalid-key feedback or briefly appear on entry/pointer movement.
4. Decide which source-row actions remain persistently visible.
5. Decide whether completed history remains session-long with no clear action,
   as today, or whether a later scoped history-retention control is desirable.
