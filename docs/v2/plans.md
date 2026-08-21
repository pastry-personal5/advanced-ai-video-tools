# Version 2 Plan

## Status

- Development target: v2
- Released baseline: v1.0.0
- Current phase: [Phase 1 — Enhance GUI](1-enhance-gui.md)
- Last updated: 2026-08-22

## Purpose

Version 2 evolves the released v1.0.0 application without weakening its validated media behavior. The two confirmed v2 goals are:

1. Enhance the GUI.
2. Rename the project.

Phase 1's GUI enhancement includes a single-window layout revision: a right-side
source-clip preview and an integrated, tabbed message area along the bottom.

The new project name, rename compatibility policy, and exact scope of later phases are not decided yet. Do not invent them during Phase 1.

## Planning principles

- Treat v1.0.0 as the behavioral baseline until an explicit v2 decision supersedes a contract.
- Keep the GUI and CLI as thin adapters over the same typed pipeline.
- Make each phase independently reviewable, tested, documented, and releasable where practical.
- Record product and architecture decisions before implementing behavior that depends on them.
- Preserve user data, settings, queued intent, output safety, and diagnostic usefulness across changes.
- Do not combine a visual redesign with unrelated media-pipeline changes.

## Roadmap

| Phase | Title | Status | Outcome |
| --- | --- | --- | --- |
| 1 | [Enhance GUI](1-enhance-gui.md) | Active planning | A clearer, more accessible, native macOS workflow over the existing backend |
| 2 | [Rename Project](2-rename-project.md) | Active planning; implementation follows Phase 1 | Consistent new identity across package, application, storage, documentation, and release artifacts with an explicit migration policy |
| 3 | v2 stabilization and release | Proposed | Migration verification, target-hardware acceptance, packaging, release notes, and v2.0.0 artifacts |

Phase 2 is established and may be planned while Phase 1 remains active, but implementation follows Phase 1 unless the user explicitly changes the execution order. Phase 3 remains provisional; create its phase file only after its entry criteria and release scope are approved.

## Cross-phase decisions still required

### Project rename

The complete decision checklist and migration plan are maintained in [Phase 2 — Rename Project](2-rename-project.md).

- New product display name.
- New Python distribution name and import-package name, if either will change.
- New CLI command name and whether the old command remains as a deprecated alias.
- macOS application identifier, bundle name, executable name, and signing identity.
- Settings, logs, and cache migration from the existing Qt application paths.
- Repository name and documentation-link migration.
- Output filename prefix: retain `ai-video-` or replace it.
- Copyright-holder name in the proprietary license.
- Compatibility duration for old settings, commands, and generated project files.

### Version 2 release policy

- Whether v1 receives critical fixes after v2 development begins.
- Whether v2 requires a settings-schema increment.
- Supported migration and rollback behavior.
- Signed/notarized application and distribution format.
- Target-hardware acceptance criteria.

## Version 2 invariants

Unless explicitly superseded, v2 retains these v1 guarantees:

- Concat first and run AI upscaling at most once.
- Preserve aspect ratio and never rotate, crop, or stretch implicitly.
- Preserve accepted BT.709 or SMPTE 170M matrices and reject unsupported HDR.
- Preserve exact rational timing using time-base-derived verification tolerance.
- Maintain the first-audio, silence, pad, trim, and explicit stream-drop acknowledgement policy.
- Publish verified output atomically and preserve existing output after failure or cancellation.
- Run one processing job at a time through the frontend-independent FIFO.
- Keep FFmpeg, FFprobe, Real-ESRGAN, and model installation user-managed.
- Perform no telemetry, automatic model downloads, or other implicit network activity.
- Keep subprocess execution shell-free even when logs render shell-quoted diagnostic commands.

## Phase completion protocol

A phase is complete only when:

1. Its approved outcomes and acceptance criteria are implemented.
2. Relevant automated tests cover success, failure, state transitions, and regressions.
3. `make check` passes.
4. Required target-macOS manual checks are recorded.
5. README, architecture, changelog, and planning status agree with the implementation.
6. Remaining risks and deferred decisions are explicit.

## Decision log

| Date | Decision |
| --- | --- |
| 2026-08-22 | Set v2 as the active development target; keep v1.0.0 as the released baseline. |
| 2026-08-22 | Establish GUI enhancement and project renaming as confirmed v2 goals. |
| 2026-08-22 | Begin Phase 1: Enhance GUI. |
| 2026-08-22 | Establish Phase 2: Rename Project; implementation follows Phase 1 unless explicitly redirected. |
| 2026-08-22 | Limit the Phase 1 video preview to the currently selected source clip. |
| 2026-08-22 | Make the Phase 1 source preview playback-only, with no editing, filtering, trimming, frame export, or concat-boundary controls. |
| 2026-08-22 | Use PySide6 `QMediaPlayer` with `QVideoWidget` for Phase 1 preview playback and keep FFmpeg and Real-ESRGAN out of the presentation layer. |
| 2026-08-22 | Define the widget as a non-color-accurate convenience preview; FFprobe-backed preflight and the processing pipeline remain authoritative for all media interpretation and validation. |
| 2026-08-22 | Treat unsupported native preview formats as non-blocking, show the approved preview-unavailable message, and generate no proxy videos in Phase 1. |
| 2026-08-22 | Make preview playback fill the available width while preserving the exact unrotated display aspect ratio, with no crop, stretch, or rotation. |
| 2026-08-22 | Add the Phase 1 main-window layout goal: keep the source-clip preview in the far-right content column and reserve an integrated message widget at the bottom of the window. |
| 2026-08-22 | Use a two-tab `QTabWidget` for integrated messages: `Global Messages` for application-wide log-style notices and `Job Messages` for the selected/current job's notices. |
| 2026-08-22 | Give the right-side preview pane a default width-to-height ratio of 3:4; its default height tracks the available window content height after the bottom message widget, while the displayed video itself preserves its exact source aspect ratio. |
| 2026-08-22 | Define Phase 1 source-preview playback controls as previous clip, play/pause, go to the beginning, go to the end, and next clip. Selecting or navigating to a source clip starts playback automatically. Loop controls are not included in v2. |
| 2026-08-22 | Use icon-only source-preview controls: previous clip, go to beginning, play/pause, go to end, and next clip. Previous/next clip use double-triangle skip glyphs, while beginning/end use single-triangle seek glyphs. Previous/next clip selection starts the newly selected clip automatically; controls are disabled at the first/last clip rather than wrapping. Provide accessible names and tooltips for every icon. |
| 2026-08-22 | Start the preview muted on first launch, remember mute and volume as non-safety preferences, and never autoplay audio; autoplay begins muted and audio requires explicit user action. Changing selection stops the prior source and loads the new local source asynchronously while preserving visible concat order. Pause preview when processing begins, do not resume it automatically, and release the player on window close. Accept only local files already in the editor; reject URLs and remote sources. Show player failures inline without replacing authoritative preflight errors. |
| 2026-08-22 | Use a far-left vertical two-icon navigation rail: the first icon opens Job Creation controls and hides Queue Monitoring controls; the second opens Queue Monitoring controls and hides Job Creation controls. Keep the bottom integrated message widget visible in both views. |
| 2026-08-22 | Remove the v1 GUI heading labels `Video processing jobs` and `One job runs at a time • Default output height: {settings.target_height}p` as part of the Phase 1 layout simplification. |
| 2026-08-22 | Keep the v2 GUI dark-themed and use Codex-created app-owned icons. Accept local file-manager drag-and-drop into the source list, retain custom target height without presets, use native preview playback as-is for rotation, move External Tools to `Edit` → `Preferences` in a separate window, remove the main-window External Tools button, omit retry support, log completed jobs globally, show five-line tails in both message tabs, and display queue `Status` before `Job Name`. |
| 2026-08-22 | Set the Phase 1 window to an initial/minimum 1536 × 1536 pixels with a user-resizable message area and no preview scrolling. Accept duplicate clips and show filenames only. Put selected-job details and the job-start output name in `Job Messages`; use queue `Status`, `Job Name`, and `Remove` columns with both stage/whole-job progress, no-confirmation removal for cancelled/failed jobs, session-only messages, automatic `Job Messages` activation, `No job is selected.` empty state, local timestamps without timezone, inline errors, no message actions/severity controls, and temporary identity `Advanced AI Video Tools`. |
