# V3 Phase 1 — Refactoring

## Status

- Phase: 1
- State: Complete
- Predecessor: V2 release completion
- Successor: [Phase 6 — Crop Feature](6-crop.md)

## Objective

Make application API naming consistent first, then establish maintainability
and clear extension boundaries for future v3
features, specifically V3 Phase 6 Crop and V3 Phase 7 Video Interpolation,
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

## Approval record

The owner explicitly authorized v3 Phase 1 on 2026-09-01 after completion of
v2 Phase 7. Crop and video-interpolation implementation remain gated behind
this phase and are not authorized.

## Approval gates

Before each implementation slice, record the selected modules, public-
compatibility impact, and measurable completion criteria in this document.

The canonical detailed plan for Phase 1A is
[phase1-refactoring-plan.md](phase1-refactoring-plan.md).

### Phase 1A — Naming-first foundation

- Selected modules: `services.preflight`, `services.pipeline`,
  `services.queue`, the preparation/extraction/upscaling/finalization service
  executors, `services.progress`, the corresponding video/upscaling command
  builders, and the GUI editor/preflight/submission/tool-validation controller
  boundaries. In-repository callers and tests are part of the slice.
- Public-compatibility impact: the owner explicitly approved public API changes
  on 2026-09-02. The selected generic `run`, `execute`, `start`, and `build_*`
  entry points are replaced by descriptive verb-noun names without deprecated
  aliases. CLI flags, GUI behavior, media behavior, and persisted settings do
  not change.
- Measurable completion criteria: API naming consistency is complete before
  supporting work is accepted; every selected definition and caller uses the
  new name; all pipeline stages emit immutable progress through one shared
  helper; affected service boundaries translate only documented operational
  failures while preserving exception causes and diagnostic tails; focused
  tests and `make check` pass.

#### Phase 1A implementation evidence

- Completed on 2026-09-03. The selected service, command-builder, and GUI
  controller APIs now use descriptive verb-noun names with all CLI, queue, GUI,
  integration, and test callers migrated. No compatibility aliases remain.
- `run` remains only for Qt worker slots and the external-process runner
  protocol, where it is the established framework/adapter idiom; thread and
  timer `start` calls remain framework APIs rather than application entry
  points.
- `services.progress.ProgressEmitter` is the sole production constructor of
  `ProgressEvent`; preparation, extraction, upscaling, finalization, preflight,
  and pipeline cleanup all use it. Focused tests cover optional callbacks and
  paired preview paths.
- The affected application boundaries continue to catch targeted operational
  errors, chain the original cause, retain bounded process diagnostics, and
  preserve the existing cancellation/cleanup ownership rules. Regression tests
  assert cause and diagnostic-tail preservation for every processing executor.
- The ≥300-line readability inventory found no qualifying application-owned
  orchestration method after excluding Qt/framework overrides and constructors;
  no forced structural split was made.
- Validation: focused service/frontend suite — 172 passed; FFmpeg integration
  suite — 6 passed; `make lint` — Pylint 10.00/10 and pycodestyle passed;
  `make check` — 264 passed and 3 opt-in native acceptance tests skipped.
- The native performance and screen-capture targets were not run because this
  slice changes no presentation, platform, or subprocess behavior. They remain
  an overall Phase 1 completion requirement where applicable.

### Remaining Phase 1 gates

- **Phase 1B — Consolidation:** extract only evidence-backed shared stage and
  one-shot GUI worker lifecycle helpers; preserve typed signals and contracts;
  add before/after parity tests.
- **Phase 1C — Readability:** select complexity/coupling hotspots, add
  characterization tests, and split only targeted application-owned methods;
  exclude framework overrides and constructors without a demonstrated defect.
- **Phase 1D — Contracts:** define typed stage input/output/context protocols and
  conform existing stages without runtime registries, configuration-driven
  ordering, or user-facing crop/interpolation behavior.
- Complete Phase 1 only after all slices, documentation, applicable native
  evidence, and automated checks pass.

#### Phase 1B/1D implementation evidence

- Shared Qt worker completion cleanup and bounded shutdown now live in
  `gui.worker_lifecycle`; preflight and tool-validation workers retain their
  operation-specific signals and behavior.
- Stage boundary protocols now live in `services.contracts` and are consumed by
  `PipelineService`, providing a typed extension seam without runtime stage
  registration or configuration-driven ordering.
- `StageContext` carries the shared workspace, cancellation, progress, and
  toolchain dependencies through every stage while preserving the existing
  descriptive entry-point signatures.
- `make check` passes after these changes: 265 tests passed; the three opt-in
  native acceptance tests remain skipped because their required environment
  flag was not set.

#### Phase 1 completion status

All approved implementation slices and automated checks are complete. The owner
approved completion on 2026-09-03 and waived the three opt-in native acceptance
checks because this refactor changes no platform, presentation, or subprocess
behavior. Phase 1 is complete; Phase 6 Crop and Phase 7 Interpolation remain
gated behind their own design approvals.
