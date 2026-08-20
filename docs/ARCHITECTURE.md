# Architecture

This document is the authoritative technical overview for AI Video Tools. It describes the intended architecture while the repository is in its foundation stage. Update it when an implementation decision changes the pipeline, component boundaries, job states, or media policies.

## Design goals

- Provide one reliable processing pipeline through both a CLI and desktop GUI.
- Concatenate clips before AI upscaling so Real-ESRGAN runs once per job.
- Preserve source streams without re-encoding when concat inputs are compatible.
- Keep the GUI responsive and make progress, cancellation, errors, and cleanup predictable.
- Keep external command construction isolated and independently testable.
- Never overwrite user input or publish an incomplete output.

## Version 1 platform

Version 1 requires macOS 26.5.2 or later on Apple Silicon and uses PySide6 for the GUI. Set the application deployment target accordingly and reject unsupported systems during preflight with a clear message. The reference machine is an Apple M5 Max with 128 GB unified memory. Treat that machine as the performance and validation baseline, not as a minimum hardware requirement and not as permission to use unbounded memory.

macOS releases older than 26.5.2, Intel Macs, Windows, and Linux are outside the v1 support contract. Keep path handling and process adapters portable where doing so is natural, but do not add untested cross-platform branches or compatibility abstractions.

FFmpeg, FFprobe, `realesrgan-ncnn-vulkan`, its model files, and required Vulkan support are user-managed prerequisites. The application must not bundle, install, update, or automatically download them. Resolve explicit configured paths before `PATH` and validate the resolved tools during preflight.

## Key decision: concat first, upscale once

Each job creates one merged media timeline before frame extraction or AI processing. Source clips are never upscaled individually.

For compatible clips, FFmpeg's concat demuxer joins streams with stream copy. This is lossless and avoids an unnecessary encode. The relevant streams must match, including codec, time base, resolution, frame rate, pixel format, and audio layout.

When clips are incompatible, the pipeline normalizes them to one explicit intermediate specification and then concatenates the normalized results. Normalization is a compatibility step, not AI upscaling. The merged result is still upscaled once.

This approach provides one frame-number sequence, one audio timeline, one Real-ESRGAN invocation, and one final encoding policy for the whole job.

## Default media profile

Defaults must be explicit in the typed job model and overridable by the CLI and GUI.

| Stage | Version 1 default |
| --- | --- |
| Normalization container | Matroska |
| Normalization video | Lossless FFV1 |
| Normalization audio | Lossless PCM, 48 kHz, selected primary channel layout |
| Common canvas | First clip's resolution; preserve aspect ratio and pad |
| Constant frame rate | First clip's frame rate |
| Frame sequence | Lossless PNG with deterministic zero-padded names |
| Final container | MP4 with fast-start metadata |
| Final video | `libx264`, CRF 18, slow preset, `yuv420p` |
| Final audio | Stream copy when MP4-compatible; otherwise AAC-LC, 256 kbit/s, 48 kHz |

Mixed resolution, aspect ratio, frame rate, variable frame rate, or channel layout triggers a visible normalization warning. Never crop, stretch, discard a stream, or change timing silently. Extra audio streams, subtitles, chapters, and attachments require an explicit policy; until supported, report them before processing and require acknowledgement rather than silently dropping them.

## System boundaries

```text
CLI ─────┐
         ├──> Job model ──> Pipeline service ──> Progress/events
GUI ─────┘                       │
                                ├──> FFprobe adapter
                                ├──> FFmpeg adapter
                                ├──> Real-ESRGAN adapter
                                └──> Workspace/output manager
```

- **CLI:** parses arguments, creates a typed job request, and renders progress and errors. It contains no media-processing logic.
- **GUI:** creates the same typed job request and consumes the same progress events. It contains no backend command construction.
- **Job model:** holds validated inputs, output policy, concat and normalization settings, frame rate, model, scale, device, tiling, encoding, audio, temporary-file, and overwrite policies.
- **Pipeline service:** owns stage transitions, orchestration, cancellation, error translation, and cleanup.
- **Process adapters:** build argument arrays, launch external tools without a shell, parse progress, capture diagnostic output, and translate exit failures.
- **Workspace/output manager:** owns job-specific temporary paths, verifies ownership before cleanup, and atomically publishes the final output.

## Pipeline stages

### 1. Validate

- Resolve FFmpeg, FFprobe, and `realesrgan-ncnn-vulkan` from explicit configuration first, then `PATH`.
- Verify that resolved executables can launch on Apple Silicon and that the Real-ESRGAN installation can access a working Vulkan device and its selected model files.
- Do not install, download, update, or modify external tools as part of preflight.
- Validate readable inputs, distinct output, overwrite policy, model files, scale, Vulkan device, and workspace.
- Estimate required temporary space when practical; frame sequences can be substantially larger than their source videos.
- Freeze the effective job configuration before starting so logs and retries are reproducible.

### 2. Probe

Run FFprobe for every input and parse machine-readable output. Record:

- Video and audio stream selection
- Codec, dimensions, sample aspect ratio, and pixel format
- Average and real frame rates, time base, duration, and start time
- Audio codec, sample rate, channel layout, and duration
- Rotation and other metadata that affects rendered orientation

Do not select concat or normalization behavior from filename extensions.

### 3. Normalize when required

Compare the probed streams against the concat compatibility policy. If they do not match, transcode each incompatible input to one documented intermediate specification.

The default normalization profile is Matroska with lossless FFV1 video and lossless PCM audio at 48 kHz. Use the first clip's resolution, frame rate, and primary channel layout unless the job overrides them. Preserve aspect ratio by padding; never stretch or crop silently.

### 4. Concatenate

Create a safely escaped concat manifest in the job workspace and invoke FFmpeg with an argument list, never a shell command string.

- Use concat-demuxer stream copy for compatible source or normalized clips.
- Respect the user-defined clip order.
- Produce one merged working video before continuing.
- Verify successful exit, expected streams, readable duration, and a plausible timeline.

### 5. Extract frames and audio

- Decode the merged video into one lossless PNG sequence.
- Use a single zero-padded naming convention that preserves lexical and numeric order.
- Choose and record an explicit constant output frame rate. Variable-frame-rate conversion must be visible to the user.
- Extract or map the selected concatenated audio independently for later muxing.
- Record the expected frame count for validation after upscaling.

### 6. Upscale once

Invoke `realesrgan-ncnn-vulkan` with the extracted directory as input and one output directory. Pass model, scale, GPU, tile size, thread settings, and image format explicitly.

Use directory processing rather than one subprocess per frame. If GPU memory exhaustion supports a retry, use a bounded and logged tile-size reduction policy. Do not silently switch to another Real-ESRGAN implementation or promise a CPU fallback.

Before encoding, verify that output frame numbers match the input set exactly. Missing, duplicate, unreadable, or unexpected frames fail the stage.

### 7. Encode and mux

- Encode the upscaled sequence at the recorded output frame rate. The default is MP4 using `libx264`, CRF 18, the slow preset, `yuv420p`, and fast-start metadata.
- Apply explicit video codec, quality, pixel format, and color metadata policies even when defaults are used.
- Copy the selected primary audio stream when it is compatible with MP4; otherwise encode AAC-LC at 256 kbit/s and 48 kHz.
- Define behavior for no audio, multiple audio streams, subtitles, chapters, and attachments; do not rely on implicit FFmpeg selection.
- Write to a partial output located on the destination filesystem.

### 8. Verify, publish, and clean up

Probe the partial output and verify readable streams, nonzero duration, expected dimensions, expected frame rate, and audio presence according to policy. Only then atomically rename it to the requested destination.

On success, failure, or cancellation, terminate owned child processes and delete only job-owned temporary artifacts. A diagnostic retention option may preserve the workspace, but its location must be reported clearly.

## Job state model

The pipeline should expose explicit states:

```text
queued
  → validating → probing → normalizing? → concatenating
  → extracting → upscaling → encoding → verifying → publishing
  → completed
```

From any active stage, the job may move through `cancelling` to `cancelled`, or to `failed`. Cleanup is a guaranteed finalization action, not a state that hides the terminal result.

Progress events include the job ID, stage, measured completed work, measured total when known, and a human-readable message. Unknown totals use indeterminate progress instead of guessed percentages.

## Failure and safety rules

- Pass subprocess commands as argument arrays with `shell=False`.
- Capture enough stderr for diagnosis without exposing secrets or flooding the GUI.
- Treat nonzero exit codes, malformed probe output, missing frames, and failed output verification as typed failures.
- Cancellation must terminate the active process tree and wait for termination before workspace deletion.
- Never modify or delete source inputs.
- Never overwrite an existing destination without the job's explicit overwrite policy.
- Avoid loading full videos or unbounded frame batches into Python memory.

## Testing boundaries

- Unit-test job validation, compatibility decisions, command construction, state transitions, progress parsing, path escaping, and cleanup ownership with process fakes.
- Integration-test FFprobe, concat, extraction, and encoding with tiny generated media fixtures.
- Contract-test the Real-ESRGAN adapter with a fake executable that copies or transforms small image fixtures predictably.
- Test orchestration without a GUI, GPU, network, or real model weights.
- Reserve end-to-end Vulkan tests for an explicitly marked hardware-enabled suite.

The same pipeline contract must pass whether a job originates from the CLI or GUI.
