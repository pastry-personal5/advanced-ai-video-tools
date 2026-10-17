# CLI user guide

The primary command is `advanced-ai-video-tools`. The deprecated
`ai-video-tools` compatibility alias remains available in version 2.0.0.

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
through `PATH` and the model directory is beside Real-ESRGAN. The Spandrel runner and
its 2×/3× models are the exception: see
[Factory-default tools and models](#factory-default-tools-and-models).

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

- `--output FILE`: choose an explicit destination: `.mp4`, or for `--pipeline concat`
  the first clip's own `.mp4` or `.mov` suffix.
- `--height PIXELS`: select the exact output height; the default is `2160`. It is
  ignored by `--pipeline concat` and `--pipeline native`.
- `--pipeline {auto,concat,native,4x-resize,2x-3x-resize}`: choose the processing
  pipeline (see below); the default is `auto`.
- `--scale {2,3,4}`: the native scale; required for, and only valid with,
  `--pipeline native`.
- `--spandrel-runner`, `--model-2x`, `--model-3x`: the Spandrel runner executable and
  its `.safetensors` or `.pth` checkpoints. They are accepted only by a pipeline that can run
  a Spandrel pass (`native` with 2 or 3, or `2x-3x-resize`).
- `--no-overwrite`: refuse to replace an existing destination.
- `--acknowledge-dropped-streams`: accept preflight-listed extra streams being
  dropped.
- `--allow-mixed-color-tags`: explicitly allow untagged clips when every
  declared supported SDR matrix, transfer, and primaries tag agrees. Use this
  only when you know the untagged footage matches that declared profile.
- `--json`: emit one machine-readable terminal result.
- `--ffmpeg`, `--ffprobe`, `--realesrgan`, `--model-dir`: configure explicit
  user-managed tool locations. `--model` still accepts only `realesrgan-x4plus`;
  Spandrel checkpoints are never passed through it.

Text mode writes measured progress to stderr and the result to stdout. JSON
mode emits a machine-readable terminal result. Exit statuses are:

- `0`: success
- `1`: processing failure
- `2`: preflight rejection
- `130`: cooperative Ctrl-C cancellation

Press `Ctrl-C` once to request cancellation. The active child process is
terminated cooperatively, owned temporary state is cleaned up, and an existing
published output is preserved on failure or cancellation.

## Choose a processing pipeline

| `--pipeline` | What runs after the clips are checked | Uses `--height` |
| --- | --- | --- |
| `auto` (default) | Real-ESRGAN scale chosen from the height, then one resize | yes |
| `concat` | Stream-copies compatible `.mp4`/`.mov` clips; no AI, no re-encode | no |
| `native` | One AI pass at the model's own scale (`--scale 2`, `3`, or `4`) | no |
| `4x-resize` | Real-ESRGAN 4×, then one resize | yes |
| `2x-3x-resize` | Spandrel 2×, then Spandrel 3×, then one resize | yes |

The CLI never reads the GUI's saved settings, so omitted flags mean `auto` and a
2160 px height. `preflight` shows the resolved output size, the ordered passes,
whether AI is skipped, and the tool and model paths it would use, in both text and
`--json` (`pipeline`, `native_scale`, `ai_scale`, `ai_skipped`, `ai_summary`, `passes`).
Existing fields keep their meaning for `auto`.

- Explicit resize pipelines skip AI when the source is already at least as tall as
  `--height`, and reject a `--height` above their native result (4× or 6× of the
  source) rather than enlarging past it.
- `native` runs even for a tall source. Its output height is the source height times
  the scale, so an odd result (for example 3× of a 1081-pixel source) is rejected.
- `concat` is the only pipeline that can write `.mov`. Clips that would need
  normalization, padding, trimming, or frame-rate conversion are rejected with the
  exact reason instead of being re-encoded.
- Spandrel passes need the user-installed runner and `.safetensors` or `.pth` models
  (`.pth` is read only by a restricted tensor-only loader; TorchScript `.pt` and
  `.ckpt` are refused), for example:

```bash
uv run advanced-ai-video-tools process \
  --input clip.mp4 --output-dir ./output \
  --pipeline 2x-3x-resize --height 2160 \
  --spandrel-runner tools/spandrel-runner/spandrel-runner \
  --model-2x /models/2xPublic_realplksr_dysample_layernorm_real_nn.pth \
  --model-3x /models/DAT_x3_bf16.safetensors
```

The runner requires Apple Silicon MPS and never falls back to the CPU. The supplied
DAT models are slow on MPS and the runner publishes a conservative maximum input size;
preflight rejects a pass above it with the exact dimensions. Text-mode progress shows
`pass=N/M scale=Kx` for the single aggregate `upscale` stage.

### Factory-default tools and models

| Scale | Tool | Model |
| --- | --- | --- |
| 2× | `spandrel-runner` (`tools/spandrel-runner/spandrel-runner`) | `2xPublic_realplksr_dysample_layernorm_real_nn.pth` (PLKSR, float32) |
| 3× | `spandrel-runner` (`tools/spandrel-runner/spandrel-runner`) | `DAT_x3_bf16.safetensors` (DAT, bfloat16) |
| 4× | `realesrgan-ncnn-vulkan` | `realesrgan-x4plus` |

Omit `--spandrel-runner`, `--model-2x`, and `--model-3x` to use these defaults; 4× uses
`realesrgan-x4plus`, the `--model` default. The runner is always the checkout's
`tools/spandrel-runner/spandrel-runner` and is never looked up on `PATH`. The default
models are the files above inside the `models` directory beside the runner, which is
`tools/spandrel-runner/models/` for the default runner and moves with an explicit
`--spandrel-runner`. A flag you pass always wins. A missing default file is a preflight
error that names the expected path and the flag that overrides it, and it never affects a
pipeline that does not run that pass. The model files remain user-supplied, and the
defaults resolve against the source checkout, not the working directory.

## Processing behavior

The pipeline probes all inputs, normalizes incompatible clips when required,
concatenates once, extracts a single frame sequence, optionally runs the
selected AI pass (two only for `2x-3x-resize`), encodes the final MP4, verifies it, and publishes it
atomically. It preserves aspect ratio and does not rotate, crop, or stretch
media implicitly.

Inputs must use supported SDR color metadata. By default, clips may not mix
missing and declared color tags; use the explicit flag above only for known
matching untagged footage. Extra audio, subtitles,
chapters, and attachments require explicit acknowledgement before being
dropped. Failed jobs retain a diagnostic workspace; successful and cancelled
jobs remove owned temporary workspaces.
