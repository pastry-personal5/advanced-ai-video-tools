# V3 Phase 3 — Focused Clip Dimensions

## Status

- State: Complete
- Completed: 2026-09-03
- Predecessor: Phase 2
- Successor: Phase 4

## Outcome

The source preview shows the focused clip's coded `W×H` dimensions immediately
left of `Output volume`. Dimensions never enter source-list rows, Global
Messages, CLI output, preflight, or processing intent.

- A dedicated GUI worker performs filesystem inspection and FFprobe work away
  from the presentation thread.
- Focused clips have priority; idle work prewarms remaining clips in list order.
- Cache keys combine canonical path with device, inode, size, and nanosecond
  modification time where available. Successes and failures are cached; stale
  results are ignored and tool-setting changes invalidate affected entries.
- Dimensions use the first primary video's coded pixels without rotation or
  sample-aspect-ratio transformation.
- The Output volume label retains its width; the slider absorbs the additional
  compact label. Worker shutdown is joined.

## Evidence

- Controller, cache, stale-result, layout, settings-reconfiguration, media-case,
  and lifecycle coverage passed.
- `make check`: 281 passed, 3 opt-in native checks skipped.
- `git diff --check` passed; native capture was attempted but no Cocoa display
  was available in that execution environment.
