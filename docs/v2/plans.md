# Version 2 Plan

## Status

- Development target: v2
- Released baseline: v1.0.0
- Current phase: [Phase 2 — Rename Project](2-rename-project.md) (complete)
- Last updated: 2026-08-24

## Purpose

Version 2 evolves the released v1.0.0 application without weakening its validated media behavior. The confirmed v2 product goals are:

1. Enhance the GUI.
2. Rename the project.

After those product changes, v2 proceeds through three quality phases: an
initial stabilization pass, a deliberate refactoring pass, and a final
stabilization/release pass.

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
| 1 | [Enhance GUI](1-enhance-gui.md) | Complete | A clearer, more accessible, native macOS workflow over the existing backend |
| 2 | [Rename Project](2-rename-project.md) | Complete | Apply the approved identity across package, application, storage, documentation, and release artifacts with an explicit migration policy |
| 3 | Stabilization | In progress | Stabilize performance, resource usage, lifecycle behavior, and exception/error handling before structural refactoring |
| 4 | Refactoring | Proposed | Improve code readability and maintainability without weakening approved behavior |
| 5 | Stabilization and release | Proposed | Re-verify behavior after refactoring and produce the v2 release artifacts |

Phase 2 is complete after Phase 1. Phase 3 is now in progress under [Phase 3 — Stabilization](3-stabilization.md); Phases 4–5 remain provisional.

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

Approved Phase 2 identity decisions:

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

### Phase 3 stabilization scope

- Phase 3 is dedicated to performance, resource, exception, and error-handling checks before refactoring.
- Detailed workloads, metrics, budgets, and pass/fail thresholds are proposed below and remain subject to owner approval.

#### Proposed Phase 3 performance charter

Use repeatable local fixtures on the supported Apple Silicon reference host. Record
the median and p95 for timings, and compare post-change results with the same
baseline rather than treating media throughput as an absolute promise.

- **Startup:** measure process launch to visible main window for cold and warm starts; target ≤6 seconds cold and ≤3 seconds warm.
- **GUI responsiveness:** measure input-to-visible-state latency while idle, previewing, validating, and monitoring a job; target p95 ≤100 ms idle and ≤250 ms during active work.
- **Preview selection:** measure source-row selection to asynchronous media-source assignment and selection-to-first-frame for a supported fixture; target assignment ≤100 ms and first frame ≤2 seconds, without GUI-thread blocking.
- **Queue submission:** measure Preflight activation to worker-start acknowledgement; target GUI return ≤100 ms and no long-running work on the presentation thread.
- **Memory stability:** record RSS at startup, idle, preview playback, preflight, and each pipeline stage; after ten sequential jobs, allow no unexplained monotonic growth and no more than 10% growth over the first-job peak (with a 100 MB minimum tolerance).
- **Resource ownership:** verify that every completed, failed, cancelled, and preview-failure path releases media outputs, worker threads, queue ownership, and temporary resources; repeated preview selection must not accumulate live players or outputs.
- **Pipeline throughput:** no performance benchmark may invoke AI upscaling. Any future fixed-media throughput measurement must explicitly skip Real-ESRGAN and document that policy; report stage durations, total duration, CPU utilization, and peak RSS, with regression alerts at >10% versus baseline.
- **Disk usage:** measure peak workspace size and retained failed-workspace size; successful and cancelled jobs must release temporary data according to policy, and cleanup should complete within 5 seconds after terminal state where no external process remains.
- **Cancellation:** measure cancellation request to terminal queue state for queued and active jobs; target queued cancellation ≤1 second and active cancellation ≤10 seconds after the current child process exits.
- **Shutdown:** measure window-close to joined preview/validator/queue workers; target ≤5 seconds with no live worker or child process remaining.
- **Repeatability:** run each benchmark at least three times, record host/OS/tool/model versions, fixture properties, and whether the result is cold or warm; keep raw results out of the repository and retain only summarized evidence.

#### Proposed Phase 3 exception and error-handling charter

- **Boundary coverage:** exercise malformed settings, missing tools, invalid media, unsupported media, permission failures, insufficient disk space, queue rejection, worker exceptions, cancellation races, preview decode failures, and shutdown during active work.
- **Containment:** every expected failure must terminate in a typed result or controlled Qt state; no exception may escape a worker thread, leave the GUI permanently busy, or terminate the process unexpectedly.
- **User feedback:** each failure must provide a concise actionable GUI message, preserve the relevant job/source state, and identify the next legal action without exposing raw subprocess command lines.
- **Diagnostics:** each failure must retain detailed local diagnostics with stable job/stage context, exception type, and a redacted actionable cause; repeated failures must not flood the GUI message history.
- **Cleanup invariants:** fault injection must verify release of queue ownership, worker threads, media outputs, reservations, temporary directories, and partial publications on every failure and cancellation path.
- **Recovery behavior:** after a failed validation, preview load, queued job, active job, or settings save, the application must remain usable for a subsequent valid operation without restart.
- **Concurrency safety:** test exception delivery across worker-to-Qt boundaries and cancellation/error races; GUI state mutations must occur on the Qt thread and terminal jobs must be reported exactly once.
- **Regression gate:** add failure-path tests for every corrected defect and require zero unexpected tracebacks, leaked workers, orphaned child processes, or stale busy indicators in the Phase 3 acceptance run.

### Phase 4 refactoring scope

- Phase 4 is dedicated to improving code readability and maintainability after Phase 3 stabilization.
- Refactoring must preserve approved GUI behavior, CLI behavior, media-pipeline invariants, settings safety, queue semantics, and public compatibility unless a later decision explicitly changes them.
- Prefer small independently validated slices over broad rewrites.
- Consolidate duplicated logic, clarify module and class responsibilities, reduce deeply nested control flow, improve names and type signatures, isolate Qt presentation code from application services, and make lifecycle ownership explicit.
- Polish variable names throughout the touched code: locals, parameters, attributes, signal payloads, and intermediate results should describe their domain meaning rather than implementation shorthand; preserve public names where compatibility requires them.
- Reduce functions with excessive statements by extracting cohesive helper functions with explicit inputs and outputs; retain the current orchestration flow and signal/thread boundaries.
- Use thin layers of abstraction around existing behavior—such as construction, validation, formatting, lifecycle transitions, and event mapping—without adding speculative frameworks, indirection, or new ownership models.
- Keep each extraction reviewable: one responsibility per helper, typed boundaries, preserved exceptions, and focused regression coverage before broader movement.
- Add or strengthen tests before moving behavior across boundaries; every refactoring slice must retain focused regression coverage and pass the full quality gate.
- Do not combine Phase 4 with new product features, branding changes, media-policy changes, or speculative compatibility abstractions.
- Detailed module targets, complexity budgets, and the policy for internal API renames remain to be approved before the phase file is created.

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
