# Advanced AI Video Tools

Advanced AI Video Tools is a macOS Apple Silicon application and CLI for
concatenating real-world video clips with FFmpeg and optionally upscaling the
single merged timeline with `realesrgan-ncnn-vulkan`.

## Current status

V2.0.0 is complete. V3 Phase 1 — Refactoring is the active development target;
Crop and Video Interpolation are proposed future phases. The v2 media contract
remains authoritative during refactoring.

The verified v2 distribution artifact is an unsigned/ad-hoc-signed development
DMG. Production Developer ID signing, notarization, and Gatekeeper validation
are deferred because Apple Developer Program enrollment is unavailable.

## Quick start

Requirements: macOS 26.5.2 or later on Apple Silicon, Python 3.10+, `uv`,
PySide6, FFmpeg, FFprobe, a Vulkan-capable GPU, Real-ESRGAN NCNN Vulkan, and
the `realesrgan-x4plus` model files. External tools and models are installed
and managed by the user.

```bash
uv sync --dev
uv run advanced-ai-video-tools gui
uv run advanced-ai-video-tools --help
```

User documentation:

- [GUI user guide](docs/USER_GUIDE_GUI.md)
- [CLI user guide](docs/USER_GUIDE_CLI.md)
- [v2.0.0 release notes](docs/v2/release-notes-v2.0.0.md)

## Project documents

- [Architecture and media contract](docs/ARCHITECTURE.md)
- [AI-agent instructions](AGENTS.md)
- [Project milestones](docs/MILESTONES.md)
- [Development workflow](docs/DEVELOPMENT.md)
- [Contributor guide](CONTRIBUTING.md)

## Development commands

```bash
make install          # synchronize dependencies
make format           # format source and tests
make lint             # run Pylint and pycodestyle
make test             # run the test suite
make check            # formatting, lint, and tests
make run              # launch the GUI
make performance-test # opt-in native no-upscaling benchmark
make gui-capture-test # opt-in native GUI capture check
make package-dev-dmg  # build the unsigned development DMG
```

The default test suite requires no GPU, network, model download, or checked-in
media. Native targets require an interactive supported macOS desktop.

## License

This project is proprietary. Copyright © 2026 Pastry Personal 5. See
[LICENSE](LICENSE) for the complete terms.
