# Repository instructions

Keep changes small, tested, documented, and consistent with implemented code.

## Read first

- [README.md](README.md): product scope and current status
- [CONTRIBUTING.md](CONTRIBUTING.md): contributor workflow
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md): engineering rules
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): authoritative runtime/media contract

For v3 work, read [the roadmap](docs/v3/plans.md),
[implementation guide](docs/v3/implement.md), and selected phase file. Do not
start a proposed phase without explicit user approval or before its predecessor
is complete. Keep status and evidence truthful.

## Contracts

- Keep CLI and GUI thin over the same typed application service.
- Keep concat first and upscale at most once; follow the architecture stages.
- Support macOS 26.5.2+ on Apple Silicon only.
- Keep FFmpeg, FFprobe, Real-ESRGAN, Vulkan, and models user-managed.
- Keep long work off the GUI thread; run one queued job at a time with explicit
  progress, cancellation, cleanup, and worker shutdown.
- Execute argument arrays with `shell=False`; add no application network access.

## Work

For reviews and plans, inspect without editing unless a change is requested.
For requested changes:

1. Inspect implementation, callers, tests, and affected docs.
2. Make the smallest complete vertical change and preserve unrelated work.
3. Add regression coverage at the lowest practical layer.
4. Run focused checks, then `make check` when available.
5. Review the diff for unsafe behavior, debug/generated files, and docs drift.

Never commit credentials, personal paths, model weights, generated media,
caches, temporary frames, or local environment files.

## Handoff

Report the outcome, design decisions, checks actually run, and remaining user
action or limitations. Never describe planned or unverified work as complete.
