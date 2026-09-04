# V3 Phase 3 — Show Focused Clip Dimensions Beside Output Volume

## Status

- Development target: v3
- Phase: 3 (implemented)
- Predecessor: Phase 2 — Configurable Clip-Related File Deletion (complete)

## Purpose

Display the focused source clip's coded video dimensions (for example,
`1920×1080`) in the preview pane, immediately to the left of the existing
`Output volume` label. Dimensions must not be added to the source-clip list and
must not be reported through the Global Messages stream. Resolution is obtained
with FFprobe in the background and cached for the current GUI session.

## Scope

- **In scope:** Focused-clip dimension display in the preview audio-control row,
  background probing, cache, selection-priority scheduling, and tests.
- **Out of scope:** Dimensions in source-clip rows, dimensions in Global
  Messages, CLI changes, preflight report changes, crop/interpolation features,
  and output dimension display (already exists in `JobPlan`).

## Implementation Details

### 1. `src/advanced_ai_video_tools/gui/preview.py` — Focused dimension display

- Add one dedicated label to `SourcePreviewPane.dimension_info_and_volume_control_row` immediately before
  `outputVolumeLabel` (for example, object name `previewSourceDimensions`).
- Render dimensions as `W×H` using the existing secondary-label visual language.
  Show `Probing…` while pending and `Unavailable` for probe failures or clips
  without usable video dimensions; keep the label blank when there is no
  focused clip. Do not add a Global Message for probe failures.
- Preserve the existing `Output volume` label width and presentation contract
  (including its object name, fixed height, contents margins, and accessible
  text). Establish the current label width as the baseline and make that width
  explicit so the new dimension text cannot resize it. The new dimension label
  consumes space on its left, so the volume slider is the control that becomes
  narrower. Keep the slider usable at the preview pane's minimum width and
  verify the relationship with layout geometry tests rather than hard-coding a
  platform-specific slider width.
- Update the dimension label whenever `set_sources()` changes the focused path,
  using a cached result immediately when available. Do not alter source-list row
  construction.

### 2. `src/advanced_ai_video_tools/gui/clip_resolution.py` — Background probing and cache

- Add a session-scoped, dedicated Qt worker thread/controller. Keep all
  filesystem stat calls, FFprobe process creation, and probe parsing off the GUI
  thread; the GUI thread owns only cache state and label updates.
- Use a hybrid schedule: probe the focused clip first, then prewarm remaining
  clips during idle opportunities in source-list order. A newly focused clip
  always takes priority over queued prewarming work.
- Key entries by canonical path plus a file identity/version token (device,
  inode, size, and nanosecond mtime where available). Cache both successful
  dimensions and failures so repeated focus does not repeatedly probe an
  unchanged file; invalidate stale entries when the token changes and clear
  negative entries after a tool-setting change.
- Resolve the configured `ffprobe` executable in the worker context and reuse
  the typed probe client. Extract width and height from the first primary video
  stream only, report coded pixels, and intentionally do not apply rotation or
  sample-aspect-ratio transformations.
- Tag requests with the path/version and ignore late results for a no-longer
  focused clip. Shut down and join the worker during pane/application teardown.
- Keep the controller GUI-only; do not add deletion, CLI, pipeline, or preflight
  behavior.

### 3. Settings/tool reconfiguration

- Pass the current resolved tool configuration into the controller through the
  existing GUI settings application path. Reconfigure or replace the existing
  controller safely when settings are saved, without restarting the application.
- Apply saved settings to future probes and focused-clip displays only; never
  probe or mutate files while editing preferences.

### 4. Tests

- Controller tests: focused-first scheduling, list-order idle prewarming,
  cache/version invalidation, negative-result caching, stale-result suppression,
  tool reconfiguration, probe errors, and clean shutdown.
- Preview tests: dimensions appear only for the focused clip, cached results are
  applied without a new probe, and no dimension widget appears in source-list
  rows or Global Messages.
- Layout tests: the `Output volume` label keeps its existing width and
  accessibility identity; the dimension label is immediately to its left; the
  slider becomes the flexible/reduced-width control and remains usable at the
  preview minimum width.
- Media cases: valid video, non-video input, audio-only input, missing/unreadable
  file, and a file whose primary video stream has no valid dimensions.
- GUI lifecycle tests: removing/reordering clips, changing focus during a probe,
  closing the window, and applying changed tool settings do not update the wrong
  label or leak a worker.

## Test Plan

- Add focused unit/GUI coverage in the existing test modules and a small
  controller-focused module where that is the lowest practical layer.
- Run focused settings/probe/GUI tests, then `git diff --check` and `make check`.
- Because this phase changes native GUI presentation, perform the supported
  macOS GUI capture/acceptance check (`make gui-capture-test`) when the visual
  implementation lands; verify that the Output volume label remains stable and
  the slider has the intended reduced allocation.

## Assumptions

- The configured `ffprobe` path and existing typed probe client remain the source
  of truth; no new media dependency is introduced.
- “Dimension” means coded width × height from the primary video stream, not a
  rotated display size or aspect-ratio-adjusted size.
- The focused label is intentionally informational and compact: blank is the
  non-success state, so probe diagnostics do not compete with operational
  Global Messages.
- The feature is GUI-only and does not alter CLI behavior or processing plans.

## Verification evidence

- `UV_CACHE_DIR=/private/tmp/ai-video-tools-uv-cache make check` — 281 passed,
  3 opt-in native acceptance tests skipped.
- `git diff --check` — passed.
- `make gui-capture-test` — attempted; blocked because the execution
  environment exposed no active macOS display to Cocoa.
