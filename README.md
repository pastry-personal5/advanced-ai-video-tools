# AI Video Tools

AI Video Tools is a Python project for macOS on Apple Silicon that concatenates real-world video footage with FFmpeg and upscales it with `realesrgan-ncnn-vulkan`. A single Python processing service owns the complete pipeline; the PySide6 desktop shell observes and controls that same backend queue.

> **Release and development status:** v1.0.0 is the current completed release baseline. The active development target is v2. Existing v1 behavior remains authoritative until a v2 design decision explicitly changes it; no additional v2 features are implied solely by the target change.

Active v2 planning is maintained in [docs/v2/plans.md](docs/v2/plans.md). Implementation follows [docs/v2/implement.md](docs/v2/implement.md), the current phase is [Phase 1 — Enhance GUI](docs/v2/1-enhance-gui.md), and [Phase 2 — Rename Project](docs/v2/2-rename-project.md) is defined for subsequent work.

> **Status:** executable foundation. Typed job and media models, external-tool
> discovery, collision-safe output naming, FFprobe parsing, and the shared
> preflight service are implemented and tested. Typed compatibility analysis,
> safe FFmpeg/FFprobe command construction, lossless normalization planning,
> concat manifests, owned workspaces, cancellable process execution, sequential
> normalization, one concat, and merged-media verification are also implemented
> and exercised with tiny real media. Caller-owned composition and exact-CFR RGB
> PNG extraction are implemented as backend services. Cancellable directory-mode
> Real-ESRGAN execution, skip policy, bounded memory retries, and exact output-frame
> verification are implemented. Quality-first final MP4 encoding, final probe
> verification, atomic replacement/no-clobber publication, and terminal workspace
> cleanup are implemented and exercised with real FFmpeg. Full-job orchestration
> now composes those stages with shared cancellation, progress, state transitions,
> reservation release, and terminal workspace policy. The `process` CLI command
> exposes that complete pipeline with text or JSON terminal results and cooperative
> Ctrl-C cancellation. Typed persistent settings and bounded local diagnostics are
> available for frontends. A typed single-worker FIFO now serializes queued jobs;
> a native PySide6 shell now renders queue state, progress, output paths, errors,
> reordering, and cancellation. The GUI now creates jobs through ordered clip
> selection, asynchronous preflight review, explicit stream-drop acknowledgement,
> safe queue submission, and validated external-tool preference editing.

## Implemented foundation

- Reproducible Python packaging with `uv` and a committed lockfile
- Immutable models for job intent, probed streams, issues, and execution plans
- Exact rational frame-rate and sample-aspect-ratio handling
- Automatic local-time `ai-video-...mp4` names with compact UUIDv7 identifiers and collision reservation
- Explicit-path-first discovery of FFmpeg, FFprobe, Real-ESRGAN, and x4plus models
- A tiny cached Real-ESRGAN inference smoke test that verifies the Vulkan backend
- Safe FFprobe JSON parsing with typed stream and metadata inventory
- Typed stream-copy compatibility findings with normalize-all-or-none planning
- Safely escaped concat manifests using ordered absolute paths
- Shell-free FFmpeg normalization commands with `-noautorotate`, explicit preservation of the first clip's SDR color profile, exact rational CFR, first-audio mapping, silence insertion, audio padding/trimming, FFV1, and PCM
- One concat-demuxer stream-copy command after optional normalization
- Ownership-marked per-job workspaces with guarded cleanup and failed-workspace retention
- Shell-free subprocess execution with bounded diagnostics, timeouts, cancellation, and process-group termination
- A media-preparation service that normalizes clips sequentially, writes the manifest, concatenates exactly once, reports measured stage progress, and verifies the merged intermediate—including FFV1/PCM on the normalization path—with either standalone cleanup or caller-owned retention
- Cancellable exact-rational frame extraction with explicit limited-range YUV-to-RGB conversion using the frozen BT.709 or SMPTE 170M matrix, deterministic nine-digit PNG names, structural RGB PNG validation, contiguous numbering, plausible frame-count checks, and retention of merged audio for later muxing
- Strict `realesrgan-x4plus` directory execution with the frozen 2×/3×/4× scale, automatic GPU and threads, automatic tiling first, bounded allocation-failure retries at `512 → 256 → 128 → 64 → 32`, cancellation, attempt diagnostics, skip behavior, and exact output-frame verification
- Explicit final MP4 encoding from RGB frames with exact rational CFR, limited-range conversion and frozen first-clip color tags, H.264 CRF 3 slow `yuv420p`, first-audio copy only when exact and MP4-safe, otherwise aligned 48 kHz AAC-LC at 256 kbit/s
- Probe-gated publication using same-filesystem partials, atomic replacement for explicit overwrite, atomic no-clobber for generated/no-overwrite paths, old-output preservation on failure or cancellation, actionable exact frame-timing diagnostics, success/cancellation cleanup, and failed-workspace retention
- A synchronous full-job pipeline service with explicit lifecycle transitions, measured validation/probe progress, one shared cancellation token and workspace, typed terminal results, reservation release, clean cancellation, and failed-workspace retention
- Preflight gates for platform, paths, explicit matching SDR BT.709 or SMPTE 170M profiles, rotation, streams, timestamp-aware CFR/VFR timing,
  audio layout, dimensions, AI scale, concat strategy, and disk margin
- Human-readable and JSON CLI results through `ai-video-tools preflight` and `ai-video-tools process`, with measured text progress on stderr
- One-time Loguru bootstrap with human-readable stderr output, a thread-safe rotating `10 MB` local file retained for five rotations, stable job/stage context, exact shell-quoted INFO records for every FFmpeg, FFprobe, and Real-ESRGAN launch, and CLI-visible log paths
- Typed schema-versioned JSON settings for tool overrides, recent input/output directories, target height, overwrite preference, and non-safety preview mute/volume preferences, with private file permissions, atomic replacement, corruption quarantine, and protection against silently destroying newer schemas
- A frontend-independent single-worker FIFO with frozen creation identities and destination claims, typed snapshots and terminal outcomes, pending-job reorder/removal, active cooperative cancellation, progress forwarding, failure isolation, and shutdown that cancels and joins all unfinished work
- A PySide6 application bootstrap, cross-thread queue-snapshot signal bridge, typed `QAbstractListModel`, and native job window with measured progress, status/error details, pending reorder controls, cancellation, settings summary, diagnostics location, and joined backend shutdown
- An ordered GUI job editor for clips, output directory, target height, fixed real-image model and compact UUIDv7 naming; QThread-backed diagnostic preflight; complete warning/error review; per-job dropped-stream acknowledgement; authoritative FIFO submission; and persistence of recent directories and target height without persisting safety acknowledgement
- A native external-tools editor with file and directory pickers, per-executable reset-to-`PATH`, automatic model-directory discovery, off-thread executable/model/Vulkan validation, and atomic persistence only after every check succeeds
- Fast tests that require no GPU, network, model download, or checked-in media;
  the tiny FFmpeg integration fixture is generated locally and skips when the
  user-installed FFmpeg tools are unavailable
- A full-job integration test that runs real preflight, normalization, concat,
  extraction, final encoding, verification, atomic publication, and cleanup
  with tiny generated media and a lightweight directory-mode fake upscaler

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
- **Normalization video:** lossless FFV1 level 3 in `yuv444p10le`
- **Normalization audio:** lossless `pcm_s24le` at 48 kHz, using the selected primary channel layout
- **Normalization canvas and frame rate:** first clip's resolution and frame rate unless explicitly overridden; preserve aspect ratio and pad rather than crop or stretch
- **Color:** require and freeze the first clip's supported SDR matrix, preserve it through output, and accept BT.709 or SMPTE 170M without cross-matrix conversion; require explicit range, ignore missing transfer/primary tags without inventing values, and reject explicit conflicts, detected HDR, unsupported wide gamut, and unsupported tags
- **Color range:** limited/TV; convert accepted full-range input explicitly
- **Rotation:** unsupported in v1; reject nonzero rotation metadata and disable FFmpeg auto-rotation
- **Extracted/upscaled frames:** lossless PNG with deterministic zero-padded names
- **Upscaling model:** `realesrgan-x4plus` for real-world imagery
- **Final dimensions:** 2160 pixels high; calculate an even width from coded dimensions and sample aspect ratio
- **Final container:** MP4 with fast-start metadata
- **Final video:** H.264 through `libx264`, CRF 3, slow preset, and `yuv420p`
- **Final audio:** first audio stream, copied when compatible and unchanged; otherwise AAC-LC at 256 kbit/s and 48 kHz
- **Additional streams:** require acknowledgement, then drop extra audio, subtitles, chapters, and attachments

All media choices must be overridable from the shared job model. Mixed-resolution or variable-frame-rate inputs must produce a visible normalization warning before processing.

The default output height is exactly 2160 pixels. Calculate width from the merged video's coded dimensions and sample aspect ratio, then round to the nearest even integer required by `yuv420p`. For a 16:9 source, the result is 3840 × 2160. The equivalent FFmpeg sizing rule is `scale=-2:2160`.

Version 1 never rotates video. Inputs must already be upright and have zero or absent rotation/display-matrix metadata. Preflight rejects nonzero rotation, every FFmpeg decode uses `-noautorotate`, and the GUI and CLI expose no rotation control. Scaling always preserves aspect ratio; cropping and stretching are unsupported.

When the merged video is shorter than 2160 pixels, use the smallest Real-ESRGAN scale of 2×, 3×, or 4× that reaches or exceeds the target, then resize once to the exact dimensions during final encoding. If 4× does not reach 2160, use 4× and report that the final FFmpeg resize includes additional conventional enlargement. Inputs already at or above 2160 skip Real-ESRGAN by default and resize directly to the requested output height.

### Color and audio policy

Version 1 requires and freezes the first clip's explicit supported SDR matrix as the job output matrix. A BT.709 matrix remains BT.709; a SMPTE 170M matrix remains SMPTE 170M through normalization, YUV-to-RGB extraction, RGB-to-YUV encoding, and final stream signaling. Matrix and range are mandatory. Missing transfer characteristics or color primaries are accepted rather than defaulting to BT.709. Optional tags declared by the first clip are preserved in output; fields absent from the first clip remain unspecified. When optional tags are present on both clips, explicit conflicts are rejected; missing optional tags do not conflict. Preflight also rejects mixed matrices, HDR transfer functions, BT.2020, unsupported wide-gamut signaling, and unsupported tags. The application neither converts SMPTE 170M to BT.709 nor silently assumes or retags absent color metadata.

For each clip, select its first audio stream. If a clip has no audio but another clip does, insert silence matching that clip's video duration and the job's normalized audio layout. If no input contains audio, produce no audio track. Pad audio that ends early with silence and trim audio that runs long so the audio timeline exactly matches the video timeline.

Extra audio streams, subtitles, chapters, and attachments are unsupported in v1. List them during preflight and require explicit acknowledgement before dropping them. Audio stream copy is allowed only when no padding, trimming, resampling, layout conversion, or container-incompatible change is required; otherwise use the default AAC-LC encoding profile.

### Operational defaults

- Preserve the first clip's nominal exact rational CFR, such as `16/1` or `30000/1001`, without float rounding. Treat `r_frame_rate` and `avg_frame_rate` as the same CFR when their frame periods differ by less than one tick of the stream time base; otherwise treat the first clip as VFR and use its rational average rate. Verify merged and final rates with the same timestamp-derived tolerance rather than literal fraction equality.
- Run one active processing job and keep later jobs in an in-memory FIFO queue.
- Overwrite an existing destination by default, but only by atomically replacing it after the new partial output passes verification. A failed or cancelled job leaves the existing file intact. Users may opt out with CLI or GUI no-overwrite mode.
- Generate the default filename when the job is created using local time: `ai-video-YYYYMMDD-HHMMSS-<compact-UUIDv7>.mp4`. The compact UUID is the standard 32 lowercase hexadecimal characters without hyphens, and its embedded Unix-millisecond timestamp comes from the same timezone-aware creation instant. Place the file in the selected output directory and reserve a unique path so automatic naming never overwrites an earlier generated output.
- Store job workspaces under `~/Library/Caches/AI Video Tools/jobs/` using Qt's application cache location.
- Require a conservative peak-disk estimate plus a 20% free-space margin before starting.
- Delete workspaces after success or cancellation; retain and report them after failure.
- Do not resume partial jobs in v1.
- Let Real-ESRGAN choose the GPU and worker threads, start with automatic tiling, and keep TTA disabled.
- Retry recognized Vulkan memory failures only with bounded tile sizes of 512, 256, 128, 64, then 32.
- Store settings and Loguru-managed local logs under `~/Library/Application Support/AI Video Tools/`.
- Persist only non-secret, non-job-specific preferences. Preview mute and volume are presentation preferences; dropped-stream acknowledgement is deliberately per job and is never remembered across inputs. Settings writes use a private same-directory temporary file and atomic replacement; malformed documents are quarantined, while unknown newer schema versions are preserved and rejected explicitly.
- Configure Loguru once at startup with stderr and queued file sinks, rotate at 10 MiB, retain five backups, and avoid production exception-value exposure. Perform no telemetry, analytics, crash uploads, update checks, or other application-initiated network requests.

## Requirements

Version 1 requires macOS 26.5.2 or later on Apple Silicon. The reference development and validation machine is an Apple M5 Max with 128 GB unified memory; that hardware configuration is not a minimum system requirement.

Expected runtime requirements include:

- macOS 26.5.2 or later on Apple Silicon; older macOS releases, Intel Macs, and other operating systems are outside the v1 support target
- Python 3.10 or later
- [uv](https://docs.astral.sh/uv/) for Python and dependency management
- [PySide6](https://doc.qt.io/qtforpython-6/) for the desktop GUI
- [Loguru](https://github.com/Delgan/loguru) for application diagnostics
- [FFmpeg](https://ffmpeg.org/) and FFprobe available on `PATH`
- [`realesrgan-ncnn-vulkan`](https://github.com/xinntao/Real-ESRGAN-ncnn-vulkan) and its model files
- A Vulkan-capable GPU and working Vulkan driver

Users install FFmpeg, FFprobe, `realesrgan-ncnn-vulkan`, Vulkan support, and model files themselves. The application does not bundle or automatically download these components. It discovers explicit executable paths first and then `PATH`, and fails preflight with an actionable message when a required component is missing or incompatible.

The `realesrgan-x4plus` parameter and binary model files are required. The application must pass `-n realesrgan-x4plus` explicitly and must not rely on the executable's built-in default model. Anime-specific models are not exposed in the v1 GUI or CLI.

## Getting started

Install the Python environment, launch the desktop shell, or inspect the CLI:

```bash
uv sync --dev
uv run ai-video-tools --help
uv run ai-video-tools gui
uv run ai-video-tools preflight --help
uv run ai-video-tools process --help
```

`uv sync` creates and manages the project virtual environment automatically. Activating it manually is optional. In the GUI, select **External Tools…** to configure FFmpeg, FFprobe, Real-ESRGAN, or its model directory when automatic discovery is unsuitable. **Use PATH** clears an executable override, and **Automatic** derives the model directory from the resolved Real-ESRGAN installation. **Validate & Save** runs launch, model-pair, and Vulkan inference checks outside the GUI thread; failed values are not persisted.

In the desktop application, add clips in top-to-bottom concat order, choose an output directory, set the target height, and select **Preflight & Queue**. Diagnostic preflight runs outside the GUI thread and shows every warning or blocking issue before submission. Unsupported secondary streams require the dedicated acknowledgement checkbox; that acknowledgement is bound to the exact reviewed per-clip dropped-item inventory, applies only to that job, and is never saved as a preference. Accepted jobs enter the single-worker FIFO and perform authoritative preflight again immediately before processing. If the inventory changed while waiting, authoritative preflight rejects the job for another review.

The GUI always uses its approved dark theme; it does not follow the macOS light/dark appearance setting.

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
ready or 2 when a blocking issue remains. Missing matrix/range metadata and explicit color conflicts are rejected, while missing transfer/primary tags are ignored without defaults. Unsupported secondary streams require `--acknowledge-dropped-streams`. For example, a job created in Korea on August
21, 2026 could propose `ai-video-20260821-143052-01a022ccf35b7a1e8b0bf554b4c36db2.mp4`.

Run the complete pipeline with the same job arguments:

```bash
uv run ai-video-tools process \
  --input clip-01.mp4 \
  --input clip-02.mp4 \
  --output-dir ./output \
  --realesrgan /path/to/realesrgan-ncnn-vulkan \
  --model-dir /path/to/models
```

Text mode writes measured stage progress to stderr and the completed output
summary to stdout. `--json` suppresses progress and emits one machine-readable
terminal result. Exit status is 0 for success, 1 for a processing failure, 2 for
preflight rejection, and 130 for clean Ctrl-C cancellation. Failed jobs report
their retained workspace; successful and cancelled jobs clean owned temporary
state. The GUI creates and previews the same typed `JobRequest`, then dispatches the accepted request through the FIFO to `PipelineService`.

## Development commands

The `Makefile` is the canonical interface for routine development tasks:

```bash
make install    # Synchronize runtime and development dependencies with uv
make format     # Format Python source with Black
make lint       # Run Pylint and pycodestyle
make test       # Run the automated test suite
make check      # Run formatting checks, linters, and tests
make run        # Launch the PySide6 desktop shell
```

Use the `Makefile` as the canonical developer interface. Run an underlying tool directly through `uv run` only when diagnosing or configuring it, for example `uv run pylint src tests`.

## Current project structure

```text
ai-videol-tools-v2/
├── src/ai_video_tools/
│   ├── core/           # Immutable domain and preflight result models
│   ├── gui/            # PySide6 bootstrap, queue model, and native window
│   ├── services/       # Shared preflight and composable processing-stage services
│   ├── storage/        # Qt-standard paths, reservations, workspaces, and publication
│   ├── system/         # Host policy and prerequisite discovery
│   ├── upscaling/      # Real-ESRGAN policy and safe argument construction
│   ├── video/          # Probing, compatibility, manifests, and FFmpeg builders
│   ├── cli.py          # Thin preflight and processing command-line adapters
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

The queue-backed GUI extends these boundaries rather than duplicating the implemented full-job pipeline.

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

This project is proprietary. Copyright © 2026 AI Video Tools Project Owner. All rights are reserved, and no permission to use, copy, modify, or distribute the project is granted without the owner's prior written permission. Third-party components remain under their respective licenses. See [LICENSE](LICENSE) for the complete terms.
