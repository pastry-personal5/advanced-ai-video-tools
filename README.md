# AI Video Tools

AI Video Tools is a Python application for macOS on Apple Silicon that concatenates video with FFmpeg and upscales it with `realesrgan-ncnn-vulkan`. A single Python processing command owns the complete pipeline; a PySide6 desktop GUI provides a convenient front end to that same core behavior.

> **Status:** foundation stage. The repository currently contains project guidance only; source code, packaging, and executable commands will be added as implementation begins.

## Planned features

- Concatenate multiple video clips in a user-defined order
- Detect incompatible clip properties and normalize them when needed
- Extract the concatenated video to frames with FFmpeg
- Upscale frame directories with `realesrgan-ncnn-vulkan`
- Re-encode upscaled frames and restore audio with FFmpeg
- Configure resolution, codec, quality, audio, and output location
- Show processing progress, logs, warnings, and actionable errors
- Cancel long-running jobs safely
- Preserve audio and video metadata where the selected workflow permits
- Use hardware acceleration when a supported backend is available

## Core processing pipeline

### Key design decision: concat first, upscale once

Merge all clips into one video before extracting or upscaling frames. When every clip has compatible streams—especially the same codec, resolution, frame rate, pixel format, time base, and audio layout—use FFmpeg's concat demuxer with stream copy. This is the cleanest path because concatenation does not re-encode the source streams.

If the clips are incompatible, normalize them to a shared intermediate specification first, then concatenate those normalized clips. In either case, create one merged timeline and run that timeline through the upscaling stage exactly once. Do not upscale each input clip independently and concatenate the upscaled results.

The canonical job is one ordered pipeline:

1. **Probe:** use FFprobe to read stream layout, dimensions, frame rate, duration, time base, codecs, and audio properties for every input.
2. **Concatenate:** join clips in the requested order with FFmpeg. Prefer concat-demuxer stream copy for compatible streams; normalize incompatible inputs before joining them. The result is one merged working video.
3. **Extract:** decode the concatenated video into a lossless, sequentially named frame directory and retain the concatenated audio separately.
4. **Upscale once:** pass the merged video's input and output frame directories to `realesrgan-ncnn-vulkan` with the selected model, scale, GPU, tile size, and image format.
5. **Re-encode:** encode the upscaled frames with FFmpeg using the selected output codec and quality settings, then mux the retained audio into the final video.
6. **Finalize:** validate the output, atomically move it to the requested destination, and remove job-owned temporary files.

The Python core must expose this workflow as one CLI operation. The GUI must call the same application service rather than maintaining a second pipeline. Progress should cover each stage, and cancellation must terminate active child processes and clean up only artifacts owned by the current job.

Frame extraction turns variable-frame-rate sources into a frame sequence, so each job must choose and record an explicit output frame rate. Audio must be mapped from the concatenated timeline and kept synchronized with the re-encoded frames.

### Version 1 media defaults

The default profile favors preservation during processing and high-quality, broadly playable output:

- **Normalization container:** Matroska
- **Normalization video:** lossless FFV1
- **Normalization audio:** lossless PCM at 48 kHz, using the selected primary channel layout
- **Normalization canvas and frame rate:** first clip's resolution and frame rate unless explicitly overridden; preserve aspect ratio and pad rather than crop or stretch
- **Extracted/upscaled frames:** lossless PNG with deterministic zero-padded names
- **Final container:** MP4 with fast-start metadata
- **Final video:** H.264 through `libx264`, CRF 18, slow preset, and `yuv420p`
- **Final audio:** copy the selected primary stream when it is MP4-compatible; otherwise encode AAC-LC at 256 kbit/s and 48 kHz
- **Additional streams:** warn rather than silently discard extra audio, subtitles, chapters, or attachments

All media choices must be overridable from the shared job model. Mixed-resolution or variable-frame-rate inputs must produce a visible normalization warning before processing.

## Requirements

Version 1 requires macOS 26.5.2 or later on Apple Silicon. The reference development and validation machine is an Apple M5 Max with 128 GB unified memory; that hardware configuration is not a minimum system requirement.

Expected runtime requirements include:

- macOS 26.5.2 or later on Apple Silicon; older macOS releases, Intel Macs, and other operating systems are outside the v1 support target
- Python 3.10 or later
- [uv](https://docs.astral.sh/uv/) for Python and dependency management
- [PySide6](https://doc.qt.io/qtforpython-6/) for the desktop GUI
- [FFmpeg](https://ffmpeg.org/) and FFprobe available on `PATH`
- [`realesrgan-ncnn-vulkan`](https://github.com/xinntao/Real-ESRGAN-ncnn-vulkan) and its model files
- A Vulkan-capable GPU and working Vulkan driver

Users install FFmpeg, FFprobe, `realesrgan-ncnn-vulkan`, Vulkan support, and model files themselves. The application does not bundle or automatically download these components. It discovers explicit executable paths first and then `PATH`, and fails preflight with an actionable message when a required component is missing or incompatible.

## Getting started

There is not yet a runnable application in this repository. Once packaging and source files are present, setup will use `uv` (the module entry point may change):

```bash
uv sync --dev
uv run ai-video-tools --help
```

`uv sync` creates and manages the project virtual environment automatically. Activating it manually is optional. The executable locations for FFmpeg, FFprobe, and Real-ESRGAN should be configurable when they are not available on `PATH`.

The intended CLI shape is:

```bash
uv run ai-video-tools process \
  --input clip-01.mp4 \
  --input clip-02.mp4 \
  --output combined-upscaled.mp4 \
  --model realesrgan-x4plus \
  --scale 4
```

This interface is a design target until the CLI entry point is implemented.

## Development commands

The project will expose its routine development tasks through a `Makefile`. Once the Python project and tool configuration have been added, the intended commands are:

```bash
make install    # Synchronize runtime and development dependencies with uv
make format     # Format Python source with Black
make lint       # Run Pylint and pycodestyle
make test       # Run the automated test suite
make check      # Run formatting checks, linters, and tests
make run        # Launch the GUI application
```

Use the `Makefile` as the canonical developer interface. Run an underlying tool directly through `uv run` only when diagnosing or configuring it, for example `uv run pylint src tests`.

## Proposed project structure

```text
ai-videol-tools-v2/
├── src/ai_video_tools/
│   ├── gui/            # PySide6 windows, dialogs, widgets, and view models
│   ├── cli.py          # Thin command-line front end
│   ├── services/       # Shared pipeline and job orchestration
│   ├── video/          # FFmpeg probing, concatenation, and encoding
│   ├── upscale/        # realesrgan-ncnn-vulkan process adapter
│   └── __main__.py     # Application entry point
├── tests/              # Automated tests and lightweight fixtures
├── docs/
│   └── ARCHITECTURE.md # Pipeline and component specification
├── AGENTS.md           # Development guidance for coding agents
├── CONTRIBUTING.md     # Contributor workflow and quality checks
├── README.md
├── Makefile            # Canonical development commands
├── uv.lock             # Reproducible dependency lockfile
└── pyproject.toml
```

This layout is a recommendation, not a description of files that already exist.

## Engineering principles

- Keep GUI code separate from video processing and AI inference logic.
- Keep the CLI and GUI thin; both must dispatch the same validated job model to the same pipeline service.
- Represent each operation as a validated job with explicit inputs and outputs.
- Never run FFmpeg or model inference on the main GUI thread.
- Prefer structured subprocess arguments over shell command strings.
- Preserve frame order with deterministic, zero-padded filenames.
- Protect user inputs and existing outputs; use temporary outputs and promote them only after success.
- Make temporary-file cleanup reliable after success, failure, and cancellation.
- Keep tests fast by mocking heavyweight inference and using very small media fixtures.
- Avoid bundling model weights or generated videos in Git.

## AI-assisted development

Most source code in this project is expected to be created with Codex or another AI coding tool. [AGENTS.md](AGENTS.md) is the repository-level implementation contract for those tools. It defines the desired outcome, architecture boundaries, safe autonomy, validation requirements, and completion criteria.

Generated code is a draft, not evidence of correctness. The contributor accepting a change remains responsible for its behavior, security, licensing, and maintainability. Useful requests to Codex should state the desired outcome and acceptance criteria; Codex should inspect the repository, choose the implementation details, and verify the result.

## Contributing

Before submitting a change:

1. Read and understand all generated or modified code.
2. Check for fabricated APIs, unsafe behavior, hidden assumptions, and incompatible licenses.
3. Create or update tests for the behavior being changed.
4. Run `make check` to verify Black formatting, Pylint, pycodestyle, and the test suite.
5. Test affected GUI workflows manually when automation cannot cover them.
6. Document new dependencies, models, environment variables, and user-facing options.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the complete workflow and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the authoritative processing design.

## License

No license has been selected yet. Until a license file is added, all rights are reserved by the project owner.
