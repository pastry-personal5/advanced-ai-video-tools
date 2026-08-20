# AI Video Tools

AI Video Tools is a Python project for macOS on Apple Silicon that concatenates real-world video footage with FFmpeg and upscales it with `realesrgan-ncnn-vulkan`. A single Python processing service will own the complete pipeline; a PySide6 desktop GUI will provide a convenient front end to that same core behavior.

> **Status:** executable foundation. Typed job and media models, external-tool
> discovery, collision-safe output naming, FFprobe parsing, and the shared
> preflight service are implemented and tested. Media processing and the
> PySide6 GUI are the next implementation stages.

## Implemented foundation

- Reproducible Python packaging with `uv` and a committed lockfile
- Immutable models for job intent, probed streams, issues, and execution plans
- Exact rational frame-rate and sample-aspect-ratio handling
- Automatic timezone-aware `ai-video-...mp4` names with collision reservation
- Explicit-path-first discovery of FFmpeg, FFprobe, Real-ESRGAN, and x4plus models
- A tiny cached Real-ESRGAN inference smoke test that verifies the Vulkan backend
- Safe FFprobe JSON parsing with typed stream and metadata inventory
- Preflight gates for platform, paths, SDR BT.709, rotation, streams, timing,
  audio layout, dimensions, AI scale, concat strategy, and disk margin
- Human-readable and JSON CLI reports through `ai-video-tools preflight`
- Fast tests that require no GPU, network, model download, or real media

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

Version 1 is designed for photographic and live-action imagery. Anime, animation, illustration, and synthetic line-art enhancement are outside the product target.

## Core processing pipeline

### Key design decision: concat first, upscale once

Merge all clips into one video before extracting or upscaling frames. When every clip has compatible streams—especially the same codec, resolution, frame rate, pixel format, time base, and audio layout—use FFmpeg's concat demuxer with stream copy. This is the cleanest path because concatenation does not re-encode the source streams.

If the clips are incompatible, normalize them to a shared intermediate specification first, then concatenate those normalized clips. In either case, create one merged timeline and run Real-ESRGAN at most once, when the merged input is below the requested height. Do not upscale each input clip independently and concatenate the upscaled results.

The canonical job is one ordered pipeline:

1. **Probe:** use FFprobe to read stream layout, dimensions, frame rate, duration, time base, codecs, and audio properties for every input.
2. **Concatenate:** join clips in the requested order with FFmpeg. Prefer concat-demuxer stream copy for compatible streams; normalize incompatible inputs before joining them. The result is one merged working video.
3. **Extract:** decode the concatenated video into a lossless, sequentially named frame directory and retain the concatenated audio separately.
4. **Upscale when needed:** when the merged input is below the target height, pass its frame directory to `realesrgan-ncnn-vulkan` once with the selected model and smallest useful supported AI scale.
5. **Re-encode:** resize the processed frames to the exact target height while preserving the source aspect ratio, encode them with FFmpeg using the selected output settings, and mux the retained audio into the final video.
6. **Finalize:** validate the output, atomically move it to the requested destination, and remove job-owned temporary files.

The Python core must expose this workflow as one CLI operation. The GUI must call the same application service rather than maintaining a second pipeline. Progress should cover each stage, and cancellation must terminate active child processes and clean up only artifacts owned by the current job.

Frame extraction turns variable-frame-rate sources into a frame sequence, so each job must choose and record an explicit output frame rate. Audio must be mapped from the concatenated timeline and kept synchronized with the re-encoded frames.

### Version 1 media defaults

The default profile favors preservation during processing and high-quality, broadly playable output:

- **Normalization container:** Matroska
- **Normalization video:** lossless FFV1
- **Normalization audio:** lossless PCM at 48 kHz, using the selected primary channel layout
- **Normalization canvas and frame rate:** first clip's resolution and frame rate unless explicitly overridden; preserve aspect ratio and pad rather than crop or stretch
- **Color:** SDR BT.709 only; reject detected HDR and wide-gamut input
- **Color range:** limited/TV; convert accepted full-range input explicitly
- **Rotation:** unsupported in v1; reject nonzero rotation metadata and disable FFmpeg auto-rotation
- **Extracted/upscaled frames:** lossless PNG with deterministic zero-padded names
- **Upscaling model:** `realesrgan-x4plus` for real-world imagery
- **Final dimensions:** 2160 pixels high; calculate an even width from coded dimensions and sample aspect ratio
- **Final container:** MP4 with fast-start metadata
- **Final video:** H.264 through `libx264`, CRF 18, slow preset, and `yuv420p`
- **Final audio:** first audio stream, copied when compatible and unchanged; otherwise AAC-LC at 256 kbit/s and 48 kHz
- **Additional streams:** require acknowledgement, then drop extra audio, subtitles, chapters, and attachments

All media choices must be overridable from the shared job model. Mixed-resolution or variable-frame-rate inputs must produce a visible normalization warning before processing.

The default output height is exactly 2160 pixels. Calculate width from the merged video's coded dimensions and sample aspect ratio, then round to the nearest even integer required by `yuv420p`. For a 16:9 source, the result is 3840 × 2160. The equivalent FFmpeg sizing rule is `scale=-2:2160`.

Version 1 never rotates video. Inputs must already be upright and have zero or absent rotation/display-matrix metadata. Preflight rejects nonzero rotation, every FFmpeg decode uses `-noautorotate`, and the GUI and CLI expose no rotation control. Scaling always preserves aspect ratio; cropping and stretching are unsupported.

When the merged video is shorter than 2160 pixels, use the smallest Real-ESRGAN scale of 2×, 3×, or 4× that reaches or exceeds the target, then resize once to the exact dimensions during final encoding. If 4× does not reach 2160, use 4× and report that the final FFmpeg resize includes additional conventional enlargement. Inputs already at or above 2160 skip Real-ESRGAN by default and resize directly to the requested output height.

### Color and audio policy

Version 1 accepts SDR BT.709 video only. Preflight must reject HDR transfer functions, BT.2020 or other unsupported wide-gamut signaling, and clearly explain why the job cannot continue. Missing or ambiguous color metadata requires acknowledgement before the input is interpreted and tagged as BT.709; the application must never tone-map or change color interpretation silently.

For each clip, select its first audio stream. If a clip has no audio but another clip does, insert silence matching that clip's video duration and the job's normalized audio layout. If no input contains audio, produce no audio track. Pad audio that ends early with silence and trim audio that runs long so the audio timeline exactly matches the video timeline.

Extra audio streams, subtitles, chapters, and attachments are unsupported in v1. List them during preflight and require explicit acknowledgement before dropping them. Audio stream copy is allowed only when no padding, trimming, resampling, layout conversion, or container-incompatible change is required; otherwise use the default AAC-LC encoding profile.

### Operational defaults

- Preserve the first clip's exact rational frame rate, such as `30000/1001`; normalize VFR or mixed-rate inputs to it without float rounding.
- Run one active processing job and keep later jobs in an in-memory FIFO queue.
- Overwrite an existing destination by default, but only by atomically replacing it after the new partial output passes verification. A failed or cancelled job leaves the existing file intact. Users may opt out with CLI or GUI no-overwrite mode.
- Generate the default filename when the job is created using local time: `ai-video-YYYYMMDD-HHMMSS-ffffffZZZZ.mp4`, where `ZZZZ` is the numeric UTC offset such as `+0900` or `-0700`. Place it in the selected output directory and reserve a unique path so automatic naming never overwrites an earlier generated output.
- Store job workspaces under `~/Library/Caches/AI Video Tools/jobs/` using Qt's application cache location.
- Require a conservative peak-disk estimate plus a 20% free-space margin before starting.
- Delete workspaces after success or cancellation; retain and report them after failure.
- Do not resume partial jobs in v1.
- Let Real-ESRGAN choose the GPU and worker threads, start with automatic tiling, and keep TTA disabled.
- Retry recognized Vulkan memory failures only with bounded tile sizes of 512, 256, 128, 64, then 32.
- Store settings and rotating local logs under `~/Library/Application Support/AI Video Tools/`.
- Rotate logs at 10 MiB with five backups. Perform no telemetry, analytics, crash uploads, update checks, or other application-initiated network requests.

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

The `realesrgan-x4plus` parameter and binary model files are required. The application must pass `-n realesrgan-x4plus` explicitly and must not rely on the executable's built-in default model. Anime-specific models are not exposed in the v1 GUI or CLI.

## Getting started

Install the Python environment and inspect the implemented CLI:

```bash
uv sync --dev
uv run ai-video-tools --help
uv run ai-video-tools preflight --help
```

`uv sync` creates and manages the project virtual environment automatically. Activating it manually is optional. The executable locations for FFmpeg, FFprobe, and Real-ESRGAN should be configurable when they are not available on `PATH`.

Run preflight against one or more real clips:

```bash
uv run ai-video-tools preflight \
  --input clip-01.mp4 \
  --input clip-02.mp4 \
  --output-dir ./output \
  --realesrgan /path/to/realesrgan-ncnn-vulkan \
  --model-dir /path/to/models \
  --json
```

Preflight does not modify media. It reserves the proposed output only for the
duration of the diagnostic command and exits with status 0 when the plan is
ready or 2 when a blocking issue remains. Missing color tags require
`--assume-bt709`; unsupported secondary streams require
`--acknowledge-dropped-streams`. For example, a job created in Korea on August
21, 2026 could propose `ai-video-20260821-143052-123456+0900.mp4`.

The future `process` command and GUI will consume the same `JobRequest`,
`PreflightReport`, and `JobPlan` types. They are intentionally not exposed as
working commands yet.

## Development commands

The `Makefile` is the canonical interface for routine development tasks:

```bash
make install    # Synchronize runtime and development dependencies with uv
make format     # Format Python source with Black
make lint       # Run Pylint and pycodestyle
make test       # Run the automated test suite
make check      # Run formatting checks, linters, and tests
make run        # Show the current CLI entry point (GUI not implemented yet)
```

Use the `Makefile` as the canonical developer interface. Run an underlying tool directly through `uv run` only when diagnosing or configuring it, for example `uv run pylint src tests`.

## Current project structure

```text
ai-videol-tools-v2/
├── src/ai_video_tools/
│   ├── core/           # Immutable domain and preflight result models
│   ├── services/       # Shared preflight application service
│   ├── storage/        # Qt-standard paths and output reservation
│   ├── system/         # Host policy and prerequisite discovery
│   ├── video/          # FFprobe invocation and typed JSON parsing
│   ├── cli.py          # Thin preflight command-line adapter
│   └── __main__.py     # Module entry point
├── tests/              # Automated tests and lightweight fixtures
├── docs/
│   └── ARCHITECTURE.md # Pipeline and component specification
├── AGENTS.md           # Development guidance for coding agents
├── CONTRIBUTING.md     # Contributor workflow and quality checks
├── README.md
├── Makefile            # Canonical development commands
├── uv.lock             # Reproducible dependency lockfile
├── setup.cfg           # pycodestyle configuration (unsupported in pyproject)
└── pyproject.toml
```

The processing service, FFmpeg command builders, upscaling adapter, job queue,
and GUI will extend these boundaries rather than duplicating preflight logic.

## Engineering principles

- Keep GUI code separate from video processing and AI inference logic.
- Keep the CLI and GUI thin; both must dispatch the same validated job model to the same pipeline service.
- Represent each operation as a validated job with explicit inputs and outputs.
- Never run FFmpeg or model inference on the main GUI thread.
- Prefer structured subprocess arguments over shell command strings.
- Preserve frame order with deterministic, zero-padded filenames.
- Protect user inputs and existing outputs; use temporary outputs and promote them only after success.
- Apply the workspace policy reliably: delete after success or cancellation and retain failed workspaces for diagnosis.
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
