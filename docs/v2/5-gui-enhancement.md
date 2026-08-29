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
preview surface. A `Close fullscreen preview` button is positioned at the
top-right and follows the same hidden-by-default lifecycle as the other
fullscreen controls. The control bar is hidden during normal fullscreen
playback.
An unrecognized keyboard input briefly reveals the control bar and starts the
auto-hide timer; pointer movement and recognized shortcuts do not reveal it.
The view receives keyboard focus while it is open.

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

The help surface is a lightweight modal overlay or dialog titled
`Preview Keyboard Shortcuts`. It lists the exact bindings above, does not stop
or reset playback, and closes with `?`, `Esc`, or its close control. When help
is open, the first `Esc` closes help and leaves fullscreen preview open.

## Approved boundaries and invariants

- Preview remains playback-only; no trimming, filtering, frame export, concat-boundary editing, or output preview is added.
- Fullscreen mode previews only the currently selected local editor source.
- Entering fullscreen, leaving fullscreen, and using shortcuts cannot mutate ordered input paths or frozen job intent.
- Existing mute, volume, navigation, playback, seeking, error, pause-on-processing, and shutdown behavior remains authoritative.
- Preview failures remain non-blocking and retain the existing message: `Preview unavailable; preflight can still inspect this clip.`
- No FFmpeg, FFprobe, Real-ESRGAN, proxy media, or processing service is introduced into the fullscreen preview.
- Keyboard handling must work when the video surface or control bar has focus and must not depend on mouse focus after opening.
- One authoritative shortcut registry must drive both event resolution and help text so bindings cannot drift from documentation.
- Fullscreen key presses and releases must be consumed once inside the dialog boundary; modifier-only and auto-repeat events must not trigger commands, and focused controls must not double-activate.
- Fullscreen playback controls, including the top-right close button, remain hidden during normal use; unrecognized keyboard input briefly reveals them and then auto-hides them.
- Fullscreen cleanup must release dialog/widget ownership cleanly and must not create a second live player or orphan a native video output.
- The implementation remains within the supported macOS/PySide6 GUI target and does not add platform-specific unvalidated behavior.

## Work breakdown

### 1. Presentation design and state

- [x] Define both fullscreen entry points—the preview-pane expand button and the per-source-row `Start Fullscreen Preview` button—along with dialog flags, dark surface, sizing, and focus policy.
- [x] Define how the existing `QMediaPlayer`/`QVideoWidget` ownership and video output move between the pane and fullscreen surface.
- [x] Define the auto-hiding fullscreen control-bar layout, reveal triggers, accessible names, tooltips, disabled boundary states, and help-surface layout.
- [x] Define behavior for fullscreen entry, exit, help open/close, source selection, player error, processing start, and application shutdown.

### 2. Fullscreen implementation

- [x] Add the preview-pane expand control and a `Start Fullscreen Preview` action at the right of every source-clip list row.
- [x] Implement fullscreen entry and exit without creating proxy media or changing the selected source.
- [x] Preserve source, playback position, play/pause state, mute state, and volume across entry/exit wherever native Qt lifecycle permits.
- [x] Add fullscreen playback, seeking, first/last-frame, previous/next, and exit controls using the existing presentation boundary.
- [x] Add keyboard bindings for `0`, `9`, `j`, `l`, `Space`, `k`, `Shift-P`, `Shift-N`, `Esc`, and `?`.
- [x] Implement non-wrapping clip navigation with autoplay for `j`/`l` and immediate playback from the beginning for `Shift-P`/`Shift-N`.
- [x] Implement hidden-by-default controls that briefly reveal on unrecognized keyboard input and then auto-hide without hiding essential error/help states.
- [x] Implement the keyboard-help overlay and its focus/escape behavior.
- [x] Ensure fullscreen closes or safely exits before the main window releases preview resources.

### 3. Regression coverage

- [x] Test fullscreen entry and exit with no selected source, a valid source, and a preview-error source.
- [x] Test that source identity, ordered editor inputs, and built job requests remain unchanged.
- [x] Test all keyboard bindings, including physical `?`/`Shift+/` variants, `Shift-P`/`Shift-N`, clip-list boundaries, child-widget focus, key-release suppression, repeated key presses, and help toggling.
- [x] Test that `Esc` closes help before fullscreen and closes fullscreen afterward.
- [x] Test preservation of playback position and audio preferences across fullscreen transitions.
- [x] Test player/dialog cleanup during normal close, source changes, processing start, and main-window shutdown.
- [x] Test focus and accessible names for the fullscreen control bar and help surface with offscreen Qt fixtures where practical.

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
- The fullscreen video preserves aspect ratio and remains presentation-only.
- `0` seeks to the first frame and `9` seeks to the last frame.
- `j` and `l` navigate to adjacent clips without wrapping and autoplay the newly selected clip.
- `Space` and `k` play or pause the current clip.
- `Shift-P` and `Shift-N` navigate to the adjacent clip and begin playback from its start.
- `Esc` closes the help overlay first, then exits fullscreen preview.
- `?` opens and closes a help surface listing the exact keyboard bindings.
- The fullscreen playback controls, including the top-right close button, are hidden during normal use and remain accessible when temporarily revealed.
- An unrecognized keyboard input reveals the control bar temporarily; it then auto-hides.
- Fullscreen transitions do not alter clip order, job intent, preflight results, or processing behavior.
- Preview errors remain non-blocking and do not create proxy media.
- Fullscreen and help surfaces clean up correctly on exit, source changes, processing start, and application shutdown.
- Focused GUI tests and the full quality gate pass, with supported-macOS manual verification recorded.

## Out of scope

- Previewing completed outputs, queued-job media, merged intermediates, or simulated processed output.
- Trim points, timeline editing, filters, frame export, concat-boundary editing, and loop controls.
- New media codecs, rotation handling, color handling, HDR handling, or processing-pipeline changes.
- FFmpeg-generated preview proxies or Real-ESRGAN execution.
- Persisting fullscreen state, keyboard-help visibility, or new user preferences.
- Global application keyboard shortcuts outside the focused fullscreen preview.

## Implementation evidence

### Fullscreen preview slice — completed

- Added the preview-pane expand button and per-source-row `Start Fullscreen Preview` action.
- Reused the existing `QMediaPlayer` and `QVideoWidget` by moving the video widget into a borderless fullscreen dialog; no second player or proxy media is created.
- Added hidden-by-default fullscreen playback/seeking controls, approved keyboard shortcuts, the `Preview Keyboard Shortcuts` help panel, non-wrapping autoplay navigation, and invalid-input auto-hide feedback.
- Consolidated keyboard handling into one immutable binding registry and one dialog-scoped dispatcher; help is generated from the registry, key releases cannot activate focused controls a second time, and rapid playback toggles use synchronous requested state.
- Preserved presentation-only behavior, ordered input intent, player error handling, processing pause, and shutdown cleanup.
- Focused validation: `UV_CACHE_DIR=/private/tmp/ai-video-tools-uv-cache uv run pytest tests/test_gui.py -q` — 37 passed.
- Full validation: `UV_CACHE_DIR=/private/tmp/ai-video-tools-uv-cache make check` — 253 passed, 2 native-only tests skipped; Black, Pylint, and pycodestyle passed.
- Native fullscreen presentation, keyboard focus, display restoration, and shutdown inspection remain the one pending manual check on the supported macOS target; this environment cannot perform native screen inspection.
