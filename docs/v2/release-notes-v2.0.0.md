# Advanced AI Video Tools v2.0.0

Advanced AI Video Tools v2.0.0 completes the GUI enhancement, project rename,
stabilization, and release verification work for the v2 line. The established
concat-first media pipeline remains intact: clips are concatenated before any
optional Real-ESRGAN pass, and upscaling runs at most once per job.

## Highlights

- New `Advanced AI Video Tools` product identity across the Python package,
  import package, CLI, GUI, storage location, and macOS bundle identity.
- Native dark macOS GUI with separate Job Creation and Queue Monitoring
  workspaces.
- Ordered clip selection, asynchronous preflight review, explicit dropped-stream
  acknowledgement, and safe queue submission.
- Single-worker FIFO queue with Active, Up Next, and History regions, inline
  cancellation/removal actions, keyboard navigation, progress, diagnostics,
  and graceful shutdown.
- Selected-source preview with fullscreen keyboard playback and navigation.
- Queue Preview with Original, Upscaled, and Final Video tabs, including live
  sampled frame previews during upscaling and looping final-output playback.
- Validated External Tools preferences for FFmpeg, FFprobe, Real-ESRGAN, and
  model-directory overrides, including Finder-launched PATH discovery.
- Unsigned development-only macOS `.app`/`.dmg` packaging with verified Finder
  launch and clean-install behavior.

## Compatibility and safety

- Existing v1 media behavior remains authoritative unless explicitly changed by
  an approved v2 decision.
- Processing continues to preserve exact timing, supported SDR color metadata,
  audio synchronization, cancellation, cleanup, and atomic publication safety.
- FFmpeg, FFprobe, Real-ESRGAN, Vulkan support, and model files remain
  user-managed; the application performs no automatic downloads or telemetry.
- Supported platform: macOS 26.5.2 or later on Apple Silicon.
- The `ai-video-tools` CLI alias remains available as a deprecated compatibility
  alias through v2; `advanced-ai-video-tools` is the primary command.
- V2 uses a new application-data location and does not support v1/v2 side-by-
  side execution. The guarded v1 settings locations are removed during the v2
  storage transition; unrelated files are preserved.

## Verification

- Default quality gate: 262 tests passed, 3 opt-in native tests skipped.
- Native GUI capture: visible-window and populated Queue Monitoring acceptance
  passed on the supported interactive Apple Silicon macOS desktop.
- Native no-upscaling presentation performance: 15 samples, 0.035-second
  median, 0.055-second p95, within the 3-second budget.
- Packaged-app settings, queue lifecycle, logging, Finder launch, and
  development-DMG clean-install behavior were manually verified.

## Distribution note

The verified v2 artifact is an unsigned/ad-hoc-signed development DMG built
with `make package-dev-dmg`. Production Developer ID signing, notarization,
stapling, and quarantined Gatekeeper verification are deferred because the
owner is not enrolled in the Apple Developer Program.

## Upgrade and support notes

V2 is designed for the supported macOS and Apple Silicon environment described
above. Users should keep FFmpeg, FFprobe, Real-ESRGAN, Vulkan support, and the
required model files installed separately and configure custom paths in
**Edit → Preferences** when automatic discovery is unsuitable.

