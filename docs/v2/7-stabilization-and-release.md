# Phase 7 — Stabilization and release

## Status

- Phase: 7
- State: Complete
- Predecessors: Phases 1 through 6
- Target: v2 release candidate and release artifacts

Phase 7 is the final v2 stabilization and release phase. It begins only after
Phase 6 is complete and its implementation, tests, and documentation are
synchronized.

The no-upscaling performance suite and supported-macOS manual verification
are complete. Production signing and notarization remain deferred because the
owner is not enrolled in the Apple Developer Program.

## Objective

Re-verify the completed v2 behavior, establish repeatable no-upscaling
performance evidence, complete the supported-macOS acceptance campaign, and
produce verifiable v2 release artifacts without changing the media contract.

## Non-negotiable performance boundary

The Phase 7 performance campaign must not invoke Real-ESRGAN, Vulkan
inference, model loading for inference, GPU upscaling, or any GPU-based video
enhancement workload. Normal macOS compositor acceleration is outside the
application workload and is not treated as video upscaling.

## Performance suite

### Warm native-window presentation

- Use the real dark-themed `MainWindow`, an empty typed fake queue, and fixed
  1400 × 880 geometry.
- Perform one process-level warm-up and two additional discarded warm-ups.
- Record 15 measured window construction-to-native-exposure samples.
- Record every sample plus median, p95, minimum, maximum, mean, standard
  deviation, failures, and timeouts.
- Preserve the existing proposed p95 budget of no more than 3 seconds.

### Queue Monitoring presentation

- Use typed fake Active, Up Next, and History snapshots, including long job
  names.
- Measure Queue Monitoring switch-to-ready time, selection-to-details-update
  time, and resize-to-stable-layout time.
- Exercise initial presentation, all three region selections, the 1400 × 880
  minimum, and a return to the default window size.
- Verify no overlap, clipped essential controls, lost rows, or broken fixed
  Status/action columns.
- Establish a baseline before setting new hard budgets for these operations.

### Queue lifecycle/resource stability

- Retain the deterministic controlled-runner workload for ten sequential jobs.
- Measure per-job and total queue time, queued cancellation, active
  cancellation, shutdown, worker joining, destination-claim release, and
  cleanup behavior.
- Use no FFmpeg, FFprobe, Real-ESRGAN, Vulkan, model files, or media frames.

### Optional CPU-only media timing

If media-operation timing is required, measure tiny FFmpeg/FFprobe fixtures as
a separate workload. Use CPU-only settings and exclude Real-ESRGAN, Vulkan,
model loading, and all AI enhancement. Do not describe this as upscaler or
production-throughput performance.

## Repeatability controls

Every run records the fixed geometry, Qt platform, test order, warm-up policy,
sample count, foreground/exposure requirement, power state, display setup,
and any interruption or thermal/system-load anomaly. Screen capture is not
part of timing loops. Failed samples are not silently discarded; invalid runs
must be labeled with a reason.

Performance tests must use presentation-only windows, typed fake queues, or
the controlled no-upscaling runner. They must not construct a real processing
submission path or discover/validate Real-ESRGAN. A command guard should fail
if an upscaler/Vulkan launch is attempted.

## Historical performance record

Accepted results are summarized in
[performance-history.md](performance-history.md). The record is append-only;
raw per-sample output remains outside the repository.

Each accepted entry records:

- run ID, date/time, timezone, and commit
- workload ID and version
- exact command, sample count, and warm-up policy
- host model, architecture, macOS build, Python, Qt/PySide6, display setup,
  and power state
- median, p95, minimum, maximum, and pass/fail result
- anomalies, invalid samples, and comparability notes

Results are comparable only when workload version, measurement method, host
class, and relevant environment match. Changed conditions remain recorded but
are labeled non-comparable.

## Release validation

- Run `make check`.
- Run the opt-in native presentation benchmark.
- Run populated Queue Monitoring native capture/layout acceptance.
- Re-verify fullscreen keyboard focus, help, source navigation, player
  cleanup, and preview-error recovery.
- Re-verify queue cancellation, shutdown, atomic publication, settings
  corruption/migration, CLI alias compatibility, and failed-workspace
  retention.
- Verify macOS 26.5.2+, Apple Silicon, high-DPI rendering, permissions, and
  user-managed FFmpeg/FFprobe/Real-ESRGAN/Vulkan/model discovery.

## Release artifacts

The current approved Phase 7 artifact is an unsigned/ad-hoc-signed
development-only DMG. Its Finder launch uses the GUI-only entry point rather
than the argument-driven CLI dispatcher, so opening the app without command
line arguments starts the window instead of exiting silently.
Build it with `make package-dev-dmg`; the workflow uses a pinned PyInstaller
version, the real application entry point, the approved bundle identifier,
and an explicit macOS minimum version. It does not sign, notarize, or bundle
user-managed external tools.

The production `.app` and `.dmg` workflow is skipped for this release because
the owner is not enrolled in the Apple Developer Program. The unsigned
development `.app`/`.dmg` workflow, bundle identifier, `Info.plist`, entry
point, DMG naming/layout, and clean-install behavior remain the verified
release artifact scope. Do not bundle user-managed FFmpeg, FFprobe,
Real-ESRGAN, Vulkan support, or model files.

Developer ID signing, notarization, stapling, and quarantined Gatekeeper
testing are deferred until Apple Developer Program enrollment is available.
Keep signing credentials outside the repository and release artifacts.

## Exit criteria

Phase 7 may be marked Complete only when:

1. The full default suite and required native acceptance checks pass.
2. No performance test invokes GPU upscaling or AI enhancement.
3. At least one accepted performance record is written, with raw output kept
   outside the repository.
4. The v2 app and DMG artifacts are reproducible and independently verified;
   production signing and notarization remain deferred while the approved
   artifact target is unsigned development distribution.
5. README, architecture, changelog, plans, and this phase document agree.
6. Remaining limitations, deferred v1 alias policy, and post-v2 work are
   explicitly recorded.

## Verification record

- Phase 7 manual verification was completed on 2026-09-01, as reported by the
  user. Packaged-app functional checks and development DMG clean-install
  behavior were also completed manually.
- `UV_CACHE_DIR=/private/tmp/ai-video-tools-uv-cache make check` passed with
  262 tests passed and 3 opt-in native tests skipped.
- The non-performance native capture target passed on the supported interactive
  macOS desktop: `make gui-capture-test` — 2 passed, 1 deselected. It
  recognized the actual `spdisplays_supported` value, created the Cocoa
  window, and captured both visible-window and populated Queue Monitoring
  layouts with Screen Recording permission enabled.
- The native presentation performance target was run once successfully:
  `make performance-test` — 1 passed, 2 deselected. A follow-up attempt
  safely skipped because the active macOS display disappeared before Qt window
  creation. The root cause was per-process Cocoa screen enumeration returning
  no screens; the fixture now waits five seconds for screen readiness before
  skipping, avoiding the previous fatal `QVideoWidget` path. The subsequent
  user-run report captured 15 samples with a 0.035-second median and
  0.050-second p95; it is recorded in [performance-history.md](performance-history.md).
- The automated direct Make target now owns a writable uv cache, fails rather
  than silently skipping when its explicitly requested Cocoa display is
  unavailable, and always writes a JUnit report. A fresh direct run passed with
  15 samples, a 0.029-second median, and a 0.069-second p95. Restricted wrapper
  processes remain intentionally unsupported because they cannot access the
  logged-in WindowServer session.
- The rebuilt unsigned development DMG launched normally from Finder after
  switching PyInstaller to the GUI-only entry point. Packaged-app functional
  checks for settings, queue lifecycle, and logs were completed manually. The
  development DMG clean-install behavior was also manually verified. The
  GUI-only bundle entry point now preserves Finder's inherited `PATH` and adds
  standard Homebrew/MacPorts locations so user-managed FFmpeg, FFprobe, and
  Real-ESRGAN installations can be discovered from Finder.
- Production `.app`/`.dmg` packaging and Developer ID distribution are skipped
  for this release because Apple Developer Program enrollment is unavailable.
- `uv build --out-dir /private/tmp/ai-video-tools-phase7-build` could not
  resolve the build dependency because network/DNS access to PyPI is
  unavailable in this environment; no artifact was written to the repository.

## Native capture instructions

Run the capture check from the logged-in Mac desktop, not from a headless
terminal session or remote environment:

1. Keep at least one display awake and unlocked. Confirm that
   `system_profiler SPDisplaysDataType -json` reports Apple Silicon Metal.
2. Open System Settings → Privacy & Security → Screen & System Audio
   Recording and enable the terminal, IDE, or test runner that will launch
   pytest. Restart that application after changing permission.
3. Close other test processes, select the Cocoa display backend, and run:

   ```bash
   QT_QPA_PLATFORM=cocoa \
   ADVANCED_AI_VIDEO_TOOLS_RUN_NATIVE_ACCEPTANCE=1 \
   uv run pytest -m gui_capture tests/test_native_acceptance.py -q
   ```

4. Keep the app window unobstructed during capture. A successful run should
   report two passing populated/visible-window capture checks. If no display
   is available, the tests now skip safely instead of allowing Qt Multimedia
   to abort the process.
