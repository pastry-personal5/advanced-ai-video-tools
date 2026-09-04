# Version 3 Implementation Guide

V3 Phase 1, Phase 2, and Phase 3 implementation are complete. Phase 4, Phase
6, and Phase 7 implementation remain unauthorized. For an authorized phase,
follow this order:

1. Read [plans.md](plans.md), the selected phase file, and the v2 architecture
   and implementation rules.
2. Confirm the phase predecessor is complete and record the owner's explicit
   approval in the phase file.
3. Inspect affected models, services, CLI/GUI callers, persistence, tests, and
   documentation before editing.
4. Implement one typed vertical slice at a time; keep media decisions in the
   application service rather than in Qt widgets.
5. Add regression coverage for success, failure, cancellation, progress,
   output verification, and GUI state where applicable.
6. Run focused checks and `make check`, then update architecture, README,
   changelog, and phase evidence only for verified behavior.

## Phase-specific gates

- **Refactoring:** preserve public behavior and media contracts; avoid
  speculative abstractions. Complete the naming-first Phase 1A gate, then
  execute the staged 1B consolidation, 1C readability, and 1D typed-contract
   gates recorded in the active phase file.
- **Deletion rules (Phase 2):** keep the feature GUI-only and best-effort after
  successful source Trash moves. Match only validated, case-insensitive
  immediate-directory basenames and preserve schema migration diagnostics.
- **Focused clip dimensions (Phase 3):** keep dimensions out of source-list rows
  and Global Messages. Probe off the GUI thread with focused-clip priority,
  cache by canonical path and file version, suppress stale results, and shut
  down the worker cleanly. Place the focused dimension text immediately left of
  the existing Output volume label; preserve that label's width and let the
  slider absorb the reduced horizontal space.
- **Modularity refactoring (Phase 4):** establish a dependency inventory and
  explicit ownership boundaries before editing; keep core/media independent of
  Qt widgets, preserve public behavior and media contracts, and require
  characterization plus boundary tests for each bounded slice.
- **Crop (Phase 6):** define crop coordinate units, validation, aspect-ratio policy,
  rotation/color ordering, CLI/GUI controls, and output verification before
  implementation.
- **Interpolation (Phase 7):** define the source-frame-rate contract, timing model,
  algorithm/tool ownership, audio/timestamp behavior, 30/60 fps selection,
  resource limits, cancellation, and quality verification before implementation.

V3 must not silently convert arbitrary frame rates, crop based on preview
geometry, or introduce an unvalidated external dependency.
