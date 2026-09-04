# V3 Phase 1A — Naming-First Refactoring Plan

## Status and priority

Phase 1A is the naming-consistency foundation of v3 Phase 1. API naming is the
primary deliverable; progress and error-boundary work is limited to the
selected boundaries needed to make that refactor safe and observable.

The current implementation WIP is the baseline. Public application APIs may
change, and the owner approved the breaking renames on 2026-09-02. Deprecated
aliases are intentionally not provided.

## Approved API vocabulary

| Area | Required form | Examples |
| --- | --- | --- |
| Pipeline and stage operations | `execute_<noun>` | `execute_pipeline`, `execute_preflight`, `execute_extraction` |
| Commands, plans, and requests | `create_<noun>` | `create_concat_command`, `create_upscale_plan`, `create_job_request` |
| GUI lifecycle actions | `begin_<noun>` | `begin_preview`, `begin_validation`, `begin_submission` |

### Breaking rename table

| Previous entry point | New entry point |
| --- | --- |
| `PipelineService.run` | `PipelineService.execute_pipeline` |
| `PreflightService.run` | `PreflightService.execute_preflight` |
| Stage executor `execute` methods | `execute_preparation`, `execute_preparation_in_workspace`, `execute_extraction`, `execute_upscaling`, `execute_finalization` |
| `build_normalization_command` | `create_normalization_command` |
| `build_concat_command` | `create_concat_command` |
| `build_media_preparation_plan` | `create_media_preparation_plan` |
| `build_frame_extraction_command` | `create_frame_extraction_command` |
| `build_frame_extraction_plan` | `create_frame_extraction_plan` |
| `build_final_encoding_plan` | `create_final_encoding_plan` |
| `build_upscale_plan` | `create_upscale_plan` |
| `build_realesrgan_command` | `create_realesrgan_command` |
| `build_ffprobe_command` | `create_ffprobe_command` |
| `GuiPreflightController.start` | `GuiPreflightController.begin_preview` |
| `ToolSettingsValidator.start` | `ToolSettingsValidator.begin_validation` |
| `JobSubmissionController.start` | `JobSubmissionController.begin_submission` |
| `EditorController.build_request` | `EditorController.create_job_request` |

Migrate every selected definition, in-repository caller, test double, and
documentation reference. Remove the selected generic `run`, `execute`,
`start`, and `build_*` application entry points. Retain `run`/`start` only for
framework or adapter protocols (for example Qt worker slots, QThread/timer
methods, and the external-process runner), and document those exceptions.

The migration note must list each breaking rename and state that no aliases are
available. CLI flags, GUI behavior, persisted settings, media behavior, queue
semantics, and output contracts remain unchanged.

## Supporting boundaries

- `services.progress.ProgressEmitter` is the sole production constructor of
  immutable `ProgressEvent` values, including optional paired preview paths.
- Each affected service boundary has an explicit exception matrix: translate
  only documented operational failures, chain causes with `raise ... from ...`,
  preserve bounded process diagnostic tails, and keep cancellation/cleanup
  ownership unchanged.
- Inventory application-owned methods at or above 300 lines after the naming
  migration. Split qualifying orchestration methods only; exclude Qt/framework
  overrides and constructors, and do not force a split when no qualifying
  method exists.
- Executor/worker base classes, registries, orchestrators, and other broad
  abstractions remain outside Phase 1A.

## Verification and completion

- Static search confirms all selected APIs use the approved vocabulary and no
  deprecated aliases or stale alternatives remain.
- Regression tests cover renamed calls, progress callback behavior and event
  fields, exception translation/cause/diagnostic tails, cancellation, cleanup,
  and any qualifying method split.
- Run focused tests, `make lint`, `make check`, and `git diff --check`.
- Native performance and screen-capture checks are slice-waived because this
  work changes no platform, presentation, or subprocess behavior; retain them
  as applicable overall Phase 1 gates.

## Documentation ownership

This file is the canonical detailed Phase 1A plan. Link it from the v3 roadmap
and active Phase 1 file. Keep Phase 6 Crop and Phase 7 Video Interpolation
sequencing intact; neither feature is authorized by this plan.

## Remaining Phase 1 slices

### Phase 1B — Evidence-driven consolidation

- Compare stage executors and extract only proven duplicated workspace,
  diagnostics, cancellation, or lifecycle logic into small typed helpers.
- Share one-shot Qt worker thread setup/cleanup between diagnostic preflight and
  tool validation while retaining operation-specific workers and signals.
- Add characterization and parity tests before and after each extraction.
- Do not introduce generic executor/orchestrator frameworks without evidence.

### Phase 1C — Readability and testability

- Select hotspots from complexity, coupling, and duplication review rather than
  a mechanical line-count threshold.
- Add characterization tests before structural splits; improve local names,
  annotations, docstrings, dependency injection, and helper boundaries only
  where they improve isolated testing or clarify ownership.
- Exclude Qt/framework overrides and constructors unless a concrete defect is
  demonstrated.

### Phase 1D — Typed extension contracts

- Define typed protocols/data contracts for stage inputs, outputs, execution
  context, progress, cancellation, verification, and failure reporting.
- Make current stages conform without changing ordering or adding user-selectable
  stages. Keep concat-first and upscale-at-most-once explicit.
- Do not add a runtime registry, configuration-driven ordering, CLI flags, GUI
  controls, crop behavior, or interpolation behavior.

Each slice requires focused regression coverage, documentation evidence, and a
passing `make check`. Public API changes remain allowed when justified, with a
migration note and complete in-repository caller migration.

### Current implementation evidence

- Phase 1A naming, progress, and error-boundary work is complete.
- Phase 1B shared worker lifecycle cleanup is complete; stage executor
  consolidation remains intentionally limited because no additional duplicated
  contract-safe helper was demonstrated.
- Phase 1C review completed with no targeted structural split justified after
  excluding framework-heavy constructors/overrides; existing local naming and
  testability improvements are retained.
- Phase 1D typed stage contracts are complete in `services.contracts`; runtime
  registries and configuration-driven ordering were not introduced.
- `StageContext` is immutable and carries workspace, cancellation, progress, and
  toolchain dependencies through the existing stage entry points.
- `make check`: 265 passed, 3 opt-in native acceptance tests skipped.

*Document version: 2.0*  
*Last updated: 2026-09-03*
