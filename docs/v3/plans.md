# Version 3 Plan

## Status

- Development target: v3
- Released baseline: v1.0.0
- Active implementation target: v3 Phase 1 — Refactoring
- Last updated: 2026-09-03

V3 is sequenced after v2 release work. Its phases are deliberately separate so
refactoring can establish safe extension points before new media operations are
approved.

## Roadmap

| Phase | Title | Status | Outcome |
| --- | --- | --- | --- |
| 1 | [Refactoring](1-refactoring.md) | Complete | Improve maintainability and establish extension boundaries for Phase 3 Crop and Phase 4 Video Interpolation without changing media behavior |
| 3 | [Crop Feature](3-crop.md) | Proposed | Add an explicitly designed crop operation while preserving aspect-ratio and output-safety contracts |
| 4 | [Video Interpolation](4-video-interpolation.md) | Proposed | Design and add an opt-in path from 16 fps to 30 fps or 60 fps with verified timing and media-quality behavior |

Phase 1 is complete. Phase 3 must complete before
Phase 4 begins. Only Phase 1 is approved for implementation; Phases 3 and 4
remain proposed.

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
