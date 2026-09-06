# Contributing

Advanced AI Video Tools accepts focused, reviewable improvements. Most code may
be AI-assisted, but the person accepting it remains responsible for validation.
The project is proprietary; outside contributions require written confirmation
from the owner that their copyright and license terms are compatible with
[LICENSE](LICENSE).

## Before changing code

Read [README.md](README.md), [the architecture contract](docs/ARCHITECTURE.md),
[development practices](docs/DEVELOPMENT.md), and [AGENTS.md](AGENTS.md). Inspect
the repository before choosing a dependency, framework, entry point, or public
interface.

The supported product targets photographic/live-action footage on macOS 26.5.2+
Apple Silicon. Specialized animation/anime models and unvalidated platforms are
outside scope. External processing tools and models remain user-managed.

## Workflow

1. Define the observable outcome and acceptance criteria.
2. Inspect affected code, callers, tests, and documentation.
3. Implement the smallest complete change that preserves shared pipeline and
   safety contracts.
4. Add deterministic coverage without requiring GPU, network, large models, or
   long media by default.
5. Run focused checks and `make check`.
6. Review the complete diff for unsafe subprocess/path handling, lifecycle
   errors, debug output, accidental files, and documentation drift.

Use `uv add` for runtime dependencies and `uv add --dev` for development-only
dependencies; explain additions and commit `pyproject.toml` with `uv.lock`.

## Review and handoff

Reject fabricated APIs, silent fallbacks, broad error handling, unsafe paths,
unbounded retries, incomplete cancellation/cleanup, and code or assets with
unknown licenses. Verify external APIs against primary documentation.

Describe the outcome, key decisions, checks actually run, compatibility impact,
and remaining limitations. Do not commit secrets, personal paths, generated
media, model weights, caches, temporary frames, or local environment files.
