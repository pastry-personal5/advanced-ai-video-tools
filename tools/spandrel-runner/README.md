# Spandrel runner

`spandrel-runner` is an external, user-installed, MPS-only PNG batch runner.
It is deliberately separate from the application package: it does not download
models, discover inputs, choose output directories, or fall back to CPU.

Install its workspace dependencies, then inspect a user-supplied `.safetensors` or
`.pth` 2× or 3× RGB super-resolution checkpoint:

```bash
uv run --package spandrel-runner python tools/spandrel-runner/main.py inspect \
  --model /absolute/path/model.safetensors \
  --protocol-version 1
```

The inspection result is one JSON object. It reports the protocol and runner
versions, a file identity, descriptor details, model scale and size
requirements, the direct-inference pixel limit, the MPS device, and the execution
precision. A `.pth` is loaded only through Spandrel's restricted state-dict
unpickler (a test proves a booby-trapped file raises without running its payload);
TorchScript `.pt`, `.ckpt`, and other formats are intentionally rejected. Choose only
checkpoints you trust.

## Precision

Precision comes only from the checkpoint: if every floating-point tensor in the file is
bfloat16 the model runs in bfloat16 on MPS, otherwise in float32 (fp16-only files are
upcast, and float16 is never used). `inspect` reports it as `precision`, and an
architecture without bfloat16 support is rejected as `incompatible_model`. Input frames
are converted to the model dtype and results are rounded to 8-bit in float32. bfloat16
inference on MPS has been unit-tested on the CPU and run on MPS with the selected
`DAT_x3_bf16.safetensors` (a 4-frame, 96×72 smoke job and one 640×360 frame through the
application CLI, and the Phase 6 native suite, on 2026-10-17).

## Executable entry point

The application launches an executable, not `python main.py`. Choose
`tools/spandrel-runner/spandrel-runner` in **Settings → Tools → External Tools**
(or pass it as `--spandrel-runner`). The launcher resolves this directory's uv
environment, so it works from any working directory; the environment must already
provide the workspace's PyTorch and Spandrel packages (`uv sync --dev` at the
repository root). The application never installs or downloads them.

## Factory-default checkpoints

The factory defaults for this runner are
`2xPublic_realplksr_dysample_layernorm_real_nn.pth` (PLKSR, float32) for 2× and
`DAT_x3_bf16.safetensors` (DAT, bfloat16) for 3×, run through
`tools/spandrel-runner/spandrel-runner`, which the application never looks up on `PATH`.
When no runner or model is configured, the application uses this launcher and looks for
these files in the `models` directory beside the runner (`tools/spandrel-runner/models/`,
which is gitignored). The runner neither downloads nor bundles them, and a configured
model path always wins.

## Verified input size and performance

`inspect` publishes `maximum_input_pixels`, and the application rejects any pass
whose exact input exceeds it. The published value is only what has been run on the
supported host: on an Apple M5 Max (macOS 26.7.1, 128 GB), `DAT_x2.safetensors` and
`DAT_x3.safetensors` each ran one 640×360 (230,400 px) frame on MPS without error,
using under 2 GB of memory, but at roughly 3 minutes per frame. The selected
`2xPublic_realplksr_dysample_layernorm_real_nn.pth` and `DAT_x3_bf16.safetensors`
checkpoints each also ran one 640×360 frame on MPS on 2026-10-17 (about 4.6 s and 8.5 s
for a whole CLI job, with a peak resident set of 0.5 GB and 1.2 GB). Larger inputs have not
been run on any model and are not covered by this evidence. Direct float32 DAT inference on MPS (measured before bfloat16 support) grows
faster than linearly with pixel count and was no faster than the CPU at 128×72, so
these models are practical only for very small frames until tiling or another
backend is separately designed. Raising the limit requires new native evidence and
a runner version bump.

## Batch manifest

`run` requires a model and a JSON manifest created from `inspect`. It accepts
only an exact model identity, an existing owned output directory, and ordered
absolute RGB-PNG input/output pairs. It never derives an output filename or
accepts arbitrary output locations. A manifest becomes invalid if its model or
input file is replaced after review.

```json
{
  "protocol_version": 1,
  "model_identity": {
    "path": "/absolute/models/model.safetensors",
    "device": 16777232,
    "inode": 1242816,
    "size_bytes": 123456,
    "modified_ns": 1770000000000000000,
    "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  },
  "output_directory": "/absolute/workspace/upscaled",
  "jobs": [
    {
      "input": {
        "path": "/absolute/workspace/frames/frame-00000001.png",
        "identity": {
          "path": "/absolute/workspace/frames/frame-00000001.png",
          "device": 16777232,
          "inode": 1242817,
          "size_bytes": 45678,
          "modified_ns": 1770000000000000001,
          "sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        },
        "width": 1920,
        "height": 1080
      },
      "output": {
        "path": "/absolute/workspace/upscaled/frame-00000001.png",
        "width": 3840,
        "height": 2160
      }
    }
  ]
}
```

Run the manifest with:

```bash
uv run --package spandrel-runner python tools/spandrel-runner/main.py run \
  --model /absolute/path/model.safetensors \
  --manifest /absolute/path/jobs.json \
  --protocol-version 1
```

The runner checks MPS availability before loading the model, then validates the
entire batch—model and input identities, RGB PNG structure, dimensions, model
requirements, output dimensions, and output availability—before it starts
inference. Every output is structurally re-verified then atomically created
without replacement. It emits one line-delimited JSON progress object only
after a complete output exists. An unsupported MPS operation fails the job
rather than executing on CPU; the runner pins `PYTORCH_ENABLE_MPS_FALLBACK=0`
before importing PyTorch.

On failure, the runner emits one JSON object on standard error:

```json
{"event":"error","code":"invalid_request","message":"..."}
```

Stable error codes and exit statuses are `invalid_request` (2),
`incompatible_model` (3), `mps_unavailable` (4), `inference_failed` (5), and
`output_conflict` (6). Previously completed frames remain intact on a later
failure; the application owns cleanup of its job workspace.

## Performance behavior

The runner retains single-frame MPS inference (float32, or bfloat16 for an all-bfloat16
checkpoint) while overlapping a
bounded amount of CPU work around it. One worker decodes the next frame and one
worker encodes the previous result; no second inference runs concurrently. The
queue therefore holds at most one frame ahead and one result behind.

Each model and input receives one full SHA-256 comparison during batch
preflight. Immediately before a frame is decoded, the runner uses the already
reviewed path, device, inode, size, and modification time instead of hashing the
same PNG again. Preflight verifies PNG structure without a full pixel decode;
the processing path decodes each input once.

Inputs remain compact `uint8` CPU arrays until transfer to MPS. Outputs are
rounded and converted to `uint8` on MPS before transfer back to CPU, reducing
the result transfer to one byte per channel. Published PNGs use lossless
compression level 1 for faster intermediate-frame encoding, are structurally
verified, and retain the same no-clobber atomic publication contract.

## Checkpoint converter

The existing converter remains a separate maintenance utility for fp16 `.pth`
prototype checkpoints; its output can be used as a `.pth` model:

```bash
tools/spandrel-runner/convert_fp16_to_bf16.sh input.pth output-bf16.pth
```

It uses `torch.load(..., weights_only=True)` and never falls back to
unrestricted pickle loading.
