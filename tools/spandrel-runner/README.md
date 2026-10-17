# Spandrel runner

`spandrel-runner` is an external, user-installed, MPS-only PNG batch runner.
It is deliberately separate from the application package: it does not download
models, discover inputs, choose output directories, or fall back to CPU.

Install its workspace dependencies, then inspect a user-supplied `.safetensors`
2× or 3× RGB super-resolution checkpoint:

```bash
uv run --package spandrel-runner python tools/spandrel-runner/main.py inspect \
  --model /absolute/path/model.safetensors \
  --protocol-version 1
```

The inspection result is one JSON object. It reports the protocol and runner
versions, a file identity, descriptor details, model scale and size
requirements, the direct-inference pixel limit, and the fixed MPS/float32
execution policy. Pickle-based `.pth` and `.pt` files are intentionally rejected.

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

The runner retains single-frame, float32 MPS inference while overlapping a
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

The existing converter remains a separate maintenance utility for the supplied
`.pth` prototype model; it is not accepted by `spandrel-runner inspect` or
`run`:

```bash
tools/spandrel-runner/convert_fp16_to_bf16.sh input.pth output-bf16.pth
```

It uses `torch.load(..., weights_only=True)` and never falls back to
unrestricted pickle loading.
