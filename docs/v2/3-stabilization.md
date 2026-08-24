# Phase 3 — Stabilization

## Status

Complete. This phase was authorized after the Phase 3 proposal in
`docs/v2/plans.md` was reviewed. It covers performance, resource ownership,
lifecycle behavior, and exception/error handling before refactoring.

The phase uses the existing default test suite for deterministic coverage and
keeps desktop and Metal presentation measurements opt-in. Performance
benchmarks must not invoke media upscaling or Real-ESRGAN.
Raw benchmark output stays outside the repository; this file records only
commands, summarized evidence, and remaining work.

## Stabilization slice completed

- [x] Native profiler failures return actionable skip reasons for launch errors,
  timeouts, nonzero exits, and malformed JSON.
- [x] Native profiler execution is platform-gated before command launch.
- [x] The profiler command uses a trusted absolute path and retains the
  shell-free argument-array boundary.
- [x] Native acceptance capture uses a trusted absolute `screencapture` path
  and captures the window region directly, avoiding logical-to-device pixel
  coordinate reconstruction.
- [x] The presentation model depends on a typed minimal queue protocol rather
  than requiring a hand-written test double to impersonate the concrete queue.
- [x] The repeated presentation benchmark includes an explicit warm-up sample.

## Validation evidence

Focused command:

```text
UV_CACHE_DIR=/private/tmp/ai-video-tools-uv-cache uv run pytest tests/test_hardware.py tests/test_native_acceptance.py -q
```

Result: 11 passed, 2 native acceptance tests skipped because explicit native
acceptance was not enabled.

Opt-in native commands:

```text
make performance-test
```

Result: 1 passed. The three-sample presentation benchmark completed on the
supported Apple Silicon Metal-capable desktop after its warm-up sample.

```text
make gui-capture-test
```

Result: 1 passed. The native window was captured successfully using the
trusted macOS capture tool and direct window-region capture.

## Remaining Phase 3 work

- [x] Run and record the native presentation benchmark on the supported Apple
  Silicon host, including three measured samples and host metadata.
- [x] Run and record the screen-capture acceptance check with Screen Recording
  permission.
- [x] Verify existing fault-injection coverage for malformed settings, missing
  tools, invalid/unsupported media, disk-margin failures, queue rejection,
  worker exceptions, cancellation races, preview decode failures, and shutdown
  during active work. Evidence is in `tests/test_settings.py`,
  `tests/test_tools.py` (including denied prerequisite launch),
  `tests/test_preflight.py`, `tests/test_queue.py`,
  `tests/test_pipeline.py`, and `tests/test_gui.py`.
- [x] Measure queue cancellation, shutdown, cleanup, memory stability, and
  resource ownership against the proposed Phase 3 budgets with a deterministic
  no-upscaling queue workload.

  Evidence:

  - Ten sequential jobs completed with one maximum active job; mean job time
    was 0.013140 seconds.
  - Queued cancellation: 0.000157 seconds. Active cancellation: 0.000188
    seconds. Shutdown with active and pending jobs: 0.000097 seconds.
  - Destination claims were released after shutdown (`0` remaining), and the
    queue worker joined successfully. Workspace cleanup invariants remain
    covered by `tests/test_pipeline.py` and `tests/test_workspaces.py`.
  - Per-job Python allocation peak rose from 15,538 to 96,811 bytes, an
    81,273-byte increase (523.06%). This is below the charter's 100 MB minimum
    tolerance; process peak RSS was 41,353,216 bytes. The queue intentionally
    retains terminal outcomes for session history.
  - The workload used only `ControlledRunner`; it launched no FFmpeg,
    FFprobe, Real-ESRGAN, or upscaling stage.
- [x] Disable AI-upscaling performance workloads. The historical one-off
  Real-ESRGAN run is retained only as superseded evidence and is not an active
  benchmark, acceptance target, or regression baseline.
- [x] Run `make check` and resolve any failures before marking this phase
  complete.

The repository-side Phase 3 slice, native presentation checks, and
no-upscaling lifecycle/resource campaign are validated. No active performance
benchmark invokes upscaling. The Phase 3 documentation review is complete;
Phase 4 remains provisional and requires separate approval before work begins.
