# Version 3 Plan

## Status

- Development target: v3
- Released baseline: v1.0.0
- Active implementation target: none; Phase 4 is the next proposed phase
- Last updated: 2026-09-03

V3 is sequenced after v2 release work. Its phases are deliberately separate so
refactoring can establish safe extension points before new media operations are
approved.

## Roadmap

| Phase | Title | Status | Outcome |
| --- | --- | --- | --- |
| 1 | [Refactoring](1-refactoring.md) | Complete | Improve maintainability and establish extension boundaries for Phase 6 Crop and Phase 7 Video Interpolation without changing media behavior |
| 2 | [Clip File Deletion Rules](2-deletion-rules.md) | Complete | Move configured same-directory related files to Trash after a successful GUI source move |
| 3 | [Focused Clip Dimensions](3-clip-resolution.md) | Complete | Probe the focused clip off-thread and show its coded dimensions beside the Output volume control without changing the clip list or Global Messages |
| 4 | [Modularity Refactoring](4-refactoring.md) | Proposed | Clarify module boundaries and improve modularity without changing behavior or public contracts |
| 6 | [Crop Feature](6-crop.md) | Proposed | Add an explicitly designed crop operation while preserving aspect-ratio and output-safety contracts |
| 7 | [Video Interpolation](7-video-interpolation.md) | Proposed | Design and add an opt-in path from 16 fps to 30 fps or 60 fps with verified timing and media-quality behavior |

Phase 1 through Phase 3 are complete. Phase 4 is the next proposed refactoring
phase and must preserve all implemented behavior. Phase 6 must complete before
Phase 7 begins. Phases 4, 6, and 7 remain proposed.

The canonical detailed Phase 1A plan is
[phase1-refactoring-plan.md](phase1-refactoring-plan.md).

## V3 invariants

- V2 behavior remains authoritative until a v3 phase explicitly changes an
  approved contract.
- Keep CLI and GUI thin over the same typed application service.
- Keep long-running work off the GUI thread and process one queued job at a
  time.
- Preserve shell-free external-tool execution, user-managed tools/models, no
  application-initiated network activity, atomic publication, cancellation,
  cleanup, and actionable diagnostics.
- Any crop or interpolation behavior must be explicit in the typed job request,
  preflight report, GUI, CLI, progress events, output verification, and docs;
  no hidden defaults or implicit media transformations are allowed.

## Phase completion protocol

A phase is complete only when its approved scope, tests, documentation, and
supported-macOS checks are complete and `make check` passes. Raw media,
benchmark output, model files, and local release artifacts stay outside the
repository.

## Decision log

| Date | Decision |
| --- | --- |
| 2026-08-31 | Establish v3 planning with Refactoring, Crop Feature, and Video Interpolation phases in that order; keep all three proposed and implementation-gated behind v2 release completion. |
| 2026-09-01 | Approve v3 Phase 1 implementation after v2 Phase 7 completion; activate Refactoring while keeping Crop and Video Interpolation proposed. |
| 2026-09-02 | Renumber Crop Feature to Phase 3 and Video Interpolation to Phase 4; preserve their dependency order and keep both proposed. |
| 2026-09-03 | Make API naming consistency the primary Phase 1A acceptance gate; designate the linked detailed plan as canonical. |
| 2026-09-03 | Record all Phase 1 implementation slices and automated checks complete; hold completion pending owner decision on native acceptance evidence. |
| 2026-09-03 | Owner approved Phase 1 completion and waived the three opt-in native acceptance checks as not applicable to the refactor-only scope. |
| 2026-09-03 | Move Crop Feature to Phase 6 and Video Interpolation to Phase 7; preserve their dependency order and keep both proposed. |
| 2026-09-03 | Approve and complete Phase 2: GUI-only configurable related-file deletion after successful source Trash moves. |
| 2026-09-03 | Record Phase 2 completion after source-aware custom templates, preferences coverage, and a passing full check; defer directory, confirmation, output-file, and additional-extension expansions. |
| 2026-09-03 | Revise proposed Phase 3 to show focused clip dimensions beside the Output volume label; keep dimensions out of source-list rows and Global Messages, preserve the volume-label width, and reduce slider allocation as needed. |
| 2026-09-03 | Complete Phase 3 after focused-first background probing, session caching, GUI settings invalidation, lifecycle coverage, and repository checks. |
| 2026-09-03 | Add proposed Phase 4 Modularity Refactoring to clarify module boundaries while preserving behavior and public contracts. |
