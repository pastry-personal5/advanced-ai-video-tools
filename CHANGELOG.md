# Changelog

All notable changes to Advanced AI Video Tools are documented in this file.

## [Unreleased] — v2 rename

- Completed Phase 3 stabilization with deterministic failure-path coverage,
  native presentation and screen-capture acceptance checks, and no-upscaling
  queue/resource measurements. Performance benchmarks that invoke AI
  upscaling are disabled.

- Added opt-in Apple Silicon Metal-gated native GUI presentation measurements
  and a macOS `screencapture` acceptance check; neither expands the default
  hardware-independent test suite.

- Renamed the Python distribution to `advanced-ai-video-tools` and the import package to `advanced_ai_video_tools`.
- Added `advanced-ai-video-tools` as the primary CLI and retained `ai-video-tools` as a stderr-warning compatibility alias through v2.
- Established the `Advanced AI Video Tools` GUI identity, new application-data location, macOS bundle identifier `com.pastrypersonal5.advancedaivideotools`, and v2 macOS `Info.plist` template.
- Removed only the guarded v1 settings files on first v2 storage initialization; unrelated files and symlink targets are preserved.
- Retained the existing `ai-` automatic output filename prefix.
- Recorded the canonical repository URL and deferred signing, notarization, and supported-hardware upgrade validation to the v2 human release checklist.
- Approved distribution outside the Mac App Store using Developer ID distribution via `.dmg`.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Fixed selected-job monitoring progress bars showing stale pipeline progress
  while a job is cancelling or after it has been cancelled.
- Made fullscreen preview keyboard playback deterministic under rapid input by
  using one data-driven key registry and dispatcher, generated shortcut help,
  complete press/release consumption, synchronous requested playback state,
  and matched embedded/fullscreen play-control feedback.
- Added Phase 5 fullscreen selected-source preview with two entry points,
  keyboard playback and clip navigation, shortcut help, auto-hiding controls,
  invalid-input control feedback, a hidden-by-default top-right close button, and
  shared-player ownership without proxy media.
- Set the temporary v2 GUI display identity to `Advanced AI Video Tools` while retaining the existing organization/storage identity for the later rename phase.
- Replaced navigation-rail text glyphs with app-owned monochrome vector icons and added resolved-tool feedback after successful Preferences validation.
- Matched the horizontal inset between the navigation rail and Basic Settings to the rail's application-edge inset (8 px).
- Removed the duplicate creation-view left inset so the visible rail-button-to-Basic Settings gap is 8 px rather than 16 px.
- Added an 8 px outer inset around each Basic Settings group while retaining 16 px separation and existing internal group padding.
- Added a titled `Job Queue` panel around the monitoring table with the same heading and padding treatment as `Basic Settings`.
- Removed the redundant `No actions available` and `Diagnostics: …` rows from Queue Monitoring; control state and selected-job details remain authoritative.
- Replaced the source-list `Remove` button and filesystem Trash action with an app-owned minus-in-circle button on each clip row that removes only the list item.
- Added a per-row vertical-ellipsis menu with `Open in Filesystem` and `Move to Trash` actions.
- Made Trash handling duplicate-safe: successful moves remove all canonical duplicate references, while failed or unavailable-file operations preserve list intent.
- Added `SourceClipTrashService` to guard Trash operations; clips referenced by queued, validating, running, or cancelling jobs cannot be moved and emit a Global Messages notice.
- Hardened Trash guards to fail closed on queue-state lookup failures, path-resolution errors, missing files, and OS Trash-provider exceptions.
- Marked Phase 1 GUI enhancement complete; native screen inspection remains explicitly security-limited and documented.
- Approved `Advanced AI Video Tools` as the Phase 2 project name and `Pastry Personal 5` as owner, copyright holder, developer, primary contact, and maintainer.
- Unified the dark GUI's surface, field, button, list, progress, tab, and scrollbar treatment around the approved 8 px spacing grid, 32 px controls, and shared corner radii.
- Unified the horizontal major-region gap between Basic Settings→Source Clips and Source Clips→Preview at 32 px.
- Rebalanced Job Creation columns by widening the source-clip list allowance by 100 px and narrowing the preview minimum width by 100 px.
- Renamed the primary Job Creation action from “Preflight & Queue” to “Preflight”; its review and queue behavior is unchanged.
- Matched the Preview caption to the Source Clips section-heading typography and spacing.
- Moved the Preview heading onto the outer preview group-box border, matching the Source Clips title placement; inline preview errors remain inside the pane.
- Enlarged the target-height up/down arrow glyphs while preserving the existing spinner dimensions and step behavior.
- Refined the target-height arrows to normal-sized, softer glyphs for a less bright visual weight.
- Corrected the volume icon optical offset so minimum volume, slider, and maximum volume align on one visual centerline.
- Fixed preview-control glyph clipping by removing text-button padding from the fixed 32×32 icon hit areas.
- Kept the reliable native double-triangle previous/next glyphs and put those navigation controls on a neutral grey visual treatment.
- Changed previous/next clip navigation glyphs to simple `<` and `>` marks as requested.
- Changed previous/next clip navigation glyphs to directional arrows `←` and `→` as requested.
- Matched previous/next clip controls to the playback buttons' shared border, radius, background, and hit-area treatment while retaining softer grey glyphs.
- Rebalanced Job Creation columns again by widening the source-clip list allowance by 50 px and narrowing the preview minimum width by 50 px.
- Aligned the preview playback region's top edge with the actual Source Clips list widget.
- Refined Job Creation into evenly padded titled panels, standardized source-row action sizing, aligned the editor/preview/monitoring regions, and made navigation controls use the same selected-state surface treatment.
- Set preview controls to 32 × 32 glyph-only buttons with 2× glyphs and grouped playback/seek controls at the left with clip navigation controls at the right.
- Added the labeled `Output volume` row with native volume indicators and a right-aligned checkbox/`Mute` label group.
- Tinted the minimum and maximum volume indicators light gray for consistent dark-theme contrast.
- Aligned the output-volume label, minimum icon, slider, and maximum icon on one shared horizontal centerline.
- Corrected the native volume glyphs' padded-canvas visual offset so their rendered marks align with the slider line.
- Changed persistent settings from JSON to YAML, added the `settings.yaml` default path, and migrated valid legacy `settings.json` preferences once without weakening atomic writes, quarantine, or newer-schema protection.
- Set version 2 as the active development target while retaining v1.0.0 as the released behavior baseline.
- Established GUI enhancement as Phase 1 and project renaming as a required v2 goal.
- Defined project renaming as Phase 2 with explicit identity, compatibility, persistent-data migration, packaging, legal, and verification gates.
- Defined the Phase 1 video-preview scope as the currently selected source clip only.
- Defined the Phase 1 source preview as playback-only, without timeline or media-editing features.
- Selected PySide6 `QMediaPlayer` and `QVideoWidget` as the planned Phase 1 preview backend, isolated from FFmpeg and Real-ESRGAN processing.
- Defined the Phase 1 widget as selected-source playback while retaining FFprobe-backed preflight and the processing pipeline as the media contract.
- Defined unsupported native preview formats as a non-blocking state with no FFmpeg proxy fallback.
- Defined full-width Phase 1 preview playback with exact unrotated aspect preservation and no crop, stretch, or rotation.
- Completed preview-control accessibility and sizing: action labels update with play/pause state, and all five controls use fixed 32 × 32 pixel hit areas.
- Added headless regression coverage for width-driven 3:4 preview resizing and native `KeepAspectRatio` handling.
- Added regression coverage proving preview navigation cannot reorder clips or mutate processing request inputs.
- Added persisted non-safety preview mute and volume preferences with explicit audio controls; source autoplay remains muted until user action.
- Pause source preview playback when queued processing enters the running state without automatically resuming it after progress or completion; retain native output release during window shutdown.
- Confirmed preview source locality: only existing local video files from the editor can enter preview binding; remote and non-local URLs are rejected before any media load.

## [1.0.0] - 2026-08-21

### Added

- Complete quality-first video pipeline using FFprobe, FFmpeg, and `realesrgan-ncnn-vulkan`.
- Concat-first processing that merges the ordered source clips before running AI upscaling at most once.
- Stream-copy concatenation for compatible clips and lossless FFV1/PCM normalization before concat when required.
- Exact-rational frame-rate handling, timestamp-quantization tolerance, aspect-ratio preservation, and a default output height of 2160 pixels.
- SDR BT.709 and SMPTE 170M color-profile preservation, including explicit rejection of HDR, unsupported wide-gamut input, conflicting matrices, and ambiguous required color metadata.
- First-audio-stream selection with silence insertion, padding, trimming, and explicit acknowledgement before unsupported secondary streams or chapters are dropped.
- Quality-first MP4 output using H.264 CRF 3, the slow preset, `yuv420p`, and compatible audio copy or AAC-LC at 256 kbit/s.
- Collision-resistant automatic output names using `ai-video-YYYYMMDD-HHMMSS-<compact-UUIDv7>.mp4`.
- Atomic output publication, default replacement of explicit destinations, no-overwrite support, destination reservation, disk-space validation, and failed-workspace retention.
- Complete command-line interface for diagnostic preflight and full processing, including JSON results and cooperative Ctrl-C cancellation.
- Native PySide6 desktop interface with ordered clip entry, asynchronous preflight review, FIFO job queuing, progress reporting, reordering, cancellation, and actionable errors.
- Native external-tool settings for FFmpeg, FFprobe, Real-ESRGAN, and model-directory overrides with browse, PATH reset, automatic model discovery, and off-thread Vulkan validation.
- Typed, schema-versioned, private application settings with atomic persistence and corruption quarantine.
- Loguru diagnostics with rotating local logs and INFO-level shell-quoted records of every FFmpeg, FFprobe, and Real-ESRGAN subprocess launch.
- Bounded Real-ESRGAN Vulkan-memory retries using progressively smaller tiles and strict frame-inventory verification.
- Owned temporary workspaces with guarded cleanup after success or cancellation and retention after failure.
- Automated unit, integration, backend-contract, and headless GUI coverage.

### Security and safety

- Subprocesses execute from argument arrays with `shell=False` and explicit timeouts.
- Cancellation terminates complete child-process groups.
- Inputs with nonzero rotation are rejected, and every FFmpeg decoding path uses `-noautorotate`.
- Existing output files remain intact until a replacement has been encoded and verified successfully.
- The application performs no telemetry, analytics, automatic model downloads, or other application-initiated network operations.
- Exact subprocess command logs include local paths and must be treated as potentially sensitive.

### Compatibility

- Requires macOS 26.5.2 or later on Apple Silicon.
- Requires Python 3.10 or later.
- Requires separately installed FFmpeg, FFprobe, `realesrgan-ncnn-vulkan`, working Vulkan support, and the `realesrgan-x4plus` model files.
- Targets photographic and live-action footage; anime, animation, illustration, HDR processing, automatic rotation, cropping, and stretching are outside version 1 scope.

### Quality

- 180 automated tests pass for this release.
- Black, pycodestyle, and Pylint checks pass; Pylint reports 10.00/10.

### License

- Released as proprietary software. Copyright © 2026 AI Video Tools Project Owner. All rights reserved.
- Third-party tools, dependencies, and models remain governed by their respective licenses.
