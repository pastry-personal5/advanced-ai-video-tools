# Contributing

Advanced AI Video Tools welcomes focused, reviewable improvements. Most code is expected to be AI-generated or AI-assisted, but the person accepting a change remains responsible for understanding and validating it.

The project is proprietary and all rights are reserved by Pastry Personal 5. Do not accept outside contributions unless the owner has confirmed in writing that the contribution's copyright and licensing terms are compatible with [LICENSE](LICENSE).

Version 1 targets photographic and live-action footage. Anime, animation, illustration, synthetic line art, and their specialized Real-ESRGAN models are out of scope.

## Before you start

Read:

- [README.md](README.md) for product scope and intended commands
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the processing pipeline and system boundaries
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for detailed engineering and runtime practices
- [AGENTS.md](AGENTS.md) for repository-wide implementation rules

Check the repository before choosing a framework, dependency, entry point, or command. The typed core, preflight and processing CLI commands, compatibility analysis, safe media command builders, owned-workspace manager, cancellable process runner, composable preparation/extraction/upscaling/finalization services, strict Real-ESRGAN adapter, output verification, atomic publisher, full-job orchestration, single-worker FIFO queue, PySide6 queue shell, reviewed GUI job-submission workflow, and asynchronously validated external-tool settings editor exist.

## Development environment

The project uses:

- macOS 26.5.2 or later on Apple Silicon as the v1 target; Apple M5 Max with 128 GB unified memory is the reference machine
- Python 3.10 or newer
- PySide6 as the GUI framework
- Loguru as the application logging API
- `uv` for environments, dependencies, and command execution
- Black for formatting
- Pylint and pycodestyle for linting
- A `Makefile` as the canonical developer interface
- FFmpeg, FFprobe, and `realesrgan-ncnn-vulkan` as external processing tools

Install FFmpeg, FFprobe, `realesrgan-ncnn-vulkan`, its model files, and working Vulkan support separately. The project does not bundle or automatically download them. Contributors may configure explicit executable paths or make the tools available on `PATH`.

Install development dependencies with:

```bash
make install
```

Use `uv add <package>` for runtime dependencies and `uv add --dev <package>` for development-only dependencies. Explain new dependencies in the change description and commit the resulting `pyproject.toml` and `uv.lock` updates together.

## Making a change

1. Define the user-visible outcome and acceptance criteria.
2. Inspect the affected code, callers, tests, and documentation.
3. Implement the smallest complete change that respects the shared pipeline architecture.
4. Add or update tests at the lowest practical layer.
5. Run targeted checks while iterating, followed by `make check` when available.
6. Review the complete diff for accidental files, debug output, unsafe subprocess handling, and documentation drift.

Do not combine an unrelated refactor with a feature or bug fix. Preserve existing user work and avoid compatibility layers that have no stated requirement.

## Processing contract

The complete media, queue, subprocess, GUI, persistence, and safety contract
lives in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Contributors must
preserve that contract and should update the architecture document only when a
verified implementation or approved design decision changes it.

## Quality checks

The project has no maximum line length. Black uses `9999` as an effectively unlimited sentinel because it requires a numeric width; pycodestyle and Pylint line-length diagnostics are disabled. Use multiline formatting for clarity, not merely to meet a character count.

The intended Make targets are:

```bash
make format     # Apply Black
make lint       # Run Pylint and pycodestyle
make test       # Run the test suite
make check      # Run formatting checks, linting, and tests
```

Tests should be deterministic and must not require a GPU, network connection, large model download, or long media file by default. Use fakes for external processes in unit tests and tiny generated fixtures for FFmpeg integration tests. Mark hardware-dependent and heavyweight tests separately.

If a check cannot run, record the attempted command, the blocker, and the next-best validation. Never report an unrun check as passing.

## Reviewing AI-generated code

Before accepting generated code:

- Read it and be able to explain its behavior.
- Verify external APIs and command options against installed tools or authoritative documentation.
- Check path handling, shell safety, cancellation, cleanup, concurrency, and error propagation.
- Reject fabricated APIs, silent fallbacks, unexplained abstractions, and unbounded retries.
- Confirm that third-party code, models, and assets have known, compatible licenses.
- Require tests for success, failure, and regression paths where practical.

## Change description

Summarize:

- The outcome and reason for the change
- Important design decisions
- Tests and checks actually run
- User-visible or compatibility impact
- Remaining limitations or risks

Do not commit credentials, personal paths, generated videos, model weights, caches, temporary frames, or local environment files.
