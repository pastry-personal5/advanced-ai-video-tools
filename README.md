# Advanced AI Video Tools

Advanced AI Video Tools is a macOS Apple Silicon application and CLI that
concatenates real-world video clips with FFmpeg and optionally upscales the
single merged timeline with `realesrgan-ncnn-vulkan`.

## Status

Version 2.0.0 is the released baseline. V3 Phases 1–5 are implemented; Crop
and Video Interpolation remain proposed. The verified distribution is an
unsigned/ad-hoc-signed development DMG. Production Developer ID signing and
notarization remain deferred because Apple Developer Program enrollment is
unavailable.

## Quick start

Requirements: macOS 26.5.2+ on Apple Silicon, Python 3.10+, `uv`, PySide6,
FFmpeg, FFprobe, Vulkan, Real-ESRGAN NCNN Vulkan, and the
`realesrgan-x4plus` model files. External tools and models are user-managed.

```bash
uv sync --dev
uv run advanced-ai-video-tools gui
uv run advanced-ai-video-tools --help
```

See the [GUI guide](docs/USER_GUIDE_GUI.md),
[CLI guide](docs/USER_GUIDE_CLI.md), and
[v2.0.0 release notes](docs/v2/release-notes-v2.0.0.md).

## Development

```bash
make install
make format
make lint
make test
make check
make run
make performance-test
make gui-capture-test
make package-dev-dmg
```

Default tests require no GPU, network, model download, or checked-in media.
Native targets require an interactive supported macOS desktop.

Core references are the [architecture and media contract](docs/ARCHITECTURE.md),
[development guide](docs/DEVELOPMENT.md), [contributor guide](CONTRIBUTING.md),
[v3 roadmap](docs/v3/plans.md), and [agent instructions](AGENTS.md).

## License

Proprietary. Copyright © 2026 Pastry Personal 5. See [LICENSE](LICENSE).
