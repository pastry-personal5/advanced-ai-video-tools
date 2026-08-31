# Version 3 Plan

## Status

- Development target: v3 (future)
- Released baseline: v1.0.0
- Active implementation target: v2; v3 implementation is not authorized
- Last updated: 2026-08-31

V3 is sequenced after v2 release work. Its phases are deliberately separate so
refactoring can establish safe extension points before new media operations are
approved.

## Roadmap

| Phase | Title | Status | Outcome |
| --- | --- | --- | --- |
| 1 | [Refactoring](1-refactoring.md) | Proposed | Improve maintainability and establish extension boundaries for Phase 2 Crop and Phase 3 Video Interpolation without changing media behavior |
| 2 | [Crop Feature](2-crop.md) | Proposed | Add an explicitly designed crop operation while preserving aspect-ratio and output-safety contracts |
| 3 | [Video Interpolation](3-video-interpolation.md) | Proposed | Design and add an opt-in path from 16 fps to 30 fps or 60 fps with verified timing and media-quality behavior |

Phase 1 must complete before Phase 2 begins. Phase 2 must complete before
Phase 3 begins. No phase is approved for implementation by this planning set.

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
