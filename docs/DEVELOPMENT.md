# Development practices

This document holds detailed engineering rules that are intentionally kept out
of the short repository-level `AGENTS.md`.

## Code quality

- Use Python 3.10+ with `uv`; keep runtime and development dependencies in
  `pyproject.toml` and commit `uv.lock` when dependencies change.
- Use `pathlib.Path`, precise public type annotations, and typed dataclasses or
  enums for cross-module data. Avoid `Any` when a useful type is known.
- Catch narrow exception types and preserve causes when translating errors.
- Prefer clear standard-library solutions. Do not leave placeholders, silent
  fallbacks, broad exception handling, or unexplained abstractions.
- Use PySide6 consistently for GUI code and Loguru for application diagnostics.
  Configure Loguru sinks once at application startup; library and GUI modules
  must not create standard-library loggers or install their own sinks.

Black is canonical formatting. Use the repository `Makefile` for routine work:
`make install`, `make format`, `make lint`, `make test`, `make check`, and
`make run`. Python commands in Make targets run through `uv run`; installation
uses `uv sync`. The project uses Black width `9999`; line-length diagnostics are
disabled in pycodestyle and Pylint.

## AI-assisted code review

Treat generated code as an untrusted draft. Read and explain it before keeping
it, verify external APIs and command options against installed tools or primary
documentation, and check for fabricated APIs, unsafe paths, shell injection,
race conditions, unbounded retries, incomplete cancellation, and cleanup bugs.
Use only code, assets, models, and dependencies with known compatible licenses.
Keep prompts, transcripts, and tool metadata out of source files.

## Runtime and safety

- Never probe media, scan files, encode, or run inference on the GUI thread.
  Use Qt signals/slots for worker progress and model mutation.
- Maintain explicit queued, running, cancelling, cancelled, failed, and
  completed states. Serialize processing through one frontend-independent FIFO.
- Make progress measured when totals are known; otherwise show indeterminate
  progress. Cancellation is a normal terminal path and must finish cleanup
  before the next queued job starts.
- Pass subprocess commands as argument lists with `shell=False`, set timeouts,
  capture bounded diagnostic stderr, and retain the original cause of failures.
- Immediately before each FFmpeg, FFprobe, or Real-ESRGAN launch, log
  `RUN <shell-quoted argument vector>` at INFO. This local record includes
  potentially sensitive paths; execution still uses the original argument list.
- Resolve settings and logs with Qt `AppDataLocation`, and job workspaces with
  Qt `CacheLocation`. Persist only typed, schema-versioned, non-secret
  preferences using private same-directory temporary files and atomic replace.
  Quarantine malformed current documents and explicitly reject newer schemas.
- Blank executable overrides mean `PATH`; a blank model-directory override
  means automatic discovery beside the resolved Real-ESRGAN executable. Validate
  tool edits off-thread before saving, and apply them only to future drafts.
- Dropped-stream acknowledgement belongs to the exact reviewed inventory for
  one job. Never persist or reuse it for another input set.
- Configure human-readable stderr and local rotating file sinks (`10 MB`, five
  retained files, `enqueue=True`), redact sensitive values where practical, and
  do not add telemetry, analytics, crash uploads, update checks, or downloads.

Do not use destructive commands against broad or unresolved paths. Preserve
unrelated worktree changes. Never add credentials, personal paths, model
weights, generated videos, caches, temporary frames, or local environment files.

## Documentation and validation

`docs/ARCHITECTURE.md` is the source of truth for implemented or binding
pipeline behavior. `README.md` describes verified user-facing behavior.
`docs/v2/plans.md` records roadmap decisions; the active phase file records
scope, checklist status, evidence, risks, and deferred work. Update affected
documents together and do not describe planned modules as implemented.

Use unit tests for validation, command construction, path handling, state
transitions, and error mapping; integration tests for tiny FFmpeg fixtures; and
fake external tools for Real-ESRGAN contracts. Default tests must not need a
GPU, network, large model, or long video. Mark hardware-heavy checks separately.
If a check cannot run, report the command, blocker, and next-best validation.
