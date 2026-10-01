# Version 3 Implementation Guide

Phases 1–5 are complete. Phases 6–10 are unassigned; Phases 11–12 remain
unauthorized.
For an authorized phase:

1. Read [plans.md](plans.md), the selected phase file, and
   [the architecture contract](../ARCHITECTURE.md).
2. Record approval and confirm the predecessor is complete.
3. Inspect affected models, services, frontends, persistence, tests, and docs.
4. Implement the smallest typed vertical slice; keep policy outside widgets.
5. Add focused success, failure, cancellation, lifecycle, and presentation
   coverage as applicable.
6. Run focused checks and `make check`; record only verified evidence.

## Remaining gates

- **Crop (Phase 11):** approve coordinates, validation, aspect ratio, operation
  order, rotation/color handling, controls, persistence, and verification.
- **Interpolation (Phase 12):** approve frame-rate/timing semantics, algorithm
  and tool ownership, audio, resource limits, cancellation, and quality gates.

No v3 phase may silently change frame rate, infer crop from preview geometry,
or introduce an unvalidated external dependency.
