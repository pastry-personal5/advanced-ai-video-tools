# V3 Phase 1 — Refactoring

## Status

- Phase: 1
- State: Proposed
- Predecessor: V2 release completion
- Successor: [Phase 2 — Crop Feature](2-crop.md)

## Objective

Improve maintainability and establish clear extension boundaries for future v3
features, specifically V3 Phase 2 Crop and V3 Phase 3 Video Interpolation,
without changing current user-visible behavior, media policy, queue semantics,
or output contracts.

## Scope

- Consolidate duplicated model, service, command-construction, and GUI mapping
  logic where the existing behavior is already approved.
- Clarify typed boundaries for job options, stage progress, media timing,
  validation, output verification, and presentation state.
- Make pipeline stages and lifecycle ownership easier to extend without moving
  processing into the GUI thread.
- Strengthen focused regression and failure-path coverage before feature work.

## Non-goals

- No crop controls, interpolation algorithm, new codec, or new media default.
- No public CLI behavior change unless separately approved as a compatibility
  correction.
- No speculative plugin framework or unvalidated third-party dependency.

## Acceptance criteria

- Existing v2 tests and user-visible behavior remain green.
- Refactoring leaves concat-first/upscale-at-most-once, timing, color/audio,
  queue, cancellation, cleanup, and publication contracts unchanged.
- New extension boundaries are typed, documented, and covered by regression
  tests.
- `make check` and required supported-macOS checks pass.

## Approval gates

Approve the target module slices, public-compatibility policy, and measurable
completion criteria before implementation.
