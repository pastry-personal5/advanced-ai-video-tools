# V3 Phase 3 — Crop Feature

## Status

- Phase: 3
- State: Proposed
- Predecessor: [Phase 1 — Refactoring](1-refactoring.md)
- Successor: [Phase 4 — Video Interpolation](4-video-interpolation.md)

## Objective

Add an explicit, user-controlled crop feature to the shared typed pipeline and
both supported frontends, with deterministic validation and output verification.

## Design gates before implementation

- Define crop coordinates and units, including how values map to source pixels
  across differing resolutions and display scaling.
- Decide whether crop is a fixed rectangle, aspect-ratio-constrained region,
  or both; define minimum dimensions and even-dimension requirements.
- Define operation ordering relative to normalization, concat, frame extraction,
  upscaling, and encoding.
- Define rotation, color metadata, HDR rejection, audio, and timing behavior.
- Define CLI syntax, GUI controls, persistence policy, preview representation,
  progress, cancellation, and actionable validation errors.

## Invariants

- Cropping is never implicit and never inferred from a preview widget's size.
- The typed job request and authoritative preflight contain the exact crop
  intent; GUI selection cannot change a queued job.
- Output dimensions, timestamps, color policy, audio policy, and atomic
  publication remain verified by the backend.

## Acceptance criteria

- Valid and invalid crop rectangles are covered at the model, preflight,
  command, pipeline, CLI, GUI, cancellation, and publication boundaries.
- The crop is represented consistently in job messages and diagnostics without
  exposing raw command lines.
- Existing jobs with no crop preserve v2 behavior byte-for-byte where the
  existing contract permits and semantically otherwise.
- `make check` and supported-macOS manual GUI verification pass.

No crop implementation should begin until the design gates are approved.
