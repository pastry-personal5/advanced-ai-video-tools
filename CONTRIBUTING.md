# Contributing

AI Video Tools welcomes focused, reviewable improvements. Most code is expected to be AI-generated or AI-assisted, but the person accepting a change remains responsible for understanding and validating it.

## Before you start

Read:

- [README.md](README.md) for product scope and intended commands
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the processing pipeline and system boundaries
- [AGENTS.md](AGENTS.md) for repository-wide implementation rules

Check the repository before choosing a framework, dependency, entry point, or command. The project is in its foundation stage, so proposed paths in the documentation may not exist yet.

## Development environment

The project uses:

- macOS 26.5.2 or later on Apple Silicon as the v1 target; Apple M5 Max with 128 GB unified memory is the reference machine
- Python 3.10 or newer
- PySide6 as the GUI framework
- `uv` for environments, dependencies, and command execution
- Black for formatting
- Pylint and pycodestyle for linting
- A `Makefile` as the canonical developer interface
- FFmpeg, FFprobe, and `realesrgan-ncnn-vulkan` as external processing tools

Install FFmpeg, FFprobe, `realesrgan-ncnn-vulkan`, its model files, and working Vulkan support separately. The project does not bundle or automatically download them. Contributors may configure explicit executable paths or make the tools available on `PATH`.

Once project metadata exists, install development dependencies with:

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

## Required processing behavior

The central invariant is **concat first, upscale once**:

```text
validate → probe → normalize if needed → concat → extract frames
         → upscale once → encode and mux audio → verify → publish
```

Compatible clips should use FFmpeg concat-demuxer stream copy. Incompatible clips must be normalized to a shared specification before concat. Source clips must not be upscaled independently.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the complete contract.

## Quality checks

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
