# Version 3 Plan

## Status

- Released baseline: v2.0.0
- Active phase: None; Phase 6 remains planned
- Last updated: 2026-10-17

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
| 6 | [Customizable Upscaling Pipelines](6-customizable-upscaling-pipelines.md) | Planned | User-selected concat, single-pass, and two-pass processing |
| 7 | [Color Tag Policy and Frame Inventory Robustness](7-color-tag-policy.md) | Complete | Explicit mixed-tag opt-in and decoded-frame authority |
| 8–10 | Unassigned | Unplanned | Scope and approval pending |
| 11 | [Crop Feature](11-crop.md) | Proposed | Explicit crop intent with verified output safety |
| 12 | [Video Interpolation](12-video-interpolation.md) | Proposed | Opt-in 16 fps to 30/60 fps interpolation |

Phase 11 follows completion of Phases 6–10 and its own design approval. Phase
12 remains gated on Phase 11 and its own design approval.

## Invariants

- Keep CLI and GUI thin over the same typed application service.
- Keep concat first. The implemented at-most-once upscale contract remains
  binding until Phase 6 is implemented and verified; Phase 6 plans an explicit
  two-pass option.
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
| 2026-10-01 | Move Crop to Phase 11 and Video Interpolation to Phase 12; leave Phases 6–10 unassigned. |
| 2026-10-11 | Record the Phase 6 customizable-upscaling design; implementation and acceptance evidence remain pending. |
| 2026-10-14 | Authorize Phase 7 before Phase 6 to resolve the mixed color-tag contract and decoded frame-inventory robustness. |
| 2026-10-14 | Complete Phase 7 with supported-macOS FFmpeg `f0`/`f1`/`f2` fixture evidence and `make check`. |
| 2026-10-17 | Tighten the Phase 6 design: retain nearest-even native dimensions, use a validated direct-inference pixel limit instead of undeclared tiling, and accept Spandrel `.safetensors` checkpoints only. Implementation remains unapproved. |
