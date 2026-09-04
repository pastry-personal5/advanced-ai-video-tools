# V3 Phase 7 — Video Interpolation

## Status

- Phase: 7
- State: Proposed
- Predecessor: [Phase 6 — Crop Feature](6-crop.md)

## Objective

Add an explicit, opt-in video-interpolation path that can produce 30 fps or 60
fps output from a 16 fps source, with verified frame timing, audio behavior,
resource use, and cancellation.

## Design gates before implementation

- Define whether only exact 16 fps input is supported or whether other rates are
  normalized first; reject or explain unsupported rates explicitly.
- Select and validate the interpolation algorithm and user-managed tool/model
  ownership. Do not assume FFmpeg frame duplication is interpolation.
- Define 30 fps and 60 fps selection, generated-frame semantics, ordering with
  crop, concat, and upscale, and whether interpolation occurs once or per clip.
- Define exact rational timestamp construction, audio duration handling,
  variable-frame-rate policy, color/rotation policy, and output verification.
- Define progress cadence, cancellation boundaries, disk/memory limits, retry
  behavior, CLI/GUI controls, and preview expectations.

## Invariants

- Interpolation is never enabled implicitly and never inferred from preview
  playback speed.
- The requested output rate is frozen in the typed job request and rechecked by
  authoritative preflight and final verification.
- No duplicate upscale or hidden second concat is introduced; stage ordering is
  explicit and documented.
- Audio remains synchronized with the verified output timeline, and failures
  never replace an existing published output.

## Acceptance criteria

- 16 fps fixtures produce verified 30 fps and 60 fps outputs with exact rational
  timing within the approved tolerance.
- Unsupported source rates, missing tools/models, cancellation, partial output,
  and resource-limit failures are actionable and leave safe state.
- CLI, GUI, progress, messages, output naming, and documentation agree on the
  selected interpolation mode and target rate.
- Quality checks include frame-count/timestamp verification and a supported
  macOS playback review; `make check` passes without requiring GPU media in the
  default suite.

No interpolation implementation should begin until every design gate is
approved and Phase 6 is complete.
