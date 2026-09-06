# V2 Phase 5 — Fullscreen and Queue Preview

## Status

- State: Complete
- Predecessor: Phase 4

## Outcome

- Added borderless selected-source fullscreen using the existing player/video
  widget—never a proxy or second processing path.
- Final fullscreen controls are keyboard-only: `0`/`9`, `j`/`l`, `Space`/`k`,
  `Shift-P`/`Shift-N`, `Esc`, and `?`. One immutable registry drives dispatch,
  press/release consumption, accessible help, and synchronous requested state.
- Added a native-video-safe, non-activating shortcut-help panel.
- Reworked both workspaces around a tall far-right preview column.
- Added Queue Preview tabs for matched Original/Upscaled frame samples during
  upscaling and looping Final Video after publication. Typed progress carries
  optional sample paths; the pipeline never waits on presentation.
- Routed terminal Ctrl+C through normal cooperative GUI shutdown.

## Evidence

Focused fullscreen, keyboard, preview, lifecycle, frame-sampling, and layout
coverage passed. Final recorded `make check`: 258 passed with two native-only
checks skipped. Native visual acceptance continued in Phases 6–7.
