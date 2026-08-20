# AGENTS.md

This file provides repository-wide guidance for AI coding agents and contributors working on AI Video Tools.

## Mission

Act as a senior Python engineer building a reliable desktop application and CLI for an FFmpeg → `realesrgan-ncnn-vulkan` → FFmpeg video pipeline. Deliver complete, maintainable changes with predictable media output, a responsive GUI, and actionable errors.

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

1. Inspect the relevant source, tests, `README.md`, `pyproject.toml`, `Makefile`, and the nearest `AGENTS.md`. Treat implemented code and configuration as the source of truth.
2. Identify the behavior to change, its callers, edge cases, and the narrowest useful validation. For a bug, reproduce it or establish a failing regression test when feasible.
3. Implement the smallest complete vertical change. Follow existing conventions; avoid speculative frameworks, premature abstraction, drive-by refactors, and compatibility shims without a requirement.
4. Run targeted checks first, then the broadest affordable repository check. Diagnose failures instead of weakening or deleting tests. Distinguish failures caused by the change from pre-existing failures.
5. Review the diff for correctness, security, dead code, debug output, accidental generated files, and documentation drift before finishing.

## Architecture boundaries

Keep these responsibilities separate:

- **GUI:** collects user input, presents validation, dispatches jobs, and renders progress.
- **CLI:** parses command-line input and presents machine-appropriate progress and errors.
- **Application services:** run the shared pipeline and manage validation, job state, progress, cancellation, cleanup, and error translation.
- **Video backend:** probes media and builds safe FFmpeg/FFprobe invocations.
- **Upscaling backend:** validates and invokes `realesrgan-ncnn-vulkan` behind a stable interface.
- **Persistence/configuration:** stores user preferences and recent paths without containing processing logic.

The CLI and GUI are thin adapters over the same typed job model and application service. Neither frontend constructs backend commands. Keep FFmpeg and Real-ESRGAN process adapters replaceable so the orchestration can be tested without opening windows or running external binaries.

## Canonical pipeline

The primary design invariant is **concat first, upscale once**. Build one merged timeline, extract one frame sequence from it, and invoke the upscaling stage for that sequence. Do not upscale source clips separately and concatenate the results.

Implement every processing job as this state sequence:

```text
validate → probe → concatenate/normalize → extract frames
         → upscale frames → encode/mux audio → verify → publish → clean up
```

- Validate all inputs, output policy, free disk space when practical, executable paths, Vulkan availability, model choice, scale, and job workspace before processing.
- Probe every clip before choosing a concat strategy. When all streams are compatible, use FFmpeg's concat demuxer with stream copy so concatenation is lossless and avoids an extra encode. Inputs with differing codecs, time bases, dimensions, frame rates, pixel formats, or audio layouts require explicit normalization to a common intermediate specification before concat.
- Complete concatenation before frame extraction or Real-ESRGAN invocation. The concat stage must produce one merged working video and one continuous media timeline for all later stages.
- Extract one lossless, zero-padded frame sequence from the concatenated timeline. Select and record an explicit output frame rate; do not infer timing later from directory contents.
- Extract or map the concatenated audio independently so it can be muxed into the final encode. Define behavior for missing audio and multiple audio streams rather than relying on FFmpeg defaults.
- Invoke `realesrgan-ncnn-vulkan` once per frame directory where possible. Pass the selected model, scale, GPU, tile size, thread settings, and image format explicitly.
- Encode upscaled frames at the recorded frame rate, mux the selected audio, and apply explicit codec, pixel-format, quality, and metadata policies.
- Verify process exit codes, expected frame count, output existence, nonzero duration, and readable output streams before publishing the result.
- Publish through a partial file on the destination filesystem and rename only after verification. Clean job-owned workspaces on success, failure, and cancellation according to the configured retention policy.

## Python standards

- Target Python 3.10 or newer unless project metadata specifies otherwise.
- Use `uv` for Python environments, dependency resolution, locking, and command execution. Do not introduce `pip`, Poetry, Pipenv, or Conda workflows.
- Keep runtime and development dependencies in `pyproject.toml`, and commit `uv.lock` once it exists.
- Use `pathlib.Path` for filesystem paths.
- Add precise type annotations to new and changed public interfaces; avoid `Any` when a useful type is known.
- Prefer dataclasses, enums, or typed models for job configuration instead of unstructured dictionaries.
- Catch narrow exception types. Preserve the original cause when translating an exception with `raise ... from ...`.
- Use `logging` for diagnostics; do not use `print` in library or GUI code.
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
- Keep overlapping rules compatible. Use one project-wide line length and disable rules that conflict with Black rather than reformatting Black output.
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

- Never perform video probing, encoding, filesystem scans, model downloads, or inference on the GUI thread.
- Communicate worker progress through the GUI framework's thread-safe signal or event mechanism.
- Model job states explicitly so queued, running, cancelling, cancelled, failed, and completed states cannot be confused.
- Treat cancellation as a normal state, not an exception shown as a crash.
- Disable or guard actions that would create conflicting concurrent jobs.
- Make progress determinate when duration or frame count is known; otherwise clearly show an indeterminate state.
- Convert backend failures into concise user messages while retaining detailed logs for diagnosis.
- Report stage-level progress for probe, concat/normalization, extraction, upscaling, encoding, verification, and cleanup. Never present guessed percentages as measured progress.

## Video processing

- Probe every input before starting a job and validate that files are readable.
- Do not assume clips share codec, dimensions, frame rate, pixel format, time base, or audio layout.
- Use stream-copy concatenation only when inputs are compatible; otherwise normalize or transcode explicitly.
- Never upscale clips individually as an implementation shortcut. Normalization, when required, happens before concat; AI upscaling happens once after concat.
- Generate concat manifests safely; escape paths according to FFmpeg's manifest format and never interpolate them into a shell command.
- Preserve deterministic frame ordering with one documented zero-padded naming scheme shared by extraction, upscaling, and encoding.
- Treat variable-frame-rate input as an explicit conversion decision. Record the chosen constant output frame rate and surface timing changes to the user.
- Preserve aspect ratio by default. Cropping or stretching requires an explicit user choice.
- Write output through a temporary or partial file and promote it only after successful completion.
- Avoid overwriting an existing output unless the user has explicitly approved it.
- Clean up owned temporary artifacts after success, failure, and cancellation without deleting user inputs.
- Record the effective processing configuration in logs to make jobs reproducible.

## AI upscaling

- The required backend is `realesrgan-ncnn-vulkan`; do not silently replace it with the Python/PyTorch Real-ESRGAN implementation.
- Discover the executable from explicit configuration first, then `PATH`. Report the resolved executable and version in diagnostic logs.
- Validate model name, model files, scale, input/output image formats, GPU selection, tile size, and device availability before processing.
- Use the executable's directory input/output support instead of launching one process per frame unless a measured constraint requires otherwise.
- Use tiling to bound GPU memory. If an out-of-memory failure is retryable, reduce tile size through a bounded, logged policy rather than retrying indefinitely.
- Do not promise a CPU fallback: this pipeline targets the NCNN Vulkan executable. Fail early with an actionable message when no compatible Vulkan device is available.
- Verify model sources and licenses before adding automatic downloads or redistribution.
- Store downloaded weights in an application cache, not in the repository.
- Preserve output-frame numbering exactly and reject missing, duplicate, or unexpected frames before encoding.

## Testing

Add tests at the lowest practical layer:

- Unit tests for validation, command construction, path handling, job-state transitions, and error mapping
- Integration tests for FFmpeg behavior using tiny generated fixtures
- Backend contract tests using a lightweight fake upscaler
- GUI tests for critical interactions when supported by the chosen framework

Tests must not require a GPU, network connection, large model download, or long video by default. Mark heavyweight or hardware-specific tests separately. When fixing a bug, add a regression test when feasible.

Use the narrowest effective validation during iteration. Before completion, run `make check` when it exists and is affordable. Use `uv run` for focused diagnostics that have no Make target. Never claim a check passed unless it was actually run; if a check cannot run, report the command, reason, and next-best validation.

## Final response

Lead with the result. Include:

- What changed and the important design decision, if any
- Which checks ran and their outcome
- Any remaining limitation, risk, or required user action

Omit routine tool narration, generic reassurance, and suggestions unrelated to the request.
