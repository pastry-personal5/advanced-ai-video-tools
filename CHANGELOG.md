# Changelog

Notable changes follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Configurable GUI-only related-file deletion rules with safe basename matching,
  schema migration, ordered editing, and best-effort Trash reporting.
- Background-probed dimensions for the focused source clip.
- A searchable, resizable **Preferences → Settings** dialog with
  **Editor → File** and **Tools → External Tools** pages, session-only geometry,
  explicit validation states, and one atomic shared draft.

### Changed

- Standardized application APIs around descriptive `execute_*`, `create_*`, and
  `begin_*` names and introduced shared typed stage and Qt worker-lifecycle
  boundaries.
- Verified non-GUI dependency direction in the V3 Phase 4 modularity audit.
- Renamed the internal `gui.preferences` module and tool validator to match the
  unified Settings ownership.

## [2.0.0] - 2026-09-01

### Added

- Redesigned dark GUI with Job Creation and Queue Monitoring workspaces,
  selected-source playback/fullscreen preview, session messages, and
  Active/Up Next/History queue regions.
- Queue Preview tabs for original/upscaled frame samples and completed output.
- Native Apple Silicon presentation/capture checks and an unsigned development
  DMG workflow.

### Changed

- Renamed the distribution, command, import package, GUI identity, application
  data, and bundle identifier to Advanced AI Video Tools. The deprecated
  `ai-video-tools` command remains a warning compatibility alias.
- Moved settings to typed schema-versioned YAML with guarded v1 migration.
- Added graceful terminal Ctrl+C handling for the GUI and refined queue,
  fullscreen, preview, and source-file interactions.

### Distribution

- Finder launch and Homebrew/MacPorts tool discovery are verified for the
  unsigned development DMG. Developer ID signing and notarization remain
  deferred. See the [v2.0.0 release notes](docs/v2/release-notes-v2.0.0.md).

## [1.0.0] - 2026-08-21

### Added

- Complete concat-first video pipeline with one optional Real-ESRGAN stage,
  stream-copy or lossless normalization, exact timing/color/audio policy, and
  verified quality-first MP4 publication.
- CLI preflight/process commands and native PySide6 queue GUI.
- User-managed tool discovery and Vulkan/model validation.
- FIFO execution, measured progress, cancellation, safe workspace cleanup,
  atomic publication, collision-safe naming, and no-overwrite support.
- Typed settings, rotating diagnostics, unit/integration/GUI coverage, and no
  application-initiated network activity.

### Compatibility

- macOS 26.5.2+ on Apple Silicon and Python 3.10+.
- Photographic/live-action SDR input; animation-specific models, HDR, rotation,
  crop, and stretch were outside the 1.0 scope.

### License

- Proprietary software, copyright © 2026 Pastry Personal 5. Third-party tools,
  dependencies, and models retain their own terms.
