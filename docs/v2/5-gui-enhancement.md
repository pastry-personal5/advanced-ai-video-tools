# Phase 5 — GUI Enhancement Including Fullscreen Preview

## Status

Verification. Phase 5 adds fullscreen presentation for the existing selected-source
preview. It is a GUI-only feature and does not change processing, preflight, or
the typed job request.

## Outcome

Users can open the selected local source clip in an immersive fullscreen preview
and control playback and clip navigation from the keyboard. A visible help
surface documents every fullscreen-preview shortcut.

## Approved interaction design

The existing source preview remains the source of truth for the selected local
clip, player state, audio preferences, and presentation-only behavior. The
fullscreen view should preserve the current source and playback position when it
opens and closes.

Fullscreen opens from either of two discoverable entry points:

- An expand button in the existing source-preview pane, which opens the
  currently selected clip.
- A `Start Fullscreen Preview` button at the right side of each source-clip
  list row, which selects that row and opens its clip in fullscreen.

The fullscreen view is a dark, borderless Qt dialog or equivalent dedicated
preview surface with no clickable controls. The view receives keyboard focus
while it is open; unrecognized key input has no playback or presentation effect.

| Hotkey | Action |
| --- | --- |
| `0` | Go to first frame |
| `9` | Go to last frame |
| `j` | Select previous clip |
| `l` | Select next clip |
| `Space` / `k` | Play or pause the current clip |
| `Shift-P` | Select and play the previous clip |
| `Shift-N` | Select and play the next clip |
| `Esc` | Close the help surface if open; otherwise close fullscreen preview |
| `?` (`Shift+/` on a standard keyboard) | Show or hide keyboard shortcut help |

Clip navigation does not wrap. `j` and `l` select the adjacent clip using the
existing editor selection path and autoplay the newly selected clip. `Shift-P`
and `Shift-N` select the adjacent clip and start playback from that clip's
beginning. At either boundary, the corresponding action is disabled and has no
effect.

The help surface is a simple borderless, non-activating dialog titled
`Preview Keyboard Shortcuts`. It is anchored at the right side and vertically
centered over the fullscreen preview. Its text is opaque white and its dark
background uses 50% opacity so the underlying video remains visible. It lists
the exact bindings above, does not stop or reset playback, and toggles with `?`;
the first `Esc` closes help and leaves fullscreen preview open.

### Tall preview-column layout and Queue Preview

- The shared left workspace contains the active Job Creation or Queue Monitoring
  surface above the resizable integrated message tabs. This narrows the message
  panel and keeps its exact geometry while switching views.
- A far-right preview stack spans nearly the full content height. Job Creation
  shows the selected source preview there, while Queue Monitoring shows the
  selected job's multipurpose Queue Preview.
- The source-clip list is narrower than before so the source preview receives a
  larger share of the application width and near-full application height.
- During a selected running job's `UPSCALE` stage, Queue Preview asynchronously
  decodes and displays the latest completed local upscaled PNG at frames 16,
  32, and every later multiple of 16. It retains that last image through later
  running stages and never polls, blocks, or affects the worker.
- On selected-job completion, Queue Preview switches to the published local
  final video, starts playback automatically, and loops indefinitely. It
  exposes play/pause, first frame, last frame, and a progress/seeking bar; it
  retains the existing non-safety preview mute and volume preferences.
- The completed-video First Frame and Last Frame actions pause playback and show
  a centered, non-activating hourglass-style `Loading first frame…` or `Loading
  last frame…` hint until the native player reports that requested seek
  position; errors, source changes, and shutdown dismiss the hint.
- Queued, validating, cancelling, failed, cancelled, and missing-output
  selections display an explanatory empty state. Queue Preview never alters
  processing intent or treats a partial encoded video as playable media.

## Approved boundaries and invariants

- Both preview surfaces remain playback-only; no trimming, filtering, frame export, or concat-boundary editing is added.
- Fullscreen mode previews only the currently selected local editor source.
- Entering fullscreen, leaving fullscreen, and using shortcuts cannot mutate ordered input paths or frozen job intent.
- Existing mute, volume, navigation, playback, seeking, error, pause-on-processing, and shutdown behavior remains authoritative.
- Preview failures remain non-blocking and retain the existing message: `Preview unavailable; preflight can still inspect this clip.`
- No FFmpeg, FFprobe, Real-ESRGAN, proxy media, or processing service is introduced into the fullscreen preview.
- Keyboard handling must work when the video surface or dialog has focus and must not depend on mouse focus after opening.
- Shortcut help must use a separate translucent tool-dialog surface so native video stacking cannot hide it; showing help must not take keyboard focus from fullscreen playback.
- One authoritative shortcut registry must drive both event resolution and help text so bindings cannot drift from documentation.
- Fullscreen key presses and releases must be consumed once inside the dialog boundary; modifier-only and auto-repeat events must not trigger commands.
- Fullscreen exposes no clickable playback, seeking, navigation, help, or close controls; keyboard shortcuts are the only fullscreen interaction path.
- Fullscreen cleanup must release dialog/widget ownership cleanly and must not create a second live player or orphan a native video output.
- The implementation remains within the supported macOS/PySide6 GUI target and does not add platform-specific unvalidated behavior.
- Queue Preview loads only the selected job's measured sixteen-frame upscale
  samples while it is running, or its local published path after completion. It
  owns its own image loader and player and remains independent of pipeline
  execution, preflight, and queue intent.

## Work breakdown

### 1. Presentation design and state

- [x] Define both fullscreen entry points—the preview-pane expand button and the per-source-row `Start Fullscreen Preview` button—along with dialog flags, dark surface, sizing, and focus policy.
- [x] Define how the existing `QMediaPlayer`/`QVideoWidget` ownership and video output move between the pane and fullscreen surface.
- [x] Define the keyboard-only fullscreen surface, dialog focus policy, and help-surface layout.
- [x] Define behavior for fullscreen entry, exit, help open/close, source selection, player error, processing start, and application shutdown.

### 2. Fullscreen implementation

- [x] Add the preview-pane expand control and a `Start Fullscreen Preview` action at the right of every source-clip list row.
- [x] Implement fullscreen entry and exit without creating proxy media or changing the selected source.
- [x] Preserve source, playback position, play/pause state, mute state, and volume across entry/exit wherever native Qt lifecycle permits.
- [x] Add fullscreen keyboard playback, seeking, first/last-frame, previous/next, exit, and help controls using the existing presentation boundary.
- [x] Add keyboard bindings for `0`, `9`, `j`, `l`, `Space`, `k`, `Shift-P`, `Shift-N`, `Esc`, and `?`.
- [x] Implement non-wrapping clip navigation with autoplay for `j`/`l` and immediate playback from the beginning for `Shift-P`/`Shift-N`.
- [x] Remove clickable fullscreen controls so unrecognized keyboard input has no visible effect.
- [x] Implement the borderless right-center keyboard-help dialog, translucent-video treatment, and non-activating focus/escape behavior.
- [x] Ensure fullscreen closes or safely exits before the main window releases preview resources.

### 3. Regression coverage

- [x] Test fullscreen entry and exit with no selected source, a valid source, and a preview-error source.
- [x] Test that source identity, ordered editor inputs, and built job requests remain unchanged.
- [x] Test all keyboard bindings, including physical `?`/`Shift+/` variants, `Shift-P`/`Shift-N`, clip-list boundaries, child-widget focus, key-release suppression, repeated key presses, and help toggling.
- [x] Test that `Esc` closes help before fullscreen and closes fullscreen afterward.
- [x] Test preservation of playback position and audio preferences across fullscreen transitions.
- [x] Test player/dialog cleanup during normal close, source changes, processing start, and main-window shutdown.
- [x] Test keyboard focus and the absence of fullscreen clickable controls, along with the help surface, with offscreen Qt fixtures where practical.

### 4. Documentation and verification

- [x] Update the architecture document with the implemented fullscreen ownership and focus boundary.
- [x] Update README user guidance with the fullscreen control and keyboard shortcuts.
- [x] Add the completed feature to `CHANGELOG.md` under `Unreleased`.
- [x] Run focused GUI tests and `make check`.
- [ ] Complete a supported macOS manual check for fullscreen presentation, keyboard handling, help, focus, display restoration, and shutdown cleanup.
- [x] Record implementation evidence, exact checks, manual limitations, and remaining risks below.

## Acceptance criteria

- A user can open the currently selected source clip in fullscreen from the existing preview pane.
- A user can select any source row and start that clip directly in fullscreen using the row action at the right.
- Job Creation shows a tall far-right selected-source preview and the narrower
  shared message panel stays the same size after switching views.
- Queue Monitoring shows a tall far-right Queue Preview: it displays the
  selected running job's latest sampled upscaled frame every 16 frames, then
  automatically loops that selected completed job's published final video.
- The completed-video mode offers play/pause, first frame, last frame, and a
  progress/seeking bar without changing the job or output.
- A delayed completed-video First Frame or Last Frame seek visibly reports its
  requested-frame loading hint; the actual final frame remains paused once it
  arrives.
- The fullscreen video preserves aspect ratio and remains presentation-only.
- `0` seeks to the first frame and `9` seeks to the last frame.
- `j` and `l` navigate to adjacent clips without wrapping and autoplay the newly selected clip.
- `Space` and `k` play or pause the current clip.
- `Shift-P` and `Shift-N` navigate to the adjacent clip and begin playback from its start.
- `Esc` closes the help overlay first, then exits fullscreen preview.
- `?` opens and closes a borderless right-center help dialog listing the exact keyboard bindings with opaque white text over a 50%-opaque background.
- The fullscreen surface exposes no clickable controls; documented keyboard shortcuts are its only interaction path.
- Unrecognized keyboard input does not alter playback or reveal presentation controls.
- Fullscreen transitions do not alter clip order, job intent, preflight results, or processing behavior.
- Preview errors remain non-blocking and do not create proxy media.
- Fullscreen and help surfaces clean up correctly on exit, source changes, processing start, and application shutdown.
- Focused GUI tests and the full quality gate pass, with supported-macOS manual verification recorded.

## Out of scope

- Previewing queued-job media, merged intermediates, partial encoded outputs,
  or simulated processed output. The approved live 16-frame upscaled PNG sample
  is the sole workspace-media exception.
- Trim points, timeline editing, filters, frame export, concat-boundary editing, and loop controls.
- New media codecs, rotation handling, color handling, HDR handling, or processing-pipeline changes.
- FFmpeg-generated preview proxies or Real-ESRGAN execution.
- Persisting fullscreen state, keyboard-help visibility, or new user preferences.
- Global application keyboard shortcuts outside the focused fullscreen preview.

## Implementation evidence

### Fullscreen preview slice — completed

- Added the preview-pane expand button and per-source-row `Start Fullscreen Preview` action.
- Refined the per-source-row fullscreen action with a centered 16 px app-owned
  muted-gray icon and the same transparent 32 px button treatment as the
  adjacent Remove and More actions.
- Reworked the main layout around a shared left-side content/message splitter
  and a near-full-height far-right preview stack; narrowed the source-clip list
  and kept the message widget's geometry stable between views.
- Evolved the Queue Monitoring player into a multipurpose Queue Preview that
  decodes only measured local upscaled PNG samples at 16-frame intervals for
  the selected running job, then automatically loops its published local final
  video after completion.
- Removed all fullscreen buttons, timeline controls, and auto-hiding control
  chrome; the existing keyboard registry and help dialog are now the only
  fullscreen interaction surfaces.
- Reused the existing `QMediaPlayer` and `QVideoWidget` by moving the video widget into a borderless fullscreen dialog; no second player or proxy media is created.
- Added approved keyboard shortcuts, the `Preview Keyboard Shortcuts` help panel, and non-wrapping autoplay navigation without adding fullscreen buttons or a control bar.
- Consolidated keyboard handling into one immutable binding registry and one dialog-scoped dispatcher; help is generated from the registry, key releases are consumed once, and rapid playback toggles use synchronous requested state.
- Preserved presentation-only behavior, ordered input intent, player error handling, processing pause, and shutdown cleanup.
- Focused validation: `UV_CACHE_DIR=/private/tmp/ai-video-tools-uv-cache uv run pytest tests/test_gui.py -q` — 37 passed.
- Full validation: `UV_CACHE_DIR=/private/tmp/ai-video-tools-uv-cache make check` — 253 passed, 2 native-only tests skipped; Black, Pylint, and pycodestyle passed.
- Fullscreen row-icon refinement validation: `UV_CACHE_DIR=/private/tmp/ai-video-tools-uv-cache uv run pytest tests/test_gui_submission.py::test_source_row_fullscreen_action_matches_adjacent_icons -q` — 1 passed; `UV_CACHE_DIR=/private/tmp/ai-video-tools-uv-cache make check` — 254 passed, 2 native-only tests skipped; Black, Pylint, and pycodestyle passed.
- Tall preview-column and final-output-preview validation: `UV_CACHE_DIR=/private/tmp/ai-video-tools-uv-cache uv run pytest tests/test_gui.py -q` — 39 passed; `UV_CACHE_DIR=/private/tmp/ai-video-tools-uv-cache uv run pytest tests/test_gui_submission.py -q` — 19 passed; `UV_CACHE_DIR=/private/tmp/ai-video-tools-uv-cache make check` — 256 passed, 2 native-only tests skipped; Black, Pylint, and pycodestyle passed. Offscreen editor and queue render captures were also inspected at 1400 × 880.
- Live-upscale-frame and looping-final-video validation: `UV_CACHE_DIR=/private/tmp/ai-video-tools-uv-cache uv run pytest tests/test_models.py tests/test_upscaling.py tests/test_gui.py -q` — 52 passed; `UV_CACHE_DIR=/private/tmp/ai-video-tools-uv-cache make check` — 258 passed, 2 native-only tests skipped; Black, Pylint, and pycodestyle passed.
- Last-frame wait-feedback validation: `UV_CACHE_DIR=/private/tmp/ai-video-tools-uv-cache uv run pytest tests/test_gui.py -q` — 39 passed.
- Source-row fullscreen activation validation: the focused fullscreen test uses
  a real mouse click on a shown row action. A native Cocoa reproduction exposed
  and verified the initialization-order fix: `dialog=True`, `visible=True`,
  `fullscreen=True`, and the active window was `fullscreenPreviewDialog`.
- Native fullscreen presentation, keyboard focus, display restoration, and shutdown inspection remain the one pending manual check on the supported macOS target; this environment cannot perform native screen inspection.
