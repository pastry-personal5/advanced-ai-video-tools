# Version 2 Implementation Guide

## Purpose

This document defines how Codex and human contributors execute the v2 plan. Product scope lives in [plans.md](plans.md), detailed work lives in the active phase file, and implemented system contracts live in [../ARCHITECTURE.md](../ARCHITECTURE.md).

Read those documents in that order before changing v2 behavior.

## Source-of-truth order

When documents conflict, use this precedence:

1. The user's latest explicit design decision.
2. Repository-wide rules in [../../AGENTS.md](../../AGENTS.md).
3. Approved decisions and invariants in [plans.md](plans.md).
4. The active phase document.
5. Existing architecture and implementation behavior.

Update every affected lower-precedence document when a new decision intentionally changes it.

## Implementation workflow

1. Confirm that the requested work belongs to the active phase.
2. Inspect the current implementation, tests, callers, persisted formats, and user-visible documentation.
3. Resolve blocking design decisions before writing behavior-dependent code.
4. Convert the selected phase checklist item into a small vertical slice with an observable user outcome.
5. Keep backend media behavior outside PySide6 widgets and controllers.
6. Add tests at the lowest practical boundary, including failure and thread-affinity cases where relevant.
7. Run focused checks while iterating and `make check` before declaring the slice complete.
8. Update the active phase status, implementation evidence, architecture, README, and changelog as applicable.
9. Report what changed, checks actually run, remaining risks, and any manual verification still required.

## Change discipline

- Do not begin work from a broad phase heading alone; select an explicit checklist item and acceptance criterion.
- Keep one item in progress at a time unless independent work is deliberately parallelized.
- Avoid speculative abstractions for undecided rename or future-phase requirements.
- Centralize application identity before the rename, but do not choose or substitute a new name during Phase 1.
- Prefer typed state and explicit signals over widget inspection or loosely structured dictionaries.
- Keep long-running work off the Qt presentation thread.
- Freeze settings and job intent at the existing ownership boundaries so UI changes cannot mutate queued jobs.
- Preserve atomic persistence and publication semantics.
- Do not weaken validation to make a redesigned interface appear successful.

## Phase status vocabulary

- **Proposed:** listed in the roadmap but not approved for implementation.
- **Active planning:** decisions and acceptance criteria are being refined.
- **Ready:** scope is approved and no blocking design decision remains.
- **In progress:** implementation and tests are underway.
- **Verification:** implementation is complete and quality/manual checks are running.
- **Complete:** all completion gates passed and documents reflect reality.
- **Blocked:** progress requires an explicit decision or external dependency.

Use these exact terms in phase files and [plans.md](plans.md).

## Testing expectations

For GUI changes, cover as applicable:

- Typed view-model or controller behavior without a visible window.
- Qt signal delivery and GUI-thread mutation.
- Busy, empty, error, cancellation, and terminal states.
- Keyboard navigation, focus order, accessible names, and disabled-action behavior.
- Persistence success, failure, and migration behavior.
- Queue and job-request immutability across settings changes.
- Headless rendering interactions with `QT_QPA_PLATFORM=offscreen`.
- A focused manual check on the supported macOS target for behavior that offscreen tests cannot prove.

Tests must remain independent of a GPU, network, large model files, and long video by default. Hardware acceptance stays opt-in.

## Documentation expectations

- `plans.md` records roadmap status and cross-phase decisions.
- The active phase file records scope, checklist status, evidence, risks, and deferred work.
- `docs/ARCHITECTURE.md` describes only implemented or binding architecture.
- `README.md` describes released or verified user-facing behavior.
- `CHANGELOG.md` records notable completed changes under `Unreleased` until release.
- `AGENTS.md` contains durable repository rules, not temporary task notes.

## Definition of done for one implementation slice

- The user-visible outcome is complete rather than scaffolded.
- Public and cross-module interfaces are typed.
- Errors are actionable and detailed diagnostics remain available.
- No blocking operation was introduced on the GUI thread.
- Automated regression coverage exists where practical.
- Focused checks and the full affordable quality gate pass.
- Planning checkboxes and documentation match the delivered state.
- No unrelated user files or worktree changes were modified.

## V2 completion record

V2 Phases 1 through 7 are complete. Phase 7 verification and release
limitations are recorded in [7-stabilization-and-release.md](7-stabilization-and-release.md).
Current implementation work follows the approved v3 Phase 1 Refactoring plan
in [../v3/1-refactoring.md](../v3/1-refactoring.md).
