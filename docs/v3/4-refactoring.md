# V3 Phase 4 — Modularity Refactoring

## Status

- Phase: 4
- State: Proposed
- Predecessor: Phase 3 — Focused Clip Dimensions (complete)
- Successors: Phase 6 — Crop Feature and Phase 7 — Video Interpolation

## Objective

Improve modularity by clarifying ownership and dependency direction between
domain models, media probing, processing services, GUI controllers, and Qt
presentation code. The result should make future feature work possible within
small, independently testable modules while preserving all approved behavior.

## Scope

- Inventory current module responsibilities, import dependencies, public
  entry points, and lifecycle ownership across `core`, `video`, `services`,
  `system`, and `gui`.
- Extract or reorganize code only where a concrete boundary problem is shown:
  oversized mixed-responsibility modules, presentation code owning domain
  decisions, duplicated adapters, or dependency cycles.
- Keep media probing, command construction, execution, validation, cache
  policy, and result interpretation behind typed, independently testable
  boundaries.
- Keep GUI modules limited to presentation state, Qt signal/slot wiring, and
  user interaction; keep application and media policy outside Qt widgets.
- Make worker ownership, cancellation, shutdown, and thread-affinity rules
  explicit for every asynchronous GUI and service boundary.
- Add characterization and contract tests before moving behavior, then add
  focused tests for each new module boundary and failure path.
- Document stable ownership and dependency rules in the architecture and
  development guidance where the implemented structure changes.

## Non-goals

- No crop or interpolation behavior, new media transformation, codec, or
  external dependency.
- No CLI flag, GUI behavior, persisted-settings schema, queue semantics,
  subprocess policy, or public compatibility change unless separately
  approved as a correction.
- No generic plugin framework, runtime module registry, speculative
  abstraction, or broad rewrite without evidence from the dependency audit.
- No movement of long-running filesystem, process, media, or inference work
  onto the GUI thread.

## Design constraints

- Dependency direction should point from presentation adapters toward typed
  application/domain boundaries; core and media modules must not import Qt
  widgets or GUI modules.
- External tools remain user-managed and are invoked with argument arrays and
  `shell=False`; the refactor must not add network activity.
- The concat-first/upscale-at-most-once pipeline, timing/color/audio policy,
  cancellation, cleanup, atomic publication, and diagnostic contracts remain
  unchanged.
- New boundaries must have one clear owner for mutable state and one explicit
  shutdown path; avoid hidden global state and implicit worker lifetime.

## Acceptance criteria

- The dependency audit identifies the selected refactoring slices and records
  their before/after ownership and public-compatibility impact in this file.
- Core, media, and application policy modules have no dependency on Qt
  presentation widgets; GUI presentation consumes typed values/signals through
  explicit adapters.
- Each selected boundary has focused success, failure, cancellation, and
  lifecycle coverage appropriate to its responsibility.
- Existing CLI/GUI behavior, media outputs, queue behavior, settings
  persistence, and safety contracts remain unchanged.
- `make check`, `git diff --check`, and all applicable supported-macOS checks
  pass. Native checks are recorded as skipped only with their actual reason.

## Approval record

Phase 4 is proposed only. Implementation requires explicit owner approval after
the dependency audit identifies a concrete, bounded first slice. Phase 6 and
Phase 7 remain gated behind their own design and approval records.

## Suggested implementation slices

1. Dependency and ownership inventory with characterization tests; no runtime
   changes.
2. Extract one evidence-backed boundary at a time, starting with the highest
   coupling hotspot and preserving compatibility at every seam.
3. Move GUI-only adapters away from domain/media modules and verify thread and
   shutdown ownership.
4. Consolidate duplicated typed contracts and update architecture evidence.
5. Run focused checks, the full repository checks, and applicable native
   acceptance before considering the phase complete.
