# CLI user guide

The primary command is `advanced-ai-video-tools`. The deprecated
`ai-video-tools` alias remains available through v2.

## Install and inspect commands

```bash
uv sync --dev
uv run advanced-ai-video-tools --help
uv run advanced-ai-video-tools preflight --help
uv run advanced-ai-video-tools process --help
```

## Preflight a job

```bash
uv run advanced-ai-video-tools preflight \
  --input clip-01.mp4 \
  --input clip-02.mp4 \
  --output-dir ./output \
  --realesrgan /path/to/realesrgan-ncnn-vulkan \
  --model-dir /path/to/models \
  --json
```

Repeat `--input` for each clip; arguments are processed in the order given.
Executable and model-directory overrides are optional when tools are available
through `PATH` and the model directory is beside Real-ESRGAN.

Preflight does not modify media. It exits with status `0` when ready and `2`
when a blocking issue remains. It reserves a generated destination only for
the duration of the command.

## Process a job

```bash
uv run advanced-ai-video-tools process \
  --input clip-01.mp4 \
  --input clip-02.mp4 \
  --output-dir ./output \
  --height 2160 \
  --realesrgan /path/to/realesrgan-ncnn-vulkan \
  --model-dir /path/to/models
```

Useful options:

- `--output FILE`: choose an explicit MP4 destination.
- `--height PIXELS`: select the exact output height; the default is `2160`.
- `--no-overwrite`: refuse to replace an existing destination.
- `--acknowledge-dropped-streams`: accept preflight-listed extra streams being
  dropped.
- `--json`: emit one machine-readable terminal result.
- `--ffmpeg`, `--ffprobe`, `--realesrgan`, `--model-dir`: configure explicit
  user-managed tool locations.

Text mode writes measured progress to stderr and the result to stdout. JSON
mode emits a machine-readable terminal result. Exit statuses are:

- `0`: success
- `1`: processing failure
- `2`: preflight rejection
- `130`: cooperative Ctrl-C cancellation

Press `Ctrl-C` once to request cancellation. The active child process is
terminated cooperatively, owned temporary state is cleaned up, and an existing
published output is preserved on failure or cancellation.

## Processing behavior

The pipeline probes all inputs, normalizes incompatible clips when required,
concatenates once, extracts a single frame sequence, optionally runs
Real-ESRGAN once, encodes the final MP4, verifies it, and publishes it
atomically. It preserves aspect ratio and does not rotate, crop, or stretch
media implicitly.

Inputs must use supported explicit SDR color metadata. Extra audio, subtitles,
chapters, and attachments require explicit acknowledgement before being
dropped. Failed jobs retain a diagnostic workspace; successful and cancelled
jobs remove owned temporary workspaces.

