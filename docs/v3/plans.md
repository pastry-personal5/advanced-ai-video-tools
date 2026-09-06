# Version 3 Plan

## Status

- Released baseline: v2.0.0
- Active phase: None; [Phase 6 — Crop Feature](6-crop.md) remains proposed
- Last updated: 2026-09-06

V3 extends the completed v2 product without weakening its media or safety
contract.

## Roadmap

| Phase | Title | Status | Outcome |
| --- | --- | --- | --- |
| 1 | [Refactoring](1-refactoring.md) | Complete | Consistent APIs and typed extension boundaries |
| 2 | [Clip File Deletion Rules](2-deletion-rules.md) | Complete | Configurable GUI-only related-file Trash cleanup |
| 3 | [Focused Clip Dimensions](3-clip-resolution.md) | Complete | Background-probed focused-clip dimensions |
| 4 | [Modularity Refactoring](4-refactoring.md) | Complete | Verified dependency and ownership boundaries |
| 5 | [Unified Settings Dialog](5-settings-dialog.md) | Complete | Searchable, validated, atomic application settings |
| 6 | [Crop Feature](6-crop.md) | Proposed | Explicit crop intent with verified output safety |
| 7 | [Video Interpolation](7-video-interpolation.md) | Proposed | Opt-in 16 fps to 30/60 fps interpolation |

Phase 6 follows Phase 5. Phase 7 remains gated on Phase 6 and its own design
approval.

## Invariants

- Keep CLI and GUI thin over the same typed application service.
- Keep concat first and upscale at most once.
- Keep long-running work off the GUI thread and process one queued job at a
  time.
- Preserve shell-free external-tool execution, user-managed tools/models, no
  application network activity, atomic publication, cancellation, cleanup,
  and actionable diagnostics.
- Crop or interpolation must be explicit in typed requests, both frontends,
  preflight, progress, verification, and documentation.

## Completion rule

A phase is complete only after its approved behavior, tests, documentation,
supported-macOS evidence, and `make check` are complete. Generated media,
models, caches, and local artifacts remain outside the repository.

## Decision record

| Date | Decision |
| --- | --- |
| 2026-09-01 | Complete v2 and authorize V3 Phase 1. |
| 2026-09-03 | Complete Phases 1–3; reserve Phases 6 and 7 for Crop and Interpolation. |
| 2026-09-06 | Complete the Phase 4 dependency audit and authorize Phase 5. |
| 2026-09-06 | Approve a unified **Preferences → Settings** dialog with searchable tree navigation, an atomic shared draft, careful asynchronous validation, fixed dimension bounds, and session-only geometry. |
| 2026-09-06 | Complete Phase 5 with full automated checks and native Settings-dialog capture evidence. |
