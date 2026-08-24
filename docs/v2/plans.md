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
| 1 | [Enhance GUI](1-enhance-gui.md) | Verification | A clearer, more accessible, native macOS workflow over the existing backend |
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
- Processing preserves aspect ratio and never rotates, crops, or stretches implicitly; preview playback may follow native rotation behavior.
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
| 2026-08-22 | Establish GUI enhancement and project renaming as v2 goals; begin Phase 1 and defer Phase 2 implementation until Phase 1 is complete. |
| 2026-08-22 | Limit the Phase 1 preview to the selected source clip, make it playback-only, use `QMediaPlayer`/`QVideoWidget`, and keep processing/preflight authoritative. Native preview failure is non-blocking and creates no proxy media. |
| 2026-08-22 | Use a single window with a far-left two-icon rail, Job Creation and Queue Monitoring views, a far-right source preview, and a persistent two-tab message widget at the bottom. The window starts at and cannot shrink below 1536 × 1024; message height is user-resizable and preview scrolling is not used. |
| 2026-08-22 | Use icon-only preview controls for previous clip, play/pause, beginning, end, and next clip. Clip navigation autoplays, does not wrap, and has no loop controls. Preview starts muted, remembers mute/volume preferences, loads only local editor files asynchronously, pauses when processing starts, and follows native rotation behavior. |
| 2026-08-22 | Keep the GUI dark-themed with Codex-created app-owned icons. Accept file-manager drag-and-drop in drop order, allow duplicates, show filenames only, retain custom target height without presets, and use `Advanced AI Video Tools` as the temporary identity. |
| 2026-08-22 | Move advanced options and External Tools to a separate `Edit` → `Preferences` window; remove the main-window External Tools button. Do not implement retry support. |
| 2026-08-22 | Use `Status`, `Job Name`, and `Remove` queue columns; show stage and whole-job progress; allow no-confirmation removal of cancelled/failed rows; show selected-job details and the job-start output name in `Job Messages`. |
| 2026-08-22 | Keep messages session-only with local timestamps, no severity/filter/action controls, automatic `Job Messages` activation, the empty state `No job is selected.`, and exactly five visible lines per tab. Completed jobs append to `Global Messages`; errors remain inline. |
| 2026-08-22 | Complete the Phase 1 audit and interaction specification, covering the current GUI hierarchy, workflows, usability findings, target state wireframes, focus criteria, and 1536 × 1024 resizing behavior. |
| 2026-08-22 | Approve the Phase 1 visual specification: native macOS system typography, 8 px spacing grid, comfortable 32 px controls/rows, and Codex-created monochrome vector icons for navigation, preview, and terminal-job removal. |
| 2026-08-22 | Complete the Phase 1 presentation-architecture specification for typed presentation state, centralized UI semantics, Qt ownership/thread boundaries, shutdown, and view binding. |
| 2026-08-23 | Make the Phase 1 GUI always dark; apply the application-owned dark palette regardless of macOS appearance. |
