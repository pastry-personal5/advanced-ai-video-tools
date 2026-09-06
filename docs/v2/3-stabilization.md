# V2 Phase 3 — Stabilization

## Status

- State: Complete
- Predecessor: Phase 2

## Outcome

- Added deterministic coverage for startup/settings corruption, unsupported
  platforms, subprocess failure/timeout/output bounds, queue cancellation and
  shutdown, destination claims, cleanup, and GUI lifecycle paths.
- Verified one active FIFO job across ten sequential controlled jobs without
  invoking Real-ESRGAN or GPU enhancement.
- Established opt-in native presentation and screen-capture acceptance checks.
  These measure GUI presentation only and remain outside `make check`.
- Confirmed settings, logging, workspace, publication, no-network, and
  user-managed-tool contracts without changing media behavior.

## Evidence

Automated stabilization and the supported interactive Apple Silicon checks
completed. Performance involving AI upscaling remained deliberately excluded.
Detailed final measurements are retained in
[performance-history.md](performance-history.md).
