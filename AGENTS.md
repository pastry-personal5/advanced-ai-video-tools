# Repository instructions

These rules apply to all work in this repository. Keep changes small, tested,
documented, and consistent with the implemented code.

## Read first

- [README.md](README.md): product scope, setup, and user-facing behavior
- [CONTRIBUTING.md](CONTRIBUTING.md): contributor workflow and media checklist
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md): agent-specific engineering rules
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): authoritative system and media contract

For version 2 work, read [the plan](docs/v2/plans.md), [the implementation
guide](docs/v2/implement.md), and [the active Phase 1 file](docs/v2/1-enhance-gui.md)
completely, in that order. Do not implement Phase 2 until Phase 1 is complete
or the user explicitly changes the order. Keep phase checklists and
implementation evidence truthful.

## Non-negotiable contracts

- Keep CLI and GUI thin over the same typed application service.
- Keep the pipeline **concat first, upscale at most once**; follow the complete
  stage contract in `docs/ARCHITECTURE.md`.
- Target macOS 26.5.2+ on Apple Silicon only; do not add unvalidated platforms.
- Keep FFmpeg, FFprobe, Real-ESRGAN, Vulkan, and model files user-managed.
- Keep long-running work off the GUI thread, run one queued job at a time, and
  make cancellation, cleanup, and progress explicit.
- Execute external tools with argument arrays and `shell=False`; never add
  application-initiated network activity.

## Working rules

For explain, review, diagnose, or plan requests, inspect and report without
editing unless a change is requested. For build, change, or fix requests, edit
within scope and validate without waiting for approval.

1. Inspect the affected implementation, callers, tests, and documentation.
2. Make the smallest complete vertical change; avoid speculative refactors.
3. Add regression coverage at the lowest practical layer.
4. Run focused checks, then `make check` when available and affordable.
5. Review the diff for unsafe behavior, debug output, generated files, and docs
   drift before reporting completion.

Preserve unrelated work. Do not commit credentials, personal paths, model
weights, generated media, caches, temporary frames, or local environment files.

## Handoff

Report the outcome, important design decisions, checks actually run, and any
remaining limitation or user action. Never describe planned or unverified work
as implemented.
