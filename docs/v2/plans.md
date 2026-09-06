# Version 2 Plan

## Completion

V2 Phases 1–7 are complete and version 2.0.0 is the released baseline. The
verified artifact is an unsigned development DMG; Developer ID signing and
notarization remain deferred.

| Phase | Outcome |
| --- | --- |
| 1 | [Dark two-workspace GUI, selected-source preview, messages, and native interactions](1-enhance-gui.md) |
| 2 | [Advanced AI Video Tools identity and guarded v1 migration](2-rename-project.md) |
| 3 | [Failure-path, native-presentation, capture, and queue stability](3-stabilization.md) |
| 4 | [Focused service, settings, queue, and GUI boundary refactoring](4-refactoring.md) |
| 5 | [Keyboard-only fullscreen and three-tab Queue Preview](5-gui-enhancement.md) |
| 6 | [Active, Up Next, and History queue information architecture](6-information-architecture-gui.md) |
| 7 | [Release verification, performance evidence, and development DMG](7-stabilization-and-release.md) |

## Final decisions

- Preserve concat-first/upscale-at-most-once processing, typed frontend-neutral
  services, one FIFO worker, explicit cancellation/cleanup, atomic publication,
  user-managed tools/models, and no application network activity.
- Support macOS 26.5.2+ on Apple Silicon and photographic/live-action SDR media.
- Use `Advanced AI Video Tools`, distribution `advanced-ai-video-tools`, package
  `advanced_ai_video_tools`, and bundle ID
  `com.pastrypersonal5.advancedaivideotools`; retain `ai-video-tools` as a v2
  warning compatibility alias and the `ai-` output prefix.
- Distribute outside the Mac App Store. The v2 artifact is unsigned/ad-hoc
  signed because Apple Developer Program enrollment is unavailable.
- Keep preview and queue enhancements presentation-only; frozen requests and
  backend media policy remain authoritative.

Detailed migration, performance, and release records remain in
[rename-migration.md](rename-migration.md),
[performance-history.md](performance-history.md), and
[release-notes-v2.0.0.md](release-notes-v2.0.0.md).
