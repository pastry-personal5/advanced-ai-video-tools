# Advanced AI Video Tools

[![Release](https://img.shields.io/github/v/tag/pastry-personal5/advanced-ai-video-tools?label=release)](https://github.com/pastry-personal5/advanced-ai-video-tools/releases)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](pyproject.toml)
[![Platform](https://img.shields.io/badge/platform-macOS%20Apple%20Silicon-lightgrey)](docs/DEVELOPMENT.md)
[![License](https://img.shields.io/badge/license-Proprietary-red)](LICENSE)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-brightgreen)](CONTRIBUTING.md)

Advanced AI Video Tools is a macOS Apple Silicon application and CLI that
concatenates real-world video clips with FFmpeg and optionally upscales the
single merged timeline with `realesrgan-ncnn-vulkan`, or through a selectable
pipeline: concat only, native upscale, 4× then resize, or 2× → 3× → resize with
user-supplied Spandrel `.safetensors` or `.pth` models.

## Status

Version 2.0.0 is the released baseline. V3 Phases 1–5 and Phase 7 are implemented; Phase 6
Customizable Upscaling Pipelines is implemented and in acceptance (see its
[phase record](docs/v3/6-customizable-upscaling-pipelines.md) for the evidence
still pending), Phases 8–10 are unassigned, and
Phase 11 Crop and Phase 12 Video Interpolation remain proposed. The verified
distribution is an unsigned/ad-hoc-signed development DMG. Production Developer ID signing and
notarization remain deferred because Apple Developer Program enrollment is
unavailable.

## Quick start

Requirements: macOS 26.5.2+ on Apple Silicon, Python 3.10+, `uv`, PySide6,
FFmpeg, FFprobe, Vulkan, Real-ESRGAN NCNN Vulkan, and the
`realesrgan-x4plus` model files. External tools and models are user-managed.
The optional 2×/3× pipelines also need the user-installed Spandrel runner
(`tools/spandrel-runner`) and `.safetensors` or `.pth` models. By default they use
`tools/spandrel-runner/spandrel-runner` with
`2xPublic_realplksr_dysample_layernorm_real_nn.pth` (2×) and `DAT_x3_bf16.safetensors`
(3×) from `tools/spandrel-runner/models/`.

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
make phase6-native-test
make package-dev-dmg
```

Default tests require no GPU, network, model download, or checked-in media.
Native targets require an interactive supported macOS desktop.

Core references are the [architecture and media contract](docs/ARCHITECTURE.md),
[development guide](docs/DEVELOPMENT.md), [contributor guide](CONTRIBUTING.md),
[v3 roadmap](docs/v3/plans.md), and [agent instructions](AGENTS.md).

## License

Proprietary. Copyright © 2026 Pastry Personal 5. See [LICENSE](LICENSE).
