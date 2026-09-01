# Version 2 Plan

## Status

- Development target: v2
- Released baseline: v1.0.0
- Current phase: Phase 7 — Stabilization and release (proposed)
- Last updated: 2026-08-31

## Purpose

Version 2 evolves the released v1.0.0 application without weakening its validated media behavior. The confirmed v2 product goals are:

1. Enhance the GUI.
2. Rename the project.

After those product changes, v2 proceeds through quality and product phases: an
initial stabilization pass, a deliberate refactoring pass, a fullscreen
preview enhancement, and a final stabilization/release pass.

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
| 1 | [Enhance GUI](1-enhance-gui.md) | Complete | A clearer, more accessible, native macOS workflow over the existing backend |
| 2 | [Rename Project](2-rename-project.md) | Complete | Apply the approved identity across package, application, storage, documentation, and release artifacts with an explicit migration policy |
| 3 | Stabilization | Complete | Stabilize performance, resource usage, lifecycle behavior, and exception/error handling before structural refactoring |
| 4 | Refactoring | Complete | Improve code readability and maintainability without weakening approved behavior |
| 5 | [GUI Enhancement Including Fullscreen Preview](5-gui-enhancement.md) | Complete | Complete the GUI enhancement with immersive fullscreen selected-source preview, keyboard playback, and clip-navigation controls |
| 6 | [Information Architecture Update and GUI Enhancement](6-information-architecture-gui.md) | Complete | Adopt a three-region Queue Monitoring workspace and improve task hierarchy without changing queue or media behavior |
| 7 | Stabilization and release | Proposed | Re-verify behavior after the fullscreen-preview feature and produce the v2 release artifacts |

Phases 1 through 6 are complete. Phase 7 remains proposed.

## Cross-phase decisions

### Resolved project rename

The complete migration reference is [v1 to v2 identity migration](rename-migration.md).
The approved Phase 2 identity decisions are:

- Project/product display name: `Advanced AI Video Tools`.
- Owner, copyright holder, developer, primary contact, and maintainer: `Pastry Personal 5`.
- Python distribution name: `advanced-ai-video-tools`.
- Python import package name: `advanced_ai_video_tools`.
- Primary CLI command: `advanced-ai-video-tools`.
- Legacy CLI policy: retain `ai-video-tools` as a deprecated alias through v2; remove it no earlier than v3 unless the owner revises this policy.
- macOS bundle identifier: `com.pastrypersonal5.advancedaivideotools`; treat it as permanent after the first v2 release.
- Persistent storage: create a new v2 storage location; do not migrate v1 settings, and remove the old settings location as part of the v2 transition.
- Runtime compatibility: only v2 is supported for execution after the transition; v1 and v2 are not a supported side-by-side installation.
- Automatic output filenames retain the existing `ai-` prefix.
- Repository: use the canonical repository `https://github.com/pastry-personal5/advanced-ai-video-tools`.
- Signing/notarization execution: deferred for v2; the approved distribution channel is outside the Mac App Store via Developer ID `.dmg`.
- Artifact and compatibility policies are resolved for the approved Phase 2 scope; deferred manual release checks are recorded in the phase file.

### Version 2 release policy

- Whether v1 receives critical fixes after v2 development begins.
- Whether v2 requires a settings-schema increment.
- Supported migration and rollback behavior.
- Distribution channel: outside the Mac App Store using Developer ID distribution via `.dmg`; signing/notarization execution remains a manual release action.
- Target-hardware acceptance criteria (human release checklist; deferred for v2).

### Phase 5 GUI-enhancement scope

The approved scope and acceptance criteria are maintained in [Phase 5 — GUI Enhancement Including Fullscreen Preview](5-gui-enhancement.md). The phase completes the GUI enhancement by extending only the existing selected-source, playback-only preview. It must not add preview editing, output processing, proxy generation, or changes to the media pipeline.

### Phase 6 information architecture and GUI-enhancement scope

The proposed scope and required decisions are maintained in [Phase 6 —
Information Architecture Update and GUI Enhancement](6-information-architecture-gui.md).
It may revise presentation hierarchy and interaction clarity only with explicit
owner approval.

### Phase 7 stabilization and release scope

- Phase 7 retains the previously planned final stabilization and v2 release-artifact work.
- Phase 7 begins only after Phases 5 and 6 are complete and their
  implementation, tests, and documentation are synchronized.
- Release work must re-verify fullscreen-preview behavior, including keyboard focus, help visibility, source navigation, player cleanup, and recovery from preview errors.

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
| 2026-08-24 | Sequence the post-rename work as Phase 3 Stabilization, Phase 4 Refactoring, and Phase 5 Stabilization and Release. |
| 2026-08-24 | Confirm that the Phase 1 minimum main-window size remains 1400 × 880 logical pixels; the temporary 1400 × 800 change is superseded. |
| 2026-08-24 | Mark Phase 1 complete with the documented security-limited native-display verification exception; move the active planning pointer to Phase 2. |
| 2026-08-24 | Approve `Advanced AI Video Tools` as the Phase 2 project name and `Pastry Personal 5` as owner, copyright holder, developer, primary contact, and maintainer. |
| 2026-08-24 | Approve `advanced-ai-video-tools` as the Python distribution and primary CLI command, `advanced_ai_video_tools` as the import package, and retain `ai-video-tools` as a deprecated CLI alias through v2. |
| 2026-08-24 | Approve `com.pastrypersonal5.advancedaivideotools` as the permanent v2 macOS bundle identifier. |
| 2026-08-24 | Defer v2 signing/notarization and target-macOS upgrade verification to the human release checklist; record `https://github.com/pastry-personal5/advanced-ai-video-tools` as the canonical repository. |
| 2026-08-24 | Approve distribution outside the Mac App Store using Developer ID distribution via `.dmg`; defer execution of signing/notarization to the human release checklist. |
| 2026-08-25 | Begin Phase 3 stabilization, including the proposed performance and exception/error-handling charter, while retaining opt-in native and benchmark checks. |
| 2026-08-25 | Disable performance benchmarks that include AI upscaling; performance measurements are limited to native GUI presentation or explicitly non-upscaling media work. |
| 2026-08-25 | Complete Phase 3 stabilization after the documented regression, native presentation, no-upscaling lifecycle/resource, and documentation checks. |
| 2026-08-29 | Approve Phase 5 as a fullscreen selected-source preview enhancement; move final stabilization and release artifacts to Phase 7. |
| 2026-08-29 | Approve fullscreen preview bindings: `0` first frame, `9` last frame, `j` previous clip, `l` next clip, `Space`/`k` play-pause, `Shift-P` play previous clip, `Shift-N` play next clip, `Esc` close, and `?` shortcut help. |
| 2026-08-29 | Approve two fullscreen entry points: an expand button in the preview pane and a `Start Fullscreen Preview` button at the right side of each source-clip list row; approve autoplay for `j` and `l`, and an auto-hiding fullscreen control bar revealed by pointer movement or keyboard input. |
| 2026-08-29 | Complete Phase 5 fullscreen preview with shared-player ownership, approved keyboard shortcuts, help overlay, row and pane entry points, auto-hide controls, regression coverage, and full quality-gate validation. |
| 2026-08-31 | Supersede the Phase 5 fullscreen control-bar decision: fullscreen selected-source preview is keyboard-only, with no clickable playback, seeking, help, or close controls. Rework both application views around a tall far-right preview column, keep the shared message tabs in a narrower left workspace, and add a Queue Monitoring preview for the selected completed job's published local output. |
| 2026-08-31 | Evolve Queue Monitoring's preview into a selected-job multipurpose surface: display the latest upscaled local PNG sample at every measured 16-frame interval while `UPSCALE` is running, retain that image through later active stages, and autoplay the published final video indefinitely after completion. |
| 2026-08-31 | Show the matched Original and Upscaled frame 1 in Queue Preview as soon as each file is ready, before continuing with the 16-frame sampling cadence. |
| 2026-08-31 | Add proposed Phase 6 for an information-architecture update and presentation-only GUI enhancement; reserve implementation until Phase 5 completion and explicit design approval are complete. |
| 2026-08-31 | Complete Phase 5 after the supported-macOS manual fullscreen acceptance check passed. |
| 2026-08-31 | Use the archived 2026-08-29 job-queue design review as the Phase 6 planning baseline: adapt its Active, Up Next, and History workspace to the current far-right Queue Preview and shared message splitter, pending review-gate approval. |
| 2026-08-31 | Preserve the far-right three-tab Queue Preview and the bottom integrated Global Messages/Job Messages area as fixed Phase 6 Queue Monitoring layout boundaries. Approve the Active/Up Next/History workspace, session-visible completed history, scrollable History at 1400 × 880, text-only status, and inline selected-job details. |
| 2026-08-31 | Begin Phase 6 implementation with presentation-only Active, Up Next, and History proxy views over the existing queue model; preserve canonical selection, far-right Queue Preview, and bottom integrated messages. |
| 2026-09-01 | Complete Phase 6 after inline queue actions, fixed responsive columns, keyboard selection/navigation, optical header alignment, regression coverage, and populated native Queue Monitoring capture acceptance. |
