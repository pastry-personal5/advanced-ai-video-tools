# Changelog

All notable changes to AI Video Tools are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Set version 2 as the active development target while retaining v1.0.0 as the released behavior baseline.
- Established GUI enhancement as Phase 1 and project renaming as a required v2 goal.
- Defined project renaming as Phase 2 with explicit identity, compatibility, persistent-data migration, packaging, legal, and verification gates.
- Defined the Phase 1 video-preview scope as the currently selected source clip only.
- Defined the Phase 1 source preview as playback-only, without timeline or media-editing features.
- Selected PySide6 `QMediaPlayer` and `QVideoWidget` as the planned Phase 1 preview backend, isolated from FFmpeg and Real-ESRGAN processing.
- Defined the Phase 1 widget as selected-source playback while retaining FFprobe-backed preflight and the processing pipeline as the media contract.
- Defined unsupported native preview formats as a non-blocking state with no FFmpeg proxy fallback.
- Defined full-width Phase 1 preview playback with exact unrotated aspect preservation and no crop, stretch, or rotation.

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
