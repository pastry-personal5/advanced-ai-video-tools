# V2 Phase 7 — Stabilization and Release

## Status

- State: Complete
- Completed: 2026-09-01
- Predecessors: Phases 1–6

## Outcome

Reverified v2 behavior, recorded repeatable GUI-only performance evidence,
completed supported-macOS acceptance, and produced the unsigned development DMG
released as v2.0.0. Performance tests never invoke Real-ESRGAN, Vulkan
inference, model loading, or media upscaling.

The DMG uses the GUI-only PyInstaller entry point, correct bundle identity and
minimum macOS target, Finder-compatible Homebrew/MacPorts discovery, and no
bundled external tools. Production Developer ID signing, notarization, stapling,
and quarantined Gatekeeper validation remain deferred because Apple Developer
Program enrollment is unavailable.

## Verification

- `make check`: 262 passed, 3 opt-in native checks skipped.
- `make gui-capture-test`: 2 passed, 1 deselected on the supported desktop.
- `make performance-test`: accepted 15-sample runs with p95 values well below
  the 3-second presentation budget; see
  [performance-history.md](performance-history.md).
- Finder launch, settings, queue lifecycle, logs, and development-DMG clean
  installation were manually verified.
- A separate `uv build` attempt was blocked by unavailable PyPI DNS and wrote no
  repository artifact; earlier v2 wheel/sdist metadata had already been
  inspected in Phase 2.

Run native checks only from an unlocked interactive Mac with Screen Recording
permission for the invoking terminal. These presentation checks do not replace
real user-managed-tool pipeline validation.
