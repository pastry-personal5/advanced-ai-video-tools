# AGENTS.md

This file provides repository-wide guidance for AI coding agents and contributors working on AI Video Tools.

## Mission

Act as a senior Python engineer building a reliable macOS Apple Silicon desktop application and CLI for an FFmpeg → `realesrgan-ncnn-vulkan` → FFmpeg pipeline for photographic and live-action footage. Use PySide6 for the GUI. Deliver complete, maintainable changes with predictable media output, a responsive interface, and actionable errors.

The repository is in its initial stage. Do not describe proposed modules or commands as implemented until they exist and have been verified.

## Success criteria

A task is complete when:

- The requested user-visible outcome and stated acceptance criteria are satisfied.
- The change is the smallest coherent implementation and follows the architecture below.
- Relevant tests and static checks pass, or unavailable checks and their reason are reported.
- Long-running work handles progress, failure, cancellation, and cleanup where applicable.
- User-facing behavior, dependencies, and configuration changes are documented.
- The final response states the outcome, validation performed, and any material remaining risk.

## AI-generated code policy

Most source code in this repository is expected to be generated or assisted by AI coding tools. AI authorship does not reduce the quality bar or transfer responsibility away from contributors and maintainers.

- Treat generated code as an untrusted draft until it has been read, understood, tested, and reviewed.
- Verify APIs, command-line options, dependency versions, and framework behavior against the installed project or authoritative documentation.
- Look for fabricated APIs, incomplete error handling, unsafe subprocess or filesystem operations, race conditions, and unnecessary abstractions.
- Never add generated code whose purpose or behavior cannot be explained clearly.
- Do not reproduce third-party code or assets with uncertain provenance or incompatible licensing.
- Keep prompts, model transcripts, and tool metadata out of source files unless they are intentionally required project documentation.
- Prefer focused changes that are easy for a human maintainer to audit.
- State which checks were actually run; never imply that generated code was tested when it was not.

## Scope and autonomy

- For requests to answer, explain, review, diagnose, or plan, inspect relevant files and report the result. Do not modify files unless the request also asks for a change.
- For requests to build, change, or fix, make in-scope local edits and run relevant non-destructive validation without asking first.
- Ask only when a missing choice would materially change the result or when permission is required for an external, destructive, costly, or scope-expanding action. Otherwise make the safest reasonable assumption and state it.
- Reading files, inspecting logs and Git state, editing requested files, and running local checks are safe actions.
- Preserve unrelated and pre-existing changes. Never discard or overwrite work merely to simplify the task.
- Do not add credentials, personal paths, model weights, generated videos, caches, or temporary frames to Git.

## Execution workflow

1. Inspect the relevant source, tests, `README.md`, `docs/ARCHITECTURE.md`, `pyproject.toml`, `Makefile`, and the nearest `AGENTS.md`. Treat implemented code and configuration as the source of truth.
2. Identify the behavior to change, its callers, edge cases, and the narrowest useful validation. For a bug, reproduce it or establish a failing regression test when feasible.
3. Implement the smallest complete vertical change. Follow existing conventions; avoid speculative frameworks, premature abstraction, drive-by refactors, and compatibility shims without a requirement.
4. Run targeted checks first, then the broadest affordable repository check. Diagnose failures instead of weakening or deleting tests. Distinguish failures caused by the change from pre-existing failures.
5. Review the diff for correctness, security, dead code, debug output, accidental generated files, and documentation drift before finishing.

## Architecture boundaries

`docs/ARCHITECTURE.md` is the authoritative pipeline and component specification. Keep it synchronized with intentional architecture changes.

Version 1 requires macOS 26.5.2 or later on Apple Silicon. The Apple M5 Max with 128 GB unified memory is the reference machine, not a minimum hardware requirement. Do not add behavior for older macOS releases, Intel Macs, Windows, or Linux without an explicit scope change and validation plan.

Keep these responsibilities separate:

- **GUI:** collects user input, presents validation, dispatches jobs, and renders progress.
- **CLI:** parses command-line input and presents machine-appropriate progress and errors.
- **Application services:** run the shared pipeline and manage validation, job state, progress, cancellation, cleanup, and error translation.
- **Video backend:** probes media and builds safe FFmpeg/FFprobe invocations.
- **Upscaling backend:** validates and invokes `realesrgan-ncnn-vulkan` behind a stable interface.
- **Persistence/configuration:** stores user preferences and recent paths without containing processing logic.

The CLI and GUI are thin adapters over the same typed job model and application service. Neither frontend constructs backend commands. Keep FFmpeg and Real-ESRGAN process adapters replaceable so the orchestration can be tested without opening windows or running external binaries.

## Canonical pipeline

The primary design invariant is **concat first, upscale at most once**. Build one merged timeline and extract one frame sequence. Invoke Real-ESRGAN once only when that merged input is below the requested height. Do not upscale source clips separately and concatenate the results.

Implement every processing job as this state sequence:

```text
validate → probe → concatenate/normalize → extract frames
         → upscale frames if needed → encode/mux audio → verify → publish → clean up
```

- Validate all inputs, output policy, conservative peak-disk estimate plus 20% margin, executable paths, Vulkan availability, model choice, target height, resolved dimensions, AI scale, and owned job workspace before processing.
- Accept supported SDR BT.709 and SMPTE 170M matrices. Require and freeze the first clip's matrix and require explicit range. Preserve SMPTE 170M as SMPTE 170M without BT.709 conversion. Ignore missing transfer characteristics and color primaries without inventing defaults; preserve optional tags declared by the first clip and omit fields absent from it. Reject explicit conflicts when both compared clips declare a value. Reject detected HDR, unsupported wide gamut, unsupported tags, mixed matrices, and missing matrix/range metadata.
- Reject nonzero rotation/display-matrix metadata. Version 1 never rotates video and every FFmpeg input must use `-noautorotate`.
- Select the first audio stream from each clip. Inventory unsupported secondary streams and require acknowledgement before dropping them.
- Treat FFmpeg, FFprobe, `realesrgan-ncnn-vulkan`, Vulkan support, and model files as user-installed prerequisites. Discover and validate them, but never bundle or automatically download them.
- Probe every clip before choosing a concat strategy. When all streams are compatible, use FFmpeg's concat demuxer with stream copy so concatenation is lossless and avoids an extra encode. Inputs with differing codecs, time bases, dimensions, frame rates, pixel formats, or audio layouts require explicit normalization to a common intermediate specification before concat.
- Complete concatenation before frame extraction or Real-ESRGAN invocation. The concat stage must produce one merged working video and one continuous media timeline for all later stages.
- Extract one lossless, zero-padded frame sequence from the concatenated timeline. Preserve the first clip's nominal exact rational CFR, recognizing rate-fraction differences smaller than one stream timestamp tick as quantization; use its valid rational average rate for genuine VFR without converting through float.
- Extract or map the concatenated audio independently so it can be muxed into the final encode. Define behavior for missing audio and multiple audio streams rather than relying on FFmpeg defaults.
- Invoke `realesrgan-ncnn-vulkan` at most once for the merged frame directory. Pass the selected model, resolved AI scale, GPU, tile size, thread settings, and image format explicitly. Skip AI processing by default when the merged input is already at or above the requested height.
- Encode the processed frames at the recorded frame rate and resolved target dimensions, mux the selected audio, and apply explicit codec, pixel-format, quality, and metadata policies.
- Verify process exit codes, expected frame count, output existence, nonzero duration, and readable output streams before publishing the result. Frame-timing failures must report expected, effective, real and average rates, time base, VFR classification, period delta, and accepted tolerance.
- Generate and reserve the default `ai-video-<local timestamp>-<compact UUIDv7>.mp4` destination when the job is created. Generated names never overwrite older output. For explicit paths, publish through a partial file on the destination filesystem and atomically replace only after verification; overwrite remains the default. Preserve the old file on failure or cancellation. Honor no-overwrite mode with collision checks. Delete owned workspaces after success or cancellation; retain and report them after failure. Do not resume partial jobs in v1.

## Python standards

- Target Python 3.10 or newer unless project metadata specifies otherwise.
- Use `uv` for Python environments, dependency resolution, locking, and command execution. Do not introduce `pip`, Poetry, Pipenv, or Conda workflows.
- Keep runtime and development dependencies in `pyproject.toml`, and commit `uv.lock` once it exists.
- Use `pathlib.Path` for filesystem paths.
- Use PySide6 for GUI code and Qt's signals, slots, models, and ownership rules consistently. Do not introduce another GUI framework.
- Add precise type annotations to new and changed public interfaces; avoid `Any` when a useful type is known.
- Prefer dataclasses, enums, or typed models for job configuration instead of unstructured dictionaries.
- Catch narrow exception types. Preserve the original cause when translating an exception with `raise ... from ...`.
- Use Loguru (`from loguru import logger`) for application diagnostics; do not create new standard-library `logging` loggers and do not use `print` in library or GUI code. Configure Loguru sinks once at application startup rather than in feature modules. CLI stdout/stderr rendering remains an explicit presentation concern, not diagnostic logging.
- Resolve settings and logs with `QStandardPaths.StandardLocation.AppDataLocation` and job workspaces with `QStandardPaths.StandardLocation.CacheLocation`. Do not hard-code a user home directory in application logic.
- Keep persistent settings typed and schema-versioned. Save them with private permissions through a same-directory temporary file and atomic replacement. Quarantine malformed known-schema documents, but preserve and explicitly reject unsupported newer schema versions.
- Persist only non-secret preferences such as tool overrides, recent directories, target height, and overwrite behavior. Dropped-stream acknowledgement is specific to the current probed inputs and must never be persisted or reused for another job.
- Configure Loguru with a human-readable stderr sink and a local file sink using `rotation="10 MB"`, `retention=5`, and `enqueue=True`. Disable diagnostic value exposure in production exception output, redact sensitive path or environment data where practical, and bind stable context such as job ID and pipeline stage. Do not add telemetry, analytics, crash uploads, update checks, or other application-initiated network requests.
- Pass subprocess commands as argument lists with `shell=False`.
- Set explicit timeouts where a subprocess can hang, and capture enough stderr to explain failures.
- Pin or constrain dependencies through the project metadata; add packages with the appropriate `uv add` command and document why they are needed.
- Prefer standard-library solutions when they are clear. Add dependencies only when their maintenance and reliability benefit justifies their cost.
- Do not leave placeholders, pseudocode, silent fallbacks, or broad exception handling in completed paths.

## Formatting, linting, and task commands

- Black is the canonical Python formatter. Do not manually format code in a way that conflicts with Black.
- Pylint is the primary semantic and quality linter.
- pycodestyle enforces the project's selected PEP 8 style checks.
- Configure Black, Pylint, and pycodestyle centrally in `pyproject.toml` where each tool supports it.
- The project imposes no maximum characters per line. Do not wrap code or prose solely to satisfy a line-length limit. Black requires a finite configured width, so `9999` is the project sentinel for effectively unlimited lines; pycodestyle `E501` and Pylint `line-too-long` must remain disabled. Keep intentional multiline formatting when it materially improves readability.
- Use the repository `Makefile` as the canonical interface for routine tasks. Keep targets small, non-interactive, and suitable for local development and CI.

The intended target names are:

```bash
make install
make format
make lint
make test
make check
make run
```

All Python tools invoked by the `Makefile` should run through `uv run`, and dependency installation should use `uv sync`. When adding or changing a target, update `README.md` as needed.

## GUI and concurrency

- Never perform video probing, encoding, filesystem scans, or inference on the GUI thread.
- Deliver worker progress to the GUI through PySide6's thread-safe signal/slot mechanism.
- Model job states explicitly so queued, running, cancelling, cancelled, failed, and completed states cannot be confused.
- Run exactly one processing job at a time. Maintain later jobs in an in-memory FIFO queue and start the next only after the active job reaches a terminal state and cleanup finishes.
- Treat cancellation as a normal state, not an exception shown as a crash.
- Disable or guard actions that would create conflicting concurrent jobs.
- Make progress determinate when duration or frame count is known; otherwise clearly show an indeterminate state.
- Convert backend failures into concise user messages while retaining detailed logs for diagnosis.
- Report stage-level progress for probe, concat/normalization, extraction, upscaling, encoding, verification, and cleanup. Never present guessed percentages as measured progress.

## Video processing

- Probe every input before starting a job and validate that files are readable.
- Do not assume clips share codec, dimensions, frame rate, pixel format, time base, or audio layout.
- Probe color primaries, transfer characteristics, matrix coefficients, range, pixel format, and HDR metadata. Never silently tone-map, gamut-map, or reinterpret color.
- Reject detected PQ, HLG, BT.2020, HDR mastering metadata, and other unsupported HDR or wide-gamut input. Accept explicitly tagged `bt709` and `smpte170m` SDR matrices. The first clip freezes the job matrix and any optional transfer/primary tags it declares. Reject matrix conflicts and conflicts between two explicitly declared optional tags. Ignore missing transfer/primary tags without defaulting them; reject missing matrix or range.
- Reject nonzero rotation/display-matrix metadata; do not normalize it. Pass `-noautorotate` for every FFmpeg input and never add a rotation filter or control. Convert accepted full-range samples to limited/TV range explicitly while preserving the frozen matrix.
- Use stream-copy concatenation only when inputs are compatible; otherwise normalize or transcode explicitly.
- Force normalization for full-range color, VFR timing, missing required audio, or audio-duration mismatch even when codecs otherwise match. A matching limited-range SMPTE 170M job does not require normalization solely because of its matrix. Rotation is a validation error, not a normalization path.
- Use the documented quality-first defaults unless the job overrides them: Matroska/FFV1/PCM for normalization, the frozen first-clip SDR BT.709 or SMPTE 170M profile, PNG frames, a 2160-pixel final height with aspect-derived even width, and MP4/libx264 CRF 3 slow/yuv420p with unchanged compatible audio copy or AAC-LC 256 kbit/s for final output.
- Use `realesrgan-x4plus` as the v1 model and pass `-n realesrgan-x4plus` explicitly. Never inherit the Real-ESRGAN executable's default model.
- Never upscale clips individually as an implementation shortcut. Normalization, when required, happens before concat; AI upscaling happens at most once after concat.
- Select the first audio stream from each clip. When any input has audio, insert normalized silence for clips without it, pad short audio, and trim long audio so the video timeline remains authoritative. Omit final audio only when every input is silent.
- Inventory extra audio, subtitles, chapters, and attachments. Show what will be dropped and require explicit acknowledgement; never discard them silently.
- Convert YUV to RGB PNG explicitly with the frozen first-clip matrix before AI processing, then convert RGB back with that same matrix and explicit frozen profile tags during final encoding.
- Generate concat manifests safely; escape paths according to FFmpeg's manifest format and never interpolate them into a shell command.
- Preserve deterministic frame ordering with one documented zero-padded naming scheme shared by extraction, upscaling, and encoding.
- Preserve the first clip's nominal exact rational CFR, such as `16/1` or `30000/1001`. When real and average frame periods differ by less than one stream time-base tick, classify the difference as timestamp quantization and retain the nominal rate. For genuine VFR, use FFprobe's valid rational average rate. Normalize all clips to the selected rate and surface timing changes to the user; never round through a decimal float. Verify rate representations with the same strict timestamp-derived tolerance instead of literal rational equality.
- Always preserve aspect ratio through proportional scaling and padding. Cropping and stretching are unsupported in v1.
- Write output through a temporary or partial file and promote it only after successful completion.
- Overwrite an existing destination by default through verified atomic replacement. Never truncate it at job start. Support CLI `--no-overwrite` and the equivalent GUI setting, with a collision recheck immediately before publication.
- For automatic naming, capture timezone-aware local time at job creation and format `ai-video-YYYYMMDD-HHMMSS-<compact-UUIDv7>.mp4`. Encode the same creation instant into the UUIDv7 timestamp and render the UUID as 32 lowercase hexadecimal characters without hyphens. Freeze and reserve the path across the filesystem and queue; resolve the extraordinary case of a full-name collision with `-01`, `-02`, and increasing numeric suffixes. Generated paths must never overwrite older output.
- Create owned workspaces beneath `QStandardPaths.StandardLocation.CacheLocation/jobs`, require estimated peak use plus a 20% margin, delete after success or cancellation, and retain after failure. Never recursively delete an unmarked workspace or a path outside the job root.
- Record the effective processing configuration in logs to make jobs reproducible.

## AI upscaling

- The required backend is `realesrgan-ncnn-vulkan`; do not silently replace it with the Python/PyTorch Real-ESRGAN implementation.
- Version 1 supports real-world imagery only. Do not expose or select anime-, animation-, illustration-, or line-art-specific models.
- Treat target height as the public sizing option. Resolve the AI scale internally by choosing the smallest supported 2×, 3×, or 4× scale that reaches the target; use 4× with a warning when it cannot reach the target.
- Discover the executable from explicit configuration first, then `PATH`. Report the resolved executable and version in diagnostic logs.
- Validate that the `realesrgan-x4plus` parameter and binary model files are available, then validate scale, input/output image formats, GPU selection, tile size, and device availability before processing.
- Use the executable's directory input/output support instead of launching one process per frame unless a measured constraint requires otherwise.
- Use automatic GPU selection by omitting `-g`, automatic tiling with `-t 0`, executable-default threads by omitting `-j`, and disabled TTA by omitting `-x`.
- Retry only recognized Vulkan memory failures using tile sizes `512`, `256`, `128`, `64`, then `32`. Recreate only the owned upscale-output directory before each retry, record every attempt, and never retry another error class.
- Do not promise a CPU fallback: this pipeline targets the NCNN Vulkan executable. Fail early with an actionable message when no compatible Vulkan device is available.
- Do not implement automatic model downloads or redistribution. Validate user-supplied model files and document their expected source and license.
- Store only model paths in application configuration; never copy model weights into the repository.
- Preserve output-frame numbering exactly and reject missing, duplicate, or unexpected frames before encoding.

## Testing

Add tests at the lowest practical layer:

- Unit tests for validation, command construction, path handling, job-state transitions, and error mapping
- Integration tests for FFmpeg behavior using tiny generated fixtures
- Backend contract tests using a lightweight fake upscaler
- GUI tests for critical interactions when supported by the chosen framework

Tests must not require a GPU, network connection, large model download, or long video by default. Mark heavyweight or hardware-specific tests separately. When fixing a bug, add a regression test when feasible.

Include fixtures for SDR BT.709, preserved SMPTE 170M output, mixed-matrix rejection, explicit optional-tag conflict rejection, accepted missing transfer/primary tags, missing matrix/range rejection, explicit HDR rejection, clips without audio, short and long audio, and unsupported secondary streams. Verify acknowledgement gates for secondary streams, silence insertion, trimming, final frozen-or-omitted color tags, and audio/video duration alignment.

Test timezone-aware filename formatting, UUIDv7 version/variant/timestamp bits, compact lowercase rendering, path reservation, numeric collision suffixes, exact rational frame rates, quantized-CFR recognition, time-base-derived verification tolerance, genuine VFR classification, nonzero-rotation rejection, `-noautorotate` command construction, aspect-ratio preservation, full-to-limited range conversion, FIFO serialization, default atomic replacement for explicit paths, old-file preservation on failure, no-overwrite races, disk-margin rejection, workspace retention and safe cleanup, bounded tile retries, log rotation, and the absence of application-initiated network calls.

Use the narrowest effective validation during iteration. Before completion, run `make check` when it exists and is affordable. Use `uv run` for focused diagnostics that have no Make target. Never claim a check passed unless it was actually run; if a check cannot run, report the command, reason, and next-best validation.

## Final response

Lead with the result. Include:

- What changed and the important design decision, if any
- Which checks ran and their outcome
- Any remaining limitation, risk, or required user action

Omit routine tool narration, generic reassurance, and suggestions unrelated to the request.
