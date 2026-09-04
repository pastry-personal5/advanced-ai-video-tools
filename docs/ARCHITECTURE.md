# Architecture

This document is the authoritative technical overview for Advanced AI Video Tools. It describes both the implemented foundation and the intended processing architecture. Update it when an implementation decision changes the pipeline, component boundaries, job states, or media policies.

## Development target

Version 1.0.0 is the completed release baseline. Version 2 is complete, and
v3 Phase 2 is complete after the Phase 1 refactoring. Until an approved v3
design decision explicitly supersedes a v2 contract, the implemented v2
behavior in this document remains binding. The target change alone does not
authorize speculative features, compatibility expansion, or changes to media
policy.

The v2 roadmap lives in [v2/plans.md](v2/plans.md), the active v3 roadmap lives
in [v3/plans.md](v3/plans.md), and shared execution rules live in
[v3/implement.md](v3/implement.md). V2 Phases 1 through 7 are complete;
v3 Phase 1 and Phase 2 are complete. Planning documents describe intended work; this
architecture document remains authoritative for implemented system behavior.

## Implementation status

The CLI exposes diagnostic preflight and one complete synchronous `process` job.
The backend has an application service that executes the media-preparation slice: it creates an owned
workspace, normalizes clips sequentially when required, writes the concat
manifest, concatenates exactly once, verifies the merged result (including the
FFV1/PCM contract on the normalization path), and either cleans a standalone
workspace or retains a caller-owned one. A composable extraction service turns
that merged timeline into a verified exact-CFR RGB PNG sequence while retaining
the merged audio source. A cancellable Real-ESRGAN service then skips AI when the
source is already tall enough or runs one directory upscale stage with bounded
Vulkan-memory retries and exact output-frame verification. A terminal service
then encodes the verified frames and selected audio, probes a same-filesystem
partial, publishes it atomically, and applies the terminal workspace policy. A
synchronous full-job service composes all of those stages behind one
frontend-independent entry point. It passes one cancellation token and owned
workspace through the job, enforces lifecycle transitions, forwards measured
progress, releases the reserved destination on every terminal path, cleans
cancellation, and retains failed workspaces. The CLI converts those typed
outcomes into stable success, failure, rejection, and cancellation exit statuses;
it never constructs backend commands. A frontend-independent single-worker FIFO
freezes queued job identities and destinations, serializes pipeline execution,
forwards typed state and progress snapshots, and owns cancellation and shutdown.
The initial PySide6 shell is implemented: it bootstraps settings and services,
marshals queue events through an explicitly queued Qt signal, exposes typed list
roles, and renders job state, progress, errors, output, reordering, and cancellation.
The GUI job-creation path is implemented with ordered input intent, output and
height options, off-thread diagnostic preflight, complete issue review, explicit
per-job stream-drop acknowledgement, queue submission, and non-safety preference
persistence. Its external-tools editor supports native browsing and reset-to-discovery controls, validates executable launches, model assets, and Vulkan inference off the presentation thread, and atomically persists only a successful override set. Preferences also provide ordered, validated GUI-only related-file deletion rules. A successful source Trash move evaluates the first enabled matching rule and best-effort moves eligible immediate sibling regular files, reporting each result without rolling back the source operation. The
implemented boundaries are:

The presentation shell uses a single dark-themed window with a two-view
navigation rail. A shared left-side vertical splitter contains the active
Job-Creation or Queue-Monitoring surface above the user-resizable `Global
Messages`/`Job Messages` tabs, while a tall far-right preview column spans the
same near-full application height. Job Creation shows the selected local source
through `QMediaPlayer`/`QVideoWidget`; Queue Monitoring presents its immutable
queue model through Active, Up Next, and History presentation regions alongside
the `Original`, `Upscaled`, and `Final Video` tabs in an independent looping
player. For
the selected running job during `UPSCALE`, the first two tabs asynchronously
decode their matched first local frame as soon as it is ready, then the latest
measured local `frame-<multiple of 16>.png` samples; Final Video is empty until
the job completes. The pipeline emits the
optional paired sample paths as part of the immutable typed progress event and never waits for, polls, or
otherwise depends on GUI presentation. On completion, Final Video is selected
and loops the published local output.
Preview state is presentation-only and queue requests remain frozen typed values.
Session messages are timestamped in memory, receive queued snapshots through Qt
signals, and never expose exact subprocess command lines. The selected-source
preview can move its existing video widget into a borderless fullscreen dialog
without creating a second player or proxy media. Fullscreen has no clickable
controls; its `0`/`9`, `j`/`l`, `Space`/`k`, `Shift-P`/`Shift-N`, `Esc`, and `?`
actions remain outside processing intent. One dialog-scoped application event
filter resolves key presses through an immutable shortcut registry, consumes
matching key releases, and generates the visible help text from that same
registry. Playback commands track requested state synchronously because native
`QMediaPlayer` state notifications are asynchronous. Shortcut help uses a
non-activating frameless tool dialog rather than a sibling video widget, keeping
opaque white text reliably above the native video surface while a 50%-opaque
background preserves visual context at the fullscreen view's right-center.
When the GUI is launched from a terminal, a Qt-timer signal bridge translates
`SIGINT`/Ctrl+C into that window's normal close lifecycle; `aboutToQuit` then
uses the existing runtime shutdown path to cancel pending and active queue work,
join its worker, and release GUI services before process exit. The bridge keeps
the cooperative handler installed through cleanup, so repeated interrupts cannot
abort that sequence with `KeyboardInterrupt`.

- `core.models`: immutable job intent, exact rationals, typed stream inventory,
  issue codes, concat strategy, and frozen execution plans
- `storage.naming`: timezone-aware automatic names and process-local destination
  reservation with filesystem collision checks
- `storage.paths`: Qt-standard application data and cache locations
- `storage.workspaces`: randomly identified ownership-marked job directories and guarded cleanup confined to the configured job root
- `storage.publication`: same-filesystem partial allocation, verified atomic replacement, atomic no-clobber publication, and guarded partial deletion
- `services.queue`: one active pipeline, FIFO pending work, immutable snapshots, typed outcomes, reorder/removal, cooperative cancellation, destination claims, failure isolation, and joined shutdown
- `gui.application`: QApplication bootstrap plus explicit ownership and shutdown of settings, pipeline, queue, model, and window
- `gui.jobs`: monotonic queue-snapshot bridge and flat Qt job model; all model mutation runs on the Qt thread
- `gui.editor`: ordered clip intent, output directory, target height, fixed real-image model, and frozen generated-output identity
- `gui.preflight`: one owned QThread for diagnostic tool discovery and media probing, progress forwarding, reservation release, and joined shutdown
- `gui.submission`: issue review, non-bypassable safety gates, exact-inventory per-job acknowledgement, FIFO handoff, and non-safety preference persistence
- `gui.tool_settings`: native override editing, PATH/automatic resets, one owned validation thread, success-gated atomic persistence, and actionable discovery failures
- `gui.window`: native queue list, selected-job progress/status/output presentation, reorder controls, cancellation, and diagnostics location
- `system.platform`: macOS 26.5.2 and Apple Silicon support gate
- `system.processes`: shell-free execution, bounded diagnostic tails, explicit timeouts, cooperative cancellation, and process-group termination
- `system.tools`: explicit-path-first discovery, executable inspection, x4plus
  model-pair validation, and a cached 16 × 16 inference smoke test that proves
  the Real-ESRGAN Vulkan backend can create output
- `video.probe`: pure FFprobe arguments, bounded time and 4 MiB-per-stream capture, and defensive typed JSON parsing
- `video.compatibility`: typed stream-copy findings and normalize-all-or-none strategy selection
- `video.manifest`: ordered absolute concat paths with FFmpeg token escaping
- `video.commands`: lossless normalization, concat and RGB PNG extraction arguments, exact frame-count calculation, and typed preparation/extraction plans
- `video.frames`: shared deterministic names and structural RGB PNG inventory verification
- `video.finalization`: exact frame-timeline calculation, conservative audio-copy selection, and explicit quality-first final FFmpeg arguments
- `video.policy`: shared explicit SDR BT.709/SMPTE 170M profile policy used by preflight and command builders
- `upscaling.realesrgan`: real-image model and scale policy, shell-free directory commands, and conservative Vulkan-memory failure classification
- `services.preflight`: shared path, media-policy, sizing, concat-strategy, audio,
  and disk-margin validation
- `services.progress`: one typed construction boundary for immutable measured
  stage progress and optional paired preview-frame paths
- `services.contracts`: shared typed protocols for preflight and each pipeline
  stage, keeping orchestration independent from concrete executors
- `services.context`: immutable `StageContext` carrying workspace,
  cancellation, progress, and resolved toolchain dependencies through stages
- `gui.worker_lifecycle`: shared one-shot Qt worker cleanup and shutdown rules;
  operation-specific workers retain their own typed signals
- `services.media_preparation`: sequential normalize-all-or-none execution, one concat, measured stage progress, merged-result verification, and workspace retention policy
- `services.frame_extraction`: cancellable exact-CFR extraction, measured progress, RGB PNG inventory verification, and retained merged-audio handoff
- `services.upscaling`: skip-or-run orchestration, measured progress, bounded attempt diagnostics, safe retry-directory resets, cancellation, and exact scaled-frame verification
- `services.finalization`: final-frame re-verification, encoding, output probing, atomic publication, old-output preservation, and terminal workspace cleanup/retention
- `services.pipeline`: full-job composition, legal lifecycle transitions, shared cancellation and workspace ownership, typed terminal outcomes, and destination-reservation release
- `cli`: typed request parsing, human-readable or JSON preflight/process results, measured text progress, exit-status mapping, and cooperative SIGINT cancellation

The Vulkan smoke test uses an owned temporary directory, explicitly selects
`realesrgan-x4plus`, and uses a 32-pixel diagnostic tile. It does not change the
processing default of automatic tiling. Unit tests replace external processes,
so the normal test suite remains independent of GPU hardware and model files. A
tiny full-job integration test uses real FFmpeg and FFprobe with a contract-faithful
directory-mode fake upscaler, proving stage order, one AI invocation, final media
verification, atomic publication, reservation release, and terminal cleanup
without a GPU or model download.

Opt-in native acceptance tests provide two macOS-only checks outside `make
check`. Both first require the supported Apple Silicon platform and affirmative
Metal capability from the read-only `system_profiler` display report. The
presentation benchmark records 15 `MainWindow` exposure samples after one
initial and two discarded warmups against the 3-second p95 budget. The
screen-capture check exposes the
same dark window, invokes `screencapture`, and verifies that the captured image
contains its surface; it requires Screen Recording permission for the invoking
terminal. These are GUI presentation checks, not a substitute for a real
Real-ESRGAN/Vulkan pipeline-throughput benchmark.

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
| Color | Require, freeze, and preserve the first clip's SDR BT.709 or SMPTE 170M matrix; require range; omit missing transfer/primary tags without defaults; reject explicit conflicts |
| Color range | Limited/TV; explicitly convert accepted full-range input |
| Common canvas | First clip's resolution; preserve aspect ratio and pad |
| Rotation | Unsupported; reject nonzero metadata and disable auto-rotation |
| Constant frame rate | First clip's nominal exact rational rate; sub-time-base-tick fraction differences are timestamp quantization |
| Frame sequence | Lossless PNG with deterministic zero-padded names |
| Real-ESRGAN model | `realesrgan-x4plus` |
| Final display height | 2160 pixels |
| Final display width | Derived from coded dimensions and sample aspect ratio, then rounded to an even integer |
| Final container | MP4 with fast-start metadata |
| Final video | `libx264`, CRF 3, slow preset, `yuv420p` |
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

Version 1 accepts supported SDR BT.709 and SMPTE 170M matrices. Probe color primaries, transfer characteristics, matrix coefficients, range, pixel format, and mastering metadata before processing. Require and freeze the first clip's matrix. Preserve its optional transfer characteristics and primaries when declared, but keep either field unspecified when absent.

- Reject detected PQ, HLG, BT.2020, HDR mastering metadata, and other explicit HDR or unsupported wide-gamut signaling with an actionable message.
- Accept explicitly tagged supported SDR BT.709 and SMPTE 170M matrices directly.
- Require every later clip to declare the same matrix. When both compared clips explicitly declare transfer characteristics or primaries, reject conflicting values. A missing optional value is ignored rather than treated as a conflict; version 1 performs no cross-profile or SMPTE 170M-to-BT.709 conversion.
- Reject absent or unknown matrix/range metadata. Accept missing transfer characteristics and primaries without an override and without substituting BT.709; omit fields absent from the first clip when signaling normalized and final output.
- Convert YUV to the RGB PNG frame representation explicitly with the frozen matrix, then convert processed RGB frames back with that same matrix for encoding.
- Tag the final stream explicitly with the frozen first-clip primaries, transfer characteristics, and matrix coefficients. Do not tone-map, gamut-map, convert matrices, or retag silently.

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

`JobQueue` is the frontend-independent serialization boundary. Submission freezes a timezone-aware creation instant and compact UUIDv7 basename, claims the resolved intended destination across queued and active records, and returns a stable job identifier that is also bound into pipeline logs. Immutable snapshots expose state, zero-based pending position, the frozen request, and latest measured progress. Terminal outcomes retain either the completed pipeline result or a typed cancellation/failure. Callback exceptions and unexpected runner exceptions are isolated so they cannot terminate the worker or strand later jobs.

Queued cancellation removes the request without invoking preflight. Active cancellation signals the pipeline's shared token and waits for its terminal cleanup before starting the successor. Shutdown rejects new submissions, cancels all pending records, signals the active job, and joins the sole worker. Destination claims are released only at a terminal outcome.

Version 1 does not resume partial jobs. Restart failed, cancelled, or interrupted jobs from the beginning.

### Output replacement

Overwrite an existing destination by default. Never truncate or remove it when the job starts: write the complete result to a partial file on the destination filesystem, verify that partial file, then atomically replace the destination. Failure or cancellation before publication leaves the existing destination unchanged. Successful replacement does not keep a backup.

The CLI provides `--no-overwrite`, and the GUI provides an overwrite setting that is enabled by default. In no-overwrite mode, reject an existing destination during preflight and recheck immediately before publication to detect a file created while the job was running.

### Automatic output naming

Generate the default output basename when the job is created, not when processing starts or finishes. Use the timezone-aware local wall clock and this ASCII-only format:

```text
ai-video-YYYYMMDD-HHMMSS-<compact-UUIDv7>.mp4
```

For example: `ai-video-20260821-143052-01a022ccf35b7a1e8b0bf554b4c36db2.mp4`.

- `ai-video-` is the fixed prefix.
- `YYYYMMDD-HHMMSS` is the creation time rendered in the job's local timezone.
- `compact-UUIDv7` is an RFC 9562 UUIDv7 rendered as 32 lowercase hexadecimal characters without hyphens. Its 48-bit Unix-millisecond timestamp is derived from the same absolute creation instant, so repeated or ambiguous local wall-clock seconds remain distinguishable.
- The selected output directory remains separate from the generated basename. The CLI uses `--output-dir`; the GUI exposes an output-directory picker.
- Capture and freeze the timestamp, compact UUIDv7, basename, and resolved path in the job model so queued jobs do not change names later.
- Reserve the resolved path against both the filesystem and all queued or active jobs. If it collides, append `-01`, `-02`, and so on before `.mp4` until a free path is reserved.
- Automatically generated paths never replace an older output. The general default-overwrite policy applies only to an explicit user-supplied destination path.

### Workspace and disk safety

Resolve the cache root with `QStandardPaths.StandardLocation.CacheLocation`; on macOS the v2 job root is `~/Library/Caches/Advanced AI Video Tools/jobs/`. Create one randomly identified, ownership-marked directory per job.

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

Resolve persistent configuration with `QStandardPaths.StandardLocation.AppDataLocation`, corresponding to `~/Library/Application Support/Advanced AI Video Tools/` on macOS. Store executable paths, recent locations, and user preferences there; do not store credentials or model binaries. The v2 first launch does not import v1 settings and removes only the guarded legacy settings files.

The settings document is typed, YAML-encoded, and explicitly schema-versioned. Version 2 persists the version-1 preferences plus nullable GUI-only related-file deletion rules. Version-1 documents load without rewrite and migrate on the next successful save. Individual malformed rules are skipped with a GUI diagnostic while valid rules remain active; malformed documents are quarantined and safe defaults are restored. Unsupported newer schema versions remain untouched and produce an explicit error rather than being mistaken for corruption. Unknown fields within the current schema are ignored for minor forward compatibility. A valid legacy `settings.json` is migrated once to `settings.yaml`; all subsequent writes use YAML.

An empty executable override means discovery through `PATH`; an empty model-directory override means the `models` directory beside the resolved Real-ESRGAN executable. The GUI never saves edited overrides optimistically. It runs all discovery checks—including the bounded Real-ESRGAN Vulkan smoke test—on an owned worker thread and atomically replaces settings only after success. The newly persisted overrides apply to later draft requests. Requests already submitted to the FIFO retain their frozen `ToolOverrides` and cannot be retargeted by a settings change.

Dropped-stream acknowledgement is bound to one job's probed stream inventory. It is never persisted or reused, because doing so would silently waive the explicit warning for different inputs.

Loguru is the application logging API. Configure it once at application startup; backend, CLI, and GUI modules import the shared Loguru `logger` and must not install their own sinks. Keep user-facing CLI stdout/stderr rendering separate from diagnostic logging.

Write a human-readable stderr sink and a local file sink under the application-data directory. Configure the file sink with `rotation="10 MB"`, `retention=5`, and `enqueue=True` for bounded, thread-safe delivery. Production exception logging disables diagnostic local-value exposure, redacts sensitive paths and environment data where practical, and binds stable context such as job ID and pipeline stage. Expose the log location in CLI and GUI diagnostics.

Immediately before every FFmpeg, FFprobe, and Real-ESRGAN subprocess launch, write an INFO message in the form `RUN <shell-quoted argument vector>`. This is a diagnostic rendering only; execution continues to use the original argument array with `shell=False`. The record deliberately includes every exact argument, including local input, output, model, and workspace paths, so the local log must be treated as potentially sensitive.

Version 1 performs no telemetry, analytics, crash uploads, update checks, or other application-initiated network requests.

## System boundaries

```text
CLI ────────────────> Job model ────────────┐
                                            ├──> Pipeline service ──> Progress/events
GUI ──> Job model ──> FIFO job queue ───────┘          │
                                                       ├──> FFprobe adapter
                                                       ├──> FFmpeg adapter
                                                       ├──> Real-ESRGAN adapter
                                                       └──> Workspace/output manager
```

- **CLI:** parses arguments, creates a typed job request, and renders progress and errors. It contains no media-processing logic.
- **GUI:** creates the same typed job request and consumes the same progress events. It contains no backend command construction.
- **Diagnostic GUI preflight:** probes off the presentation thread and releases its preview reservation. Accepted jobs still repeat authoritative preflight in the pipeline so media, tools, disk space, and destination availability cannot go stale between review and execution. Stream-drop acknowledgement carries deterministic keys for the exact reviewed path and dropped stream/chapter inventory; any changed inventory becomes a fresh blocking acknowledgement issue.
- **FIFO job queue:** freezes submission identity, claims destinations, serializes one active pipeline, forwards snapshots, and owns pending/active cancellation plus worker shutdown.
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
- Reject detected HDR, unsupported wide gamut, mixed matrices, explicit transfer/primary conflicts, and missing matrix/range tags. Ignore absent transfer/primary tags without defaults. Require acknowledgement for every unsupported secondary stream that will be dropped.
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

Full-range color, VFR timing, missing required audio, or audio-duration mismatch forces normalization even when codec and stream layouts would otherwise be concat-compatible. A matching limited-range SMPTE 170M job does not require normalization solely because of its matrix. Nonzero rotation metadata fails preflight instead of entering normalization.

The default normalization profile is Matroska with FFV1 level 3 `yuv444p10le` video and `pcm_s24le` audio at 48 kHz. Use the first clip's coded resolution, sample aspect ratio, and exact frame rate plus the first available primary audio channel layout unless the job overrides them. Use quality-first Lanczos scaling, preserve display aspect ratio by padding, and never stretch or crop silently. Normalized clips use deterministic six-digit names such as `clip-000001.mkv`.

Resolve the first clip's nominal exact rational frame rate without converting through floating point. Compare the periods represented by `r_frame_rate` and `avg_frame_rate`; if they differ by less than one tick of the stream time base, treat the difference as timestamp quantization and retain the nominal CFR, such as `16/1`. A difference of one full tick or more remains VFR; use FFprobe's valid rational average rate, normalize every clip to that rate, and report the conversion. Preserve `30000/1001` rather than rounding it to `29.97` or `30`.

Pass `-noautorotate` for every FFmpeg input and do not add rotation filters. Convert accepted full-range input explicitly to limited/TV range while preserving the frozen matrix; do not relabel range or matrix metadata without converting sample values.

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
- Perform explicit YUV-to-RGB conversion using the frozen BT.709 or SMPTE 170M matrix for the PNG sequence; do not rely on unspecified automatic color interpretation.
- Use a single zero-padded naming convention that preserves lexical and numeric order.
- Choose and record an explicit constant output frame rate. Variable-frame-rate conversion must be visible to the user.
- Retain the verified merged media as the primary-audio source for later muxing, preserving its exact relationship to the video timeline without a needless additional audio copy.
- Record the expected frame count for validation after upscaling.

### 6. Upscale once

When the merged input is below the target height, invoke `realesrgan-ncnn-vulkan` with the extracted directory as input and one output directory. Pass `-n realesrgan-x4plus`, the resolved AI scale, `-t 0`, and PNG output explicitly. Omit `-g`, `-j`, and `-x` to use automatic GPU selection, executable-default threads, and disabled TTA. Skip this stage when the input is already at or above the target height.

Do not expose anime-specific models in the v1 CLI, GUI, or configuration. Reject an anime model name with a clear validation error rather than silently substituting it.

Use directory processing rather than one subprocess per frame. Retry only recognized Vulkan memory failures with the defined `512 → 256 → 128 → 64 → 32` tile sequence. Do not silently switch to another Real-ESRGAN implementation or promise a CPU fallback.

Before encoding, verify that output frame numbers match the input set exactly. Missing, duplicate, unreadable, or unexpected frames fail the stage.

The implemented adapter passes `-m`, `-n realesrgan-x4plus`, the frozen `-s` scale, `-t`, and `-f png` explicitly. It omits `-g`, `-j`, and `-x` so the executable uses automatic GPU selection, its default worker configuration, and disabled TTA. The first attempt uses `-t 0`; only recognized allocation or out-of-memory diagnostics unlock the finite fixed-tile retry sequence. Each retry recreates only the verified job-owned `upscaled` directory and records bounded attempt diagnostics.

### 7. Encode and mux

This stage is implemented as a shell-free command plan and cancellable service boundary.

- Resize the processed sequence to the resolved even width and exact target height while preserving the source aspect ratio. Never crop or stretch. Encode at the recorded output frame rate. The default is MP4 using `libx264`, CRF 3, the slow preset, `yuv420p`, and fast-start metadata.
- Convert RGB frames explicitly to YUV using the frozen first-clip matrix and set the frozen primaries, transfer, and matrix metadata on the final stream.
- Copy the selected primary audio only when it is unchanged and compatible with MP4; otherwise encode AAC-LC at 256 kbit/s and 48 kHz.
- Pad final audio with silence or trim it so its duration matches the authoritative final video timeline. Omit audio when every input is silent.
- Map only supported streams explicitly; never rely on FFmpeg's implicit stream selection.
- Write to a partial output located on the destination filesystem.

### 8. Verify, publish, and clean up

This stage is implemented for explicit overwrite, explicit no-overwrite, and generated destinations. The no-clobber publication operation is atomic rather than only a pre-publication existence check.

Probe the partial output and verify readable streams, nonzero duration, expected dimensions, expected frame timing, no rotation transform, explicit signaling matching the frozen first-clip color profile, expected audio presence, and audio/video duration agreement. Frame-rate verification compares frame periods and accepts only differences smaller than one tick of the probed stream time base, because container timestamp quantization can produce a different but equivalent FFprobe fraction. A rejected merged or final rate reports the expected and effective rates, FFprobe real and average fractions, time base, VFR classification, exact frame-period delta, and strict accepted tolerance. Only then atomically replace the requested destination. Preserve any existing destination until this publication step succeeds.

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
- Cap FFprobe and prerequisite-inspection stdout and stderr at 4 MiB per stream while continuing to drain pipes; reject oversized output instead of retaining it in memory.
- Treat nonzero exit codes, malformed probe output, missing frames, and failed output verification as typed failures.
- Cancellation must terminate the active process tree and wait for termination before workspace deletion.
- Never modify or delete source inputs.
- Default to atomic destination replacement after verification for explicit paths. Never truncate the existing file early. In no-overwrite mode, reject collisions during preflight and recheck immediately before publication. Generated paths must be uniquely reserved and never overwrite an earlier output.
- Avoid loading full videos or unbounded frame batches into Python memory.

## Testing boundaries

- Unit-test job validation, compatibility decisions, command construction, state transitions, progress parsing, path escaping, and cleanup ownership with process fakes.
- Unit-test timezone-aware automatic names, UUIDv7 version/variant/timestamp bits, compact lowercase formatting, queued-path reservations, numeric collision suffixes, exact rational frame-rate handling, quantized-CFR recognition, time-base-derived verification tolerance, genuine VFR classification, nonzero-rotation rejection, `-noautorotate` command construction, aspect-ratio preservation, full-to-limited range conversion decisions, default atomic replacement for explicit paths, preservation of the old file on failure, no-overwrite races, disk-margin rejection, FIFO scheduling, workspace retention, log rotation, and the bounded tile retry sequence.
- Integration-test FFprobe, concat, extraction, and encoding with tiny generated media fixtures, including a nominal 16 fps ProRes/MOV stream quantized on a `1/600` clock and its normalized FFV1/Matroska result.
- Contract-test the Real-ESRGAN adapter with a fake executable that copies or transforms small image fixtures predictably.
- Test orchestration without a GUI, GPU, network, or real model weights.
- Reserve end-to-end Vulkan tests for an explicitly marked hardware-enabled suite.
- Keep Apple Silicon Metal presentation and `screencapture` checks opt-in under
  `make performance-test` and `make gui-capture-test`; record their measured
  native results as acceptance evidence rather than making the default suite
  depend on a desktop session or Screen Recording permission.

The same pipeline contract must pass whether a job originates from the CLI or GUI.
