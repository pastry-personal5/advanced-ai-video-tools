# Version 3 Implementation Guide

V3 implementation is not authorized by this document. When a phase is
approved, follow this order:

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
  speculative abstractions.
- **Crop:** define crop coordinate units, validation, aspect-ratio policy,
  rotation/color ordering, CLI/GUI controls, and output verification before
  implementation.
- **Interpolation:** define the source-frame-rate contract, timing model,
  algorithm/tool ownership, audio/timestamp behavior, 30/60 fps selection,
  resource limits, cancellation, and quality verification before implementation.

V3 must not silently convert arbitrary frame rates, crop based on preview
geometry, or introduce an unvalidated external dependency.
