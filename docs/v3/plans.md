# Version 3 Plan

## Status

- Released baseline: v2.0.0
- Active phase: None (Phase 6 completed 2026-10-17; Phases 8–10 unassigned; Phases 11–12 design-gated)
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
| 6 | [Customizable Upscaling Pipelines](6-customizable-upscaling-pipelines.md) | Complete | User-selected concat, single-pass, and two-pass processing |
| 7 | [Color Tag Policy and Frame Inventory Robustness](7-color-tag-policy.md) | Complete | Explicit mixed-tag opt-in and decoded-frame authority |
| 8–10 | Unassigned | Unplanned | Scope and approval pending |
| 11 | [Crop Feature](11-crop.md) | Proposed | Explicit crop intent with verified output safety |
| 12 | [Video Interpolation](12-video-interpolation.md) | Proposed | Opt-in 16 fps to 30/60 fps interpolation |

Phase 11 follows completion of Phases 6–10 and its own design approval. Phase
12 remains gated on Phase 11 and its own design approval.

## Invariants

- Keep CLI and GUI thin over the same typed application service.
- Keep concat first and upscale at most once, except for the explicit 2× → 3×
  two-pass pipeline that Phase 6 implemented and verified.
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
| 2026-10-17 | Authorize Phase 6 implementation. `tools/spandrel-runner` is the Phase 6 protocol-1 runner; no second runner is built. Phase 6 stays In progress until supported-macOS native acceptance and `make check` are recorded. |
| 2026-10-17 | Publish 640×360 as the Phase 6 runner's maximum input size, the only size run on both supplied DAT models. Phase 6 stays In progress pending a consolidated native re-run. |
| 2026-10-17 | At the user's direction, allow `.pth` checkpoints (loaded only through Spandrel's restricted unpickler; `.pt`, `.ckpt`, and other formats stay rejected) and select `2xPublic_realplksr_dysample_layernorm_real_nn.pth` for 2× and `DAT_x3_bf16.safetensors` for 3×. `4xNomos2_hq_dat2.safetensors` (native 4×) is not used. This reverses the checkpoint-trust decision above. Neither selected checkpoint has been run on MPS. |
| 2026-10-17 | At the user's direction, the Phase 6 runner may run bfloat16 models: an all-bfloat16 checkpoint runs in bfloat16 on MPS, any other runs in float32 (never float16), published as `precision` and validated by the application; runner 0.5.0. bfloat16 inference on MPS has not been run. |
| 2026-10-17 | At the user's direction, record the factory-default tool–model pair for now: 2× `tools/spandrel-runner/spandrel-runner` with `2xPublic_realplksr_dysample_layernorm_real_nn.pth` (PLKSR, float32), 3× the same runner with `DAT_x3_bf16.safetensors` (DAT, bfloat16), and 4× `realesrgan-ncnn-vulkan` with `realesrgan-x4plus`. The runner is to be used only at that path, never found through `PATH`. Documentation only: the application ships no default runner or model path and still looks an unset runner up on `PATH`; applying the defaults is a separate code change that has not been approved. |
| 2026-10-17 | A 4-frame, 96×72 CLI smoke run of the selected pair exited 0 on MPS (2× float32, 3× bfloat16) and on Vulkan (4×). It is the first recorded bfloat16 inference on MPS. The 640×360 run and the consolidated native re-run remain owed, so Phase 6 stays In progress. |
| 2026-10-17 | At the user's direction, include factory-default resolution in Phase 6: an unset Spandrel runner or 2×/3× model resolves to the checkout's `tools/spandrel-runner/spandrel-runner` and the default checkpoints beside it, never through `PATH`; configured paths win; the CLI help, Settings placeholders, and a **Use default** runner button disclose it. This supersedes the documentation-only entry above. Test-first coverage, plus an end-to-end CLI native 2× and 3× run from outside the repository with no runner or model flags, are recorded in the Phase 6 evidence. |
| 2026-10-17 | Complete Phase 6 with recorded evidence: `make check` (Black, Pylint 10.00/10, pycodestyle, 412 passed and 13 skipped), the runner suite (32 passed), `git diff --check`, the consolidated `make phase6-native-test` (9 passed) on the selected checkpoints, and one 640×360 frame through each selected checkpoint on MPS. The published 230,400-pixel limit is unchanged. Native GUI capture was not run, at the user's direction. |
