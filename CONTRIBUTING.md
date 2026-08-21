# Contributing

AI Video Tools welcomes focused, reviewable improvements. Most code is expected to be AI-generated or AI-assisted, but the person accepting a change remains responsible for understanding and validating it.

Version 1 targets photographic and live-action footage. Anime, animation, illustration, synthetic line art, and their specialized Real-ESRGAN models are out of scope.

## Before you start

Read:

- [README.md](README.md) for product scope and intended commands
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the processing pipeline and system boundaries
- [AGENTS.md](AGENTS.md) for repository-wide implementation rules

Check the repository before choosing a framework, dependency, entry point, or command. The typed core, preflight and processing CLI commands, compatibility analysis, safe media command builders, owned-workspace manager, cancellable process runner, composable preparation/extraction/upscaling/finalization services, strict Real-ESRGAN adapter, output verification, atomic publisher, and full-job orchestration exist. Job queuing and the GUI remain design contracts until their modules are implemented and tested.

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

## Required processing behavior

The central invariant is **concat first, upscale at most once**:

```text
validate → probe → normalize if needed → concat → extract frames
         → upscale once if needed → encode and mux audio → verify → publish
```

Compatible clips should use FFmpeg concat-demuxer stream copy. Incompatible clips must be normalized to a shared specification before concat. Source clips must not be upscaled independently.

The default final height is 2160 pixels. Preserve the aspect ratio derived from coded dimensions and sample aspect ratio, calculate an even output width, and keep raw Real-ESRGAN scale selection internal to the pipeline.

Use `realesrgan-x4plus` explicitly for AI processing. Tests must verify that the adapter does not inherit the executable's anime-oriented default and that anime-specific model names are rejected.

Version 1 accepts supported SDR BT.709 and SMPTE 170M matrices. Require and freeze the first clip's matrix and require explicit range. Missing transfer characteristics or color primaries are accepted rather than defaulting to BT.709. Preserve optional tags declared by the first clip and omit fields absent from it. Reject explicit optional-tag conflicts, detected HDR, unsupported wide gamut, unsupported tags, and missing matrix/range metadata instead of silently interpreting, converting, or tone-mapping it.

Produce limited-range output using the frozen first-clip color profile, converting accepted full-range input explicitly without changing its matrix. Reject nonzero rotation metadata, pass `-noautorotate` to FFmpeg, and never crop or stretch. Preserve the first clip's nominal exact rational frame rate without float rounding. Recognize rate differences below one stream time-base tick as timestamp quantization and use that same strict tolerance during verification.

Use the first audio stream from each clip. Insert silence where a clip lacks audio, pad short audio, trim long audio to the video timeline, and require acknowledgement before dropping unsupported secondary streams.

Run one job at a time in FIFO order. Generate and reserve a timezone-aware `ai-video-` filename when each job is created; generated paths never overwrite older output. Explicit paths overwrite by default through verified atomic replacement, preserve the old file on failure, and honor no-overwrite mode. Require estimated peak disk space plus 20%, delete successful or cancelled workspaces, retain failed workspaces, and do not implement resume in v1.

Use Real-ESRGAN automatic GPU and tiling defaults with TTA disabled. Retry only recognized Vulkan memory errors using the documented bounded tile sequence. Keep settings and rotating local logs in Qt standard macOS locations, and do not add telemetry or application-initiated network access.

Application modules use Loguru and never configure sinks independently. The eventual application bootstrap owns stderr and rotating-file sink configuration; direct CLI output remains separate from diagnostic logging.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the complete contract.

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
