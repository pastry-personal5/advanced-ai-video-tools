# Architecture

This document is the authoritative technical overview for AI Video Tools. It describes both the implemented foundation and the intended processing architecture. Update it when an implementation decision changes the pipeline, component boundaries, job states, or media policies.

## Implementation status

The current CLI slice ends after preflight. The video backend can construct and
integration-test normalization and concat operations, but no application
service executes a complete user job yet. Frame extraction, upscaling, final
encoding, publication, cancellation, and GUI work remain unimplemented. The
implemented boundaries are:

- `core.models`: immutable job intent, exact rationals, typed stream inventory,
  issue codes, concat strategy, and frozen execution plans
- `storage.naming`: timezone-aware automatic names and process-local destination
  reservation with filesystem collision checks
- `storage.paths`: Qt-standard application data and cache locations
- `system.platform`: macOS 26.5.2 and Apple Silicon support gate
- `system.tools`: explicit-path-first discovery, executable inspection, x4plus
  model-pair validation, and a cached 16 × 16 inference smoke test that proves
  the Real-ESRGAN Vulkan backend can create output
- `video.probe`: pure FFprobe arguments, bounded invocation, and defensive typed JSON parsing
- `video.compatibility`: typed stream-copy findings and normalize-all-or-none strategy selection
- `video.manifest`: ordered absolute concat paths with FFmpeg token escaping
- `video.commands`: lossless normalization, concat arguments, and a typed media-preparation plan
- `video.policy`: shared SDR BT.709 predicates used by preflight and command builders
- `services.preflight`: shared path, media-policy, sizing, concat-strategy, audio,
  and disk-margin validation
- `cli`: human-readable and JSON preflight reports

The Vulkan smoke test uses an owned temporary directory, explicitly selects
`realesrgan-x4plus`, and uses a 32-pixel diagnostic tile. It does not change the
processing default of automatic tiling. Unit tests replace external processes,
so the normal test suite remains independent of GPU hardware and model files.

## Design goals

- Provide one reliable processing pipeline through both a CLI and desktop GUI.
- Optimize photographic and live-action footage; anime, animation, illustration, and synthetic line art are outside the v1 product scope.
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

When clips are incompatible, the pipeline normalizes them to one explicit intermediate specification and then concatenates the normalized results. Normalization is a compatibility step, not AI upscaling. When the merged result is below the requested height, it is upscaled once.

This approach provides one frame-number sequence, one audio timeline, at most one Real-ESRGAN invocation, and one final encoding policy for the whole job.

## Default media profile

Defaults must be explicit in the typed job model and overridable by the CLI and GUI only within the supported real-image product scope.

| Stage | Version 1 default |
| --- | --- |
| Normalization container | Matroska |
| Normalization video | Lossless FFV1 level 3, `yuv444p10le` |
| Normalization audio | Lossless `pcm_s24le`, 48 kHz, selected primary channel layout |
| Color | SDR BT.709 only |
| Color range | Limited/TV; explicitly convert accepted full-range input |
| Common canvas | First clip's resolution; preserve aspect ratio and pad |
| Rotation | Unsupported; reject nonzero metadata and disable auto-rotation |
| Constant frame rate | First clip's exact rational rate |
| Frame sequence | Lossless PNG with deterministic zero-padded names |
| Real-ESRGAN model | `realesrgan-x4plus` |
| Final display height | 2160 pixels |
| Final display width | Derived from coded dimensions and sample aspect ratio, then rounded to an even integer |
| Final container | MP4 with fast-start metadata |
| Final video | `libx264`, CRF 18, slow preset, `yuv420p` |
| Final audio | First audio stream; copy only when unchanged and MP4-compatible, otherwise AAC-LC, 256 kbit/s, 48 kHz |

Mixed resolution, aspect ratio, frame rate, variable frame rate, or channel layout triggers a visible normalization warning. Never crop, stretch, discard a stream, or change timing silently. Report extra audio streams, subtitles, chapters, and attachments before processing and drop them only after explicit acknowledgement.

### Output sizing

Treat target height, not raw AI scale, as the user-facing sizing control. The default target is 2160 pixels.

Calculate output width from coded dimensions and sample aspect ratio. Supported inputs have no rotation transform:

```text
source_aspect_ratio = (coded_width × sample_aspect_ratio) ÷ coded_height
raw_width = target_height × source_aspect_ratio
output_width = nearest even integer to raw_width
```

Both final dimensions must be positive and even for the default `yuv420p` profile. FFmpeg's equivalent aspect-preserving rule is `scale=-2:2160`. Record the resolved dimensions in the frozen job configuration and show them before processing.

Version 1 never rotates video. Reject nonzero rotation or display-matrix metadata during preflight, pass `-noautorotate` on every FFmpeg input, and expose no rotation filter or user control. Inputs must already be upright. Preserve aspect ratio through proportional scaling and padding only; cropping and stretching are unsupported.

For input below the target, choose the smallest supported Real-ESRGAN scale in 2×, 3×, or 4× whose intermediate height reaches or exceeds the target. Resize that intermediate once during final encoding to reach the exact output dimensions. If even 4× is below the target, use 4× and warn that final sizing includes conventional FFmpeg enlargement.

For input at or above the target height, skip Real-ESRGAN by default and resize directly to the requested dimensions. A future explicit enhancement mode may allow AI processing without enlargement, but it is not part of the v1 default.

### Color policy

Version 1 supports SDR BT.709 only. Probe color primaries, transfer characteristics, matrix coefficients, range, pixel format, and mastering metadata before processing.

- Reject detected PQ, HLG, BT.2020, HDR mastering metadata, and other explicit HDR or unsupported wide-gamut signaling with an actionable message.
- Accept explicitly tagged SDR BT.709.
- When color tags are absent, unknown, or internally inconsistent, require user acknowledgement before interpreting the input as BT.709.
- Convert BT.709 YUV to the RGB PNG frame representation explicitly, then convert processed RGB frames back to BT.709 for encoding.
- Tag the final stream explicitly with BT.709 primaries, transfer characteristics, and matrix coefficients. Do not tone-map, gamut-map, or retag silently.

### Audio and secondary-stream policy

Select the first audio stream from each clip. The first available selected stream in input order defines the normalized channel layout. If no input contains audio, omit audio from the final output.

Preserve the video timeline as authoritative:

- Insert matching PCM silence for a clip with no audio when the job otherwise contains audio.
- Pad a selected audio stream that ends before its clip's video duration.
- Trim a selected audio stream that exceeds its clip's video duration.
- After concat, pad or trim once more if necessary so final audio duration matches final video duration.

Additional audio streams, subtitles, chapters, and attachments are unsupported in v1. Inventory them during probe, show exactly what will be dropped, and require explicit acknowledgement in the GUI or CLI before processing. Stream-copy audio only when no padding, trimming, resampling, layout conversion, or container conversion is required; otherwise encode with the default AAC-LC profile.

## Operational defaults

### Queue and concurrency

Run one processing job at a time. Additional jobs remain in an in-memory FIFO queue and may be reordered or removed before they start. Do not run concurrent FFmpeg or Real-ESRGAN pipelines. A cancelled active job reaches `cancelled` before the next queued job starts.

Version 1 does not resume partial jobs. Restart failed, cancelled, or interrupted jobs from the beginning.

### Output replacement

Overwrite an existing destination by default. Never truncate or remove it when the job starts: write the complete result to a partial file on the destination filesystem, verify that partial file, then atomically replace the destination. Failure or cancellation before publication leaves the existing destination unchanged. Successful replacement does not keep a backup.

The CLI provides `--no-overwrite`, and the GUI provides an overwrite setting that is enabled by default. In no-overwrite mode, reject an existing destination during preflight and recheck immediately before publication to detect a file created while the job was running.

### Automatic output naming

Generate the default output basename when the job is created, not when processing starts or finishes. Use the timezone-aware local wall clock and this ASCII-only format:

```text
ai-video-YYYYMMDD-HHMMSS-ffffffZZZZ.mp4
```

For example: `ai-video-20260821-143052-123456+0900.mp4`.

- `ai-video-` is the fixed prefix.
- `ffffff` is six-digit microsecond precision.
- `ZZZZ` is the signed numeric local UTC offset, such as `+0900` or `-0700`, which disambiguates repeated wall-clock times.
- The selected output directory remains separate from the generated basename. The CLI uses `--output-dir`; the GUI exposes an output-directory picker.
- Capture and freeze the timestamp, offset, basename, and resolved path in the job model so queued jobs do not change names later.
- Reserve the resolved path against both the filesystem and all queued or active jobs. If it collides, append `-01`, `-02`, and so on before `.mp4` until a free path is reserved.
- Automatically generated paths never replace an older output. The general default-overwrite policy applies only to an explicit user-supplied destination path.

### Workspace and disk safety

Resolve the cache root with `QStandardPaths.StandardLocation.CacheLocation`; on macOS the intended job root is `~/Library/Caches/AI Video Tools/jobs/`. Create one randomly identified, ownership-marked directory per job.

Before starting, calculate a conservative peak-disk estimate covering normalized clips, the merged intermediate, input and output PNG sequences, partial output, and process overhead. Require available space of at least `estimated_peak × 1.20`. Refuse to start when the estimate cannot be computed or the margin is unavailable.

- Delete the owned workspace after success.
- Delete it after cancellation once all child processes have terminated.
- Retain it after failure and report its path for diagnosis.
- Never treat an unmarked directory as an owned workspace, and never recursively delete outside the configured job root.

### Real-ESRGAN runtime

- Use automatic GPU selection by omitting `-g`.
- Start with automatic tiling via `-t 0`.
- Use executable-default worker threads by omitting `-j`.
- Disable TTA by omitting `-x`.
- Retry only a recognized Vulkan allocation or out-of-memory failure. After the automatic attempt, retry with tile sizes `512`, `256`, `128`, `64`, then `32`, stopping after the first success.
- Before each retry, delete and recreate only the owned upscale-output directory so partial frames cannot be mistaken for a complete result.
- Record every attempt, resolved device, tile size, and failure. Do not retry unrelated errors or loop beyond the defined sequence.

### Configuration, logs, and networking

Resolve persistent configuration with `QStandardPaths.StandardLocation.AppDataLocation`, corresponding to `~/Library/Application Support/AI Video Tools/` on macOS. Store executable paths, recent locations, and user preferences there; do not store credentials or model binaries.

Write local logs under the application-data directory. Rotate at 10 MiB with five backup files, redact sensitive path or environment data where practical, and expose the log location in the GUI and CLI diagnostics.

Version 1 performs no telemetry, analytics, crash uploads, update checks, or other application-initiated network requests.

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
- **Job model:** holds validated inputs, output directory, frozen creation time and generated basename, reserved destination, output policy, concat and normalization settings, color interpretation and range, rational frame rate, target height, resolved dimensions, model, resolved AI runtime, encoding, selected audio, dropped-stream acknowledgement, workspace, retention, and overwrite mode, which defaults to replace for explicit paths.
- **Pipeline service:** owns stage transitions, orchestration, cancellation, error translation, and cleanup.
- **Process adapters:** build argument arrays, launch external tools without a shell, parse progress, capture diagnostic output, and translate exit failures.
- **Workspace/output manager:** owns job-specific temporary paths, verifies ownership before cleanup, and atomically publishes the final output.

## Pipeline stages

### 1. Validate

- Resolve FFmpeg, FFprobe, and `realesrgan-ncnn-vulkan` from explicit configuration first, then `PATH`.
- Verify that resolved executables can launch on Apple Silicon and that the Real-ESRGAN installation can access a working Vulkan device and its selected model files.
- Require the `realesrgan-x4plus` parameter and binary files and resolve them during preflight. Never inherit the executable's default model implicitly.
- Do not install, download, update, or modify external tools as part of preflight.
- Validate readable inputs, zero or absent rotation metadata, writable output directory, frozen and reserved destination, overwrite mode, model files, target height, resolved dimensions, AI scale, Vulkan device, owned workspace, conservative disk estimate, and 20% free-space margin.
- Reject detected HDR or unsupported wide gamut. Require acknowledgement for missing or ambiguous color tags and for every unsupported secondary stream that will be dropped.
- Calculate a conservative peak temporary-space estimate; frame sequences can be substantially larger than their source videos.
- Freeze the effective job configuration before starting so logs and retries are reproducible.

### 2. Probe

Run FFprobe for every input and parse machine-readable output. Record:

- Video and audio stream selection
- Codec, dimensions, sample aspect ratio, and pixel format
- Average and real frame rates as exact rationals, time base, duration, and start time
- Audio codec, sample rate, channel layout, and duration
- Color primaries, transfer characteristics, matrix coefficients, range, pixel format, and HDR mastering metadata
- Rotation and other metadata that affects rendered orientation
- All additional audio, video, subtitle, chapter, and attachment streams

Do not select concat or normalization behavior from filename extensions.

### 3. Normalize when required

Compare the probed streams against the concat compatibility policy. If every clip is compatible, retain every source for direct concat stream copy. If any clip is incompatible, normalize every clip into the same intermediate profile before concat; mixing untouched source codecs with FFV1 normalized clips would not be stream-copy compatible.

Full-range color, VFR timing, missing required audio, or audio-duration mismatch forces normalization even when codec and stream layouts would otherwise be concat-compatible. Nonzero rotation metadata fails preflight instead of entering normalization.

The default normalization profile is Matroska with FFV1 level 3 `yuv444p10le` video and `pcm_s24le` audio at 48 kHz. Use the first clip's coded resolution, sample aspect ratio, and exact frame rate plus the first available primary audio channel layout unless the job overrides them. Use quality-first Lanczos scaling, preserve display aspect ratio by padding, and never stretch or crop silently. Normalized clips use deterministic six-digit names such as `clip-000001.mkv`.

Resolve the first clip's exact rational frame rate without converting through floating point. Preserve its CFR rate directly; for a VFR first clip, use FFprobe's valid rational average frame rate. Normalize every clip to that rational rate and report the conversion. For example, preserve `30000/1001` rather than rounding it to `29.97` or `30`.

Pass `-noautorotate` for every FFmpeg input and do not add rotation filters. Convert accepted full-range BT.709 input explicitly to limited/TV range; do not relabel range metadata without converting sample values.

When the job contains audio, normalize the first audio stream from each clip. Insert silence for clips without audio, pad short streams, and trim long streams to each clip's authoritative video duration before concat.

### 4. Concatenate

Create a UTF-8 concat manifest in the job workspace using ordered, absolute, safely token-escaped paths. Reject NUL and newline characters, invoke the concat demuxer with `-safe 0`, and pass FFmpeg an argument list rather than a shell command string.

- Use concat-demuxer stream copy for compatible source or normalized clips.
- Respect the user-defined clip order.
- Produce one merged working video before continuing.
- Verify successful exit, expected streams, readable duration, and a plausible timeline.

### 5. Extract frames and audio

- Decode the merged video into one lossless PNG sequence.
- Pass `-noautorotate` during frame extraction and verify that no rotation transform reaches the output.
- Perform explicit BT.709 YUV-to-RGB conversion for the PNG sequence; do not rely on unspecified automatic color interpretation.
- Use a single zero-padded naming convention that preserves lexical and numeric order.
- Choose and record an explicit constant output frame rate. Variable-frame-rate conversion must be visible to the user.
- Extract or map the concatenated primary audio independently for later muxing and retain its exact relationship to the video timeline.
- Record the expected frame count for validation after upscaling.

### 6. Upscale once

When the merged input is below the target height, invoke `realesrgan-ncnn-vulkan` with the extracted directory as input and one output directory. Pass `-n realesrgan-x4plus`, the resolved AI scale, `-t 0`, and PNG output explicitly. Omit `-g`, `-j`, and `-x` to use automatic GPU selection, executable-default threads, and disabled TTA. Skip this stage when the input is already at or above the target height.

Do not expose anime-specific models in the v1 CLI, GUI, or configuration. Reject an anime model name with a clear validation error rather than silently substituting it.

Use directory processing rather than one subprocess per frame. Retry only recognized Vulkan memory failures with the defined `512 → 256 → 128 → 64 → 32` tile sequence. Do not silently switch to another Real-ESRGAN implementation or promise a CPU fallback.

Before encoding, verify that output frame numbers match the input set exactly. Missing, duplicate, unreadable, or unexpected frames fail the stage.

### 7. Encode and mux

- Resize the processed sequence to the resolved even width and exact target height while preserving the source aspect ratio. Never crop or stretch. Encode at the recorded output frame rate. The default is MP4 using `libx264`, CRF 18, the slow preset, `yuv420p`, and fast-start metadata.
- Convert RGB frames explicitly to BT.709 YUV and set BT.709 primaries, transfer, and matrix metadata on the final stream.
- Copy the selected primary audio only when it is unchanged and compatible with MP4; otherwise encode AAC-LC at 256 kbit/s and 48 kHz.
- Pad final audio with silence or trim it so its duration matches the authoritative final video timeline. Omit audio when every input is silent.
- Map only supported streams explicitly; never rely on FFmpeg's implicit stream selection.
- Write to a partial output located on the destination filesystem.

### 8. Verify, publish, and clean up

Probe the partial output and verify readable streams, nonzero duration, expected dimensions, expected frame rate, no rotation transform, explicit BT.709 signaling, expected audio presence, and audio/video duration agreement. Only then atomically replace the requested destination. Preserve any existing destination until this publication step succeeds.

On success or cancellation, terminate owned child processes and delete only the owned job workspace. On failure, retain the workspace and report its path clearly. Version 1 does not resume it.

## Job state model

The pipeline exposes a FIFO queue with one active job and these explicit states:

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
- Default to atomic destination replacement after verification for explicit paths. Never truncate the existing file early. In no-overwrite mode, reject collisions during preflight and recheck immediately before publication. Generated paths must be uniquely reserved and never overwrite an earlier output.
- Avoid loading full videos or unbounded frame batches into Python memory.

## Testing boundaries

- Unit-test job validation, compatibility decisions, command construction, state transitions, progress parsing, path escaping, and cleanup ownership with process fakes.
- Unit-test timezone-aware automatic names, microsecond formatting, UTC offsets, queued-path reservations, numeric collision suffixes, exact rational frame-rate handling, nonzero-rotation rejection, `-noautorotate` command construction, aspect-ratio preservation, full-to-limited range conversion decisions, default atomic replacement for explicit paths, preservation of the old file on failure, no-overwrite races, disk-margin rejection, FIFO scheduling, workspace retention, log rotation, and the bounded tile retry sequence.
- Integration-test FFprobe, concat, extraction, and encoding with tiny generated media fixtures.
- Contract-test the Real-ESRGAN adapter with a fake executable that copies or transforms small image fixtures predictably.
- Test orchestration without a GUI, GPU, network, or real model weights.
- Reserve end-to-end Vulkan tests for an explicitly marked hardware-enabled suite.

The same pipeline contract must pass whether a job originates from the CLI or GUI.
