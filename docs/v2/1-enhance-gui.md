# Phase 1: Enhance GUI

## Status

- Phase: 1
- State: In progress
- Started: 2026-08-22
- Released baseline: v1.0.0
- Target: v2

## Objective

Improve the native macOS GUI so job creation, validation, queue monitoring, recovery, settings, diagnostics, and the main-window layout are easier to understand and operate while retaining the existing typed backend and media-safety contracts. Phase 1 explicitly adds a far-right source-clip preview region and an integrated bottom message area.

This phase enhances the GUI; it does not redesign the media pipeline.

## Approved decisions

### Source video preview scope

- Phase 1 adds a video preview for only the currently selected source clip in the job editor.
- The preview is playback-only.
- The playback backend is PySide6 `QMediaPlayer` with `QVideoWidget`.
- FFmpeg, FFprobe, Real-ESRGAN, media command construction, and processing services remain outside the preview presentation layer.
- The widget is explicitly a convenience preview, not a color-accurate or processing-authoritative representation.
- FFprobe-backed preflight and the processing pipeline remain authoritative for rotation, HDR, color metadata and interpretation, timing, stream inventory, compatibility, and every processing decision.
- `QMediaPlayer` rendering, metadata, duration, errors, or playback success must not be promoted into job validation or execution-plan input.
- macOS native playback may reject a format that FFmpeg and FFprobe can process; this is a preview limitation, not a processing rejection.
- Preview load, decode, or format failure is non-blocking and displays: “Preview unavailable; preflight can still inspect this clip.”
- Phase 1 does not generate FFmpeg proxy videos or invoke another playback fallback when native preview is unavailable.
- The video presentation fills the available preview width, and its height is derived from the clip's exact display aspect ratio.
- Playback preserves the native player's display aspect ratio. The application never stretches or crops the displayed video and does not add rotation correction or rotation suppression.
- Full-width layout must resize vertically rather than distort the image when the preview region's geometry differs from the source aspect ratio.
- Changing the source-clip selection changes the preview source without changing concat order or job intent.
- Queue selection, active jobs, merged intermediates, completed outputs, and retained failed-workspace media do not become preview sources in Phase 1.
- The preview does not simulate normalized, concatenated, upscaled, color-converted, encoded, or final published output.
- The preview provides no trim points, timeline editing, filters, frame export, or concat-boundary editing.
- Preview availability or playback success is not an authoritative media validation result and cannot replace preflight.

### Source-preview playback controls

- Provide only these playback controls, in order: play/pause, go to the first frame of the selected clip, go to the last frame of the selected clip, go to the previous clip, and go to the next clip.
- Selecting a clip in the ordered source list automatically starts playback for that clip.
- The previous-clip and next-clip controls move selection by one row in the ordered source list and automatically start playback for the newly selected clip. They do not reorder clips or mutate frozen job intent.
- Disable previous-clip at the first source clip and next-clip at the last source clip; navigation does not wrap around.
- “Go to the first frame” seeks to the start of the selected clip; “go to the last frame” seeks to its last frame without changing the ordered input list or job intent.
- Do not provide loop, repeat, A/B, trim, timeline-editing, filtering, frame-export, or concat-boundary controls in v2.
- Autoplay, seeking, and control state remain convenience-preview behavior and never become authoritative preflight or processing input.
- Render the five controls as icon-only buttons in this order: play/pause uses the conventional play triangle and pause bars; go-to-first-frame uses a leading vertical bar with one left-pointing triangle; go-to-last-frame uses one right-pointing triangle with a trailing vertical bar; previous clip uses double left-pointing triangles; next clip uses double right-pointing triangles. The double- versus single-triangle treatment distinguishes clip navigation from seeking within the selected clip.
- Use Qt-native icon construction or small app-owned vector glyphs for these controls rather than relying on undocumented platform theme names or third-party icon assets. Keep one consistent monochrome visual treatment at the supported display scale.
- Every icon-only button has a programmatic accessible name, a tooltip, and a non-color state indication. The play/pause accessible name reflects the action that will occur next (for example, “Pause preview” while playing and “Play preview” while paused).
- Start preview playback muted on first launch. Remember mute and volume only as non-safety preferences, and never autoplay audio when a clip is selected or navigated to; autoplay begins muted and audio requires an explicit user action.
- When selection changes, stop the previous media source and load the newly selected local source asynchronously. Preserve the visible concat order independently from preview selection.
- Automatically pause the preview when a processing job begins and do not resume it when processing ends. Release the media player cleanly when the main window closes.
- Accept preview sources only from local files already present in the job editor. Reject URLs and remote media sources so preview cannot introduce network activity.
- Show native player load/decode failures inline within the preview area. These failures remain non-authoritative and must never bypass, replace, or downgrade FFprobe-backed preflight errors.

### Main-window layout and integrated messages

- Phase 1 includes a main-window layout revision as an explicit GUI goal.
- Keep the source-clip preview in the far-right content column of the application window.
- The preview pane's default geometry uses a 3:4 width-to-height ratio. Its default height tracks the available application content height after the bottom message area, allowing for the menu/rail, spacing, and window margins. The default width is therefore three quarters of that preview height.
- Use an initial and minimum main-window size of 1536 × 1024 pixels. The window must not shrink below that minimum.
- Make the integrated message widget's height user-resizable. Do not introduce preview scrolling; the minimum window size is the lower bound for the layout.
- The pane geometry is a layout default, not a video distortion rule. The currently selected source clip remains the only preview source, and the displayed video preserves the native player's display aspect ratio with no crop or stretch. Unused space inside the pane is acceptable when the source aspect ratio differs from the pane's 3:4 default.
- Add one integrated message widget along the bottom of the application window. It spans the main content width and remains visible while editing and monitoring jobs.
- Implement the message widget as a two-tab `QTabWidget`. The tabs are named `Global Messages` and `Job Messages`.
- `Global Messages` presents application-wide log-style notices such as startup, tool-configuration, settings, preflight-gate, and shutdown events. `Job Messages` presents log-style notices for the selected/current job, including stage changes, measured progress summaries, warnings, failures, cancellation, cleanup, and publication results.
- Message entries include a local timestamp without timezone information and concise text. Do not add severity levels or filtering controls in v2; state must remain understandable from the message text and native control state, not color alone. Exact sensitive subprocess command lines remain in the diagnostic log rather than being shown in the widget.
- Each tab contains a read-only log widget showing the complete in-memory history for that tab, with the newest line at the bottom. The widget's minimum height must display at least five lines; normal scrolling may expose older lines.
- Keep message history for the duration of the running application only. Do not persist it.
- Do not add clear, copy, or diagnostics-reveal actions to the message tabs in v2.
- Selecting a job activates the `Job Messages` tab. When no job is selected, that tab displays `No job is selected.`
- When a job reaches `COMPLETED`, append a concise completion line to `Global Messages`.
- Message rendering is presentation-only. It must consume typed application/queue events and must not move probing, processing, logging configuration, or other long-running work onto the GUI thread.
- A preview failure remains a non-blocking message for the relevant source clip and does not become a processing or job-validation message unless authoritative preflight reports the same issue.

### View navigation

- Add a vertical icon rail at the far left of the application window with two mutually exclusive navigation buttons.
- The first button opens the Job Creation view. It shows job-creation controls, including the ordered source list and source preview, and hides controls related only to queue monitoring.
- The second button opens the Queue Monitoring view. It shows queue, progress, selected-job, reorder, and cancellation controls, and hides controls related only to job creation.
- Use semantic icon glyphs for the buttons: a document-plus/create icon for Job Creation and a stacked-list/queue icon for Queue Monitoring. Each icon-only button has an accessible name and tooltip.
- Switching views changes visibility only. It does not cancel work, alter queued requests, reorder source clips, or discard unsaved job-creation state. Each view preserves its state while hidden.
- The bottom integrated message widget remains visible in both views, including while switching, and its selected tab and message contents are preserved.
- The navigation rail and message widget are part of the single main window; they do not open separate windows or dialogs for ordinary view switching.

### Header simplification

- Remove the v1 GUI heading label `Video processing jobs`.
- Remove the v1 GUI subtitle label `One job runs at a time • Default output height: {settings.target_height}p`.
- Do not replace either label with another persistent heading or status sentence as part of this decision. Other functionality, including External Tools configuration, remains governed by its own Phase 1 layout decision.

### Job-creation details and identity

- Source-list rows show filenames only. Do not add thumbnails or inline media metadata in v2.
- Duplicate source clips are accepted without a duplicate warning or rejection.
- Show the generated output name immediately after a job starts in the selected job's `Job Messages` tab.
- Put advanced GUI options in the separate `Edit` → `Preferences` window.
- Use `Advanced AI Video Tools` as the temporary v2 display identity until the later project-rename decision is implemented.

### Visual style and icon authorship

- Keep the v2 GUI in the approved dark-theme style. Phase 1 does not add a light-theme or system-theme variant.
- Codex creates the GUI icon set as app-owned vector artwork, including navigation-rail, source-preview, and queue icons. Do not add third-party icon assets or an unreviewed platform icon dependency.
- Generated icons must remain legible at the supported display scale, work against the dark background, and expose accessible names independently of their artwork.

### Typography, spacing, density, and final icon inventory

- Use the native macOS system sans font through Qt's system-font APIs; do not bundle a custom typeface.
- Use these initial type roles: 17 pt semibold section headings, 13 pt regular body/control text, 12 pt secondary text, and 12 pt fixed-width text for the two log tails. Respect system text scaling and allow long text to wrap or elide safely.
- Use an 8 px spacing grid with 4 px icon-to-label gaps, 8 px control gaps, 16 px group padding, 24 px view margins, and 32 px separation between major regions.
- Use comfortable macOS density: 32 px minimum interactive-control height, 32 × 32 px icon-button hit area, 32 px queue/source rows, and at least 8 px between adjacent hit targets. Do not add a compact-density mode in v2.
- Generate the final icon inventory as app-owned monochrome vector artwork:
  - Navigation rail: `Job Creation` (document-plus) and `Queue Monitoring` (stacked list).
  - Source preview: `Play/Pause`, `First frame` (bar plus single-left triangle), `Last frame` (single-right triangle plus bar), `Previous clip` (double-left triangles), and `Next clip` (double-right triangles).
  - Queue: `Remove` (trash) for cancelled and failed rows only.
- Keep source-list actions (`Add Clips…`, `Remove`, `Move Up`, `Move Down`) and `Edit` → `Preferences` text-labeled rather than adding extra icon-only controls. Do not add status/severity icons in v2.
- Draw icons at an 18 px visual mark inside the 32 × 32 px hit area, use the same stroke/fill treatment throughout, and provide accessible names and tooltips independently of the artwork.

### Source-list input and preview interpretation

- Allow users to drag local video files from the operating system file manager into the source-clip list. Dropped files are appended in drop order and remain subject to existing local-file validation.
- Retain the file-picker workflow alongside drag-and-drop. Reject URL and remote-media drops.
- Use native preview playback as-is in v2. Do not add a preview rotation gate, rotation correction, or custom no-rotation renderer. Authoritative FFprobe preflight and processing validation continue to govern rotation and all media policy.
- Do not add output-height presets in v2; retain the custom target-height control and its existing validation.

### Preferences menu

- Add an application menu item `Edit` → `Preferences`.
- Selecting `Preferences` opens a separate preferences window for External Tools configuration and validation.
- Remove the `External Tools…` button from the main window. External-tool settings remain available through the Preferences menu and continue to apply only to future drafts after successful validation and persistence.

### Queue and message presentation

- Do not implement retry support in v2. Failed and cancelled jobs retain their existing terminal behavior without a retry action.
- Present the job queue with a multi-column Qt model/view widget. The first column is `Status` and contains the textual job status; the second column is `Job Name`. Additional columns may be added only through a later approved decision.
- Add a third queue column containing a `Remove` action. The action is available for cancelled and failed jobs; the user controls when those terminal rows leave the session history.
- Show both stage progress and whole-job progress in Queue Monitoring.

## Current baseline

The v1 GUI already provides:

- Ordered input-clip selection and reordering.
- Output-directory and target-height controls.
- Immutable typed job-request creation.
- Off-thread diagnostic preflight.
- Complete issue review and exact-inventory stream-drop acknowledgement.
- FIFO queue submission, progress, reorder, and cancellation controls.
- External-tool path editing, PATH/automatic resets, and off-thread validation.
- Atomic preference persistence and diagnostics-path display.

Phase 1 must build on these capabilities instead of duplicating them.

## Required design decisions

All product decisions affecting the current layout and preview slice are approved.
Before implementation, only these compact implementation details remain:

- Exact splitter proportions and internal spacing within the fixed 1536 × 1024 minimum window.

Retain native Qt focus/accessibility behavior, keep preflight acknowledgement as
the safety gate, and keep ordinary field validation inline. Do not add
v2-specific shortcuts, VoiceOver announcements, reduced-motion behavior, or
message actions.

## Work breakdown

### 1. Audit and interaction specification

- [x] Capture the current GUI hierarchy, workflows, focus order, and state transitions. See [Phase 1 GUI Audit and Interaction Specification](1-enhance-gui-audit.md).
- [x] Identify usability failures using concrete scenarios: first run, valid job, blocked preflight, acknowledgement, queued job, active cancellation, failure, and tool misconfiguration. See [Phase 1 GUI Audit and Interaction Specification](1-enhance-gui-audit.md).
- [x] Approve the information architecture: a far-left two-icon rail, mutually exclusive Job Creation and Queue Monitoring views, and a persistent bottom message area.
- [x] Approve removal of the v1 `Video processing jobs` and `One job runs at a time • Default output height: {settings.target_height}p` labels.
- [x] Approve the dark-theme visual direction and Codex-created app-owned icon set.
- [x] Define typography, spacing, density, and final icon inventory details in the approved visual specification above.
- [x] Define wireframes for empty, editing, validating, queued, running, failed, cancelled, and completed states. See [Phase 1 GUI Audit and Interaction Specification](1-enhance-gui-audit.md).
- [x] Establish measurable accessibility and window-resizing criteria. See [Phase 1 GUI Audit and Interaction Specification](1-enhance-gui-audit.md).

### 2. Presentation architecture

- [x] Separate durable presentation state from declarative widget construction where this improves testability. See [Phase 1 Presentation Architecture](1-enhance-gui-presentation-architecture.md).
- [x] Centralize application identity strings and brand-neutral UI constants in preparation for the later rename. See [Phase 1 Presentation Architecture](1-enhance-gui-presentation-architecture.md).
- [x] Define reusable spacing, status, and icon semantics without introducing an unnecessary theme framework. See [Phase 1 Presentation Architecture](1-enhance-gui-presentation-architecture.md).
- [x] Preserve Qt ownership, signal/slot thread boundaries, and clean shutdown. See [Phase 1 Presentation Architecture](1-enhance-gui-presentation-architecture.md).
- [x] Define the main-window content layout with the editor/queue region, the far-right source-preview pane, and the bottom integrated message widget.
- [x] Define the preview-pane initial geometry as 3:4 width-to-height, derive its width from the post-message-area available height, keep the window at or above 1536 × 1024, make message height user-resizable, and avoid preview scrolling.
- [x] Define typed global-message and job-message events, session-only ownership, complete per-tab in-memory history, completion routing, and GUI-thread delivery without changing backend logging or queue semantics.
- [x] Define the two-view navigation state, icon semantics, state preservation, keyboard traversal, and visibility boundaries for creation versus queue controls.

### 3. Job editor enhancement

- [ ] Implement the approved layout and field hierarchy.
- [x] Remove the two v1 heading labels without changing job state, settings behavior, or External Tools configuration behavior.
- [x] Add the integrated two-tab message widget at the bottom of the main window and connect it to global and selected-job event streams.
- [x] Add the far-left two-icon navigation rail and switch between Job Creation and Queue Monitoring views without losing either view's state.
- [x] Add the far-right source-preview pane and verify its default 3:4 geometry, available-height calculation, and responsive behavior.
- [ ] Add previous-clip, play/pause, go-to-first-frame, go-to-last-frame, and next-clip controls; start playback automatically when the selected source clip changes; disable navigation at list boundaries; provide no loop controls.
- [ ] Use the approved icon-only glyphs, accessible names, tooltips, enabled/disabled states, and keyboard focus behavior for all source-preview controls.
- [x] Add video-file drag-and-drop from the operating-system file manager, append accepted files in drop order, retain the picker, and reject non-video, URL, and remote drops.
- [x] Render filename-only source rows without metadata or thumbnails.
- [x] Add a video preview whose source is exclusively the currently selected source clip.
- [x] Implement playback with PySide6 `QMediaPlayer` and `QVideoWidget` behind a small, testable presentation boundary.
- [x] Use `Qt.AspectRatioMode.KeepAspectRatio` and a width-driven container whose height follows the exact display aspect ratio without adding application-level rotation handling.
- [ ] Verify that preview resizing never crops, stretches, or substitutes a rounded aspect ratio.
- [ ] Label and describe the widget visibly and accessibly as a convenience preview that is not color-accurate or processing-authoritative.
- [ ] Ensure selection-driven preview changes cannot reorder clips, mutate frozen job intent, or influence authoritative preflight results.
- [ ] Start muted on first launch, persist only mute/volume preferences, stop and asynchronously reload on selection changes, and preserve concat order independently from preview selection.
- [ ] Pause preview at processing start, avoid automatic resume, and release the player during window shutdown.
- [ ] Reject URL/remote preview sources and accept only local files already in the editor.
- [ ] Ensure player metadata, rendering, duration, errors, and playback success cannot influence rotation, HDR, color, timing, stream, compatibility, or processing decisions.
- [x] Map native player load, decode, and unsupported-format errors to the inline message “Preview unavailable; preflight can still inspect this clip.”
- [ ] Keep a preview-unavailable source clip in the ordered input list and allow authoritative preflight and queue submission to proceed.
- [ ] Do not generate proxy media or launch FFmpeg as a preview fallback.
- [ ] Keep native preview playback as-is for v2; do not add a preview rotation gate or custom rotation renderer, while retaining authoritative preflight rotation policy.
- [ ] Keep preview state isolated from processing intent and expose no editing, filtering, trimming, frame-export, or concat-boundary controls.
- [ ] Keep FFmpeg, FFprobe, Real-ESRGAN, command builders, and processing services out of the preview presentation layer.
- [ ] Implement the separately approved controls, audio, error, and cleanup policies around the fixed playback backend.
- [ ] Keep custom target-height input without adding output-height presets.
- [ ] Provide inline, accessible field errors while preserving authoritative preflight.

### 4. Queue and job details

- [x] Implement concise, accessible job-row presentation.
- [x] Present the queue in a multi-column widget with textual `Status` first, `Job Name` second, and `Remove` actions for cancelled/failed rows.
- [x] Add the approved selected-job details surface.
- [x] Distinguish measured determinate progress from indeterminate work.
- [x] Make legal actions obvious for each job state and guard illegal transitions.
- [ ] Implement the approved session-history policy and omit retry support in v2.

### 5. Preflight, settings, and diagnostics

- [x] Improve issue grouping and inline presentation without adding severity controls or weakening acknowledgement gates.
- [ ] Improve external-tool validation status and resolved-tool feedback.
- [x] Add `Edit` → `Preferences` as a separate settings window for External Tools and remove the main-window `External Tools…` button.
- [x] Append completed-job messages to `Global Messages` and show session history in each message tab's read-only log widget.
- [ ] Ensure settings changes continue to affect only future drafts, never frozen queued requests.

### 6. Accessibility and macOS polish

- [ ] Preserve native Qt focus behavior and verify accessible names for approved icon controls.
- [ ] Verify the approved dark theme and increased-contrast behavior.
- [ ] Verify resizing, long paths, localization-length expansion, and high-DPI rendering.
- [ ] Perform native-dialog, dark-theme, and minimum-window checks on supported macOS hardware; no new VoiceOver feature is required in v2.

### 7. Verification and documentation

- [ ] Add headless GUI tests for every changed critical interaction.
- [ ] Test dark-theme rendering, Codex-created icon accessibility, file-manager drag-and-drop, and URL/remote-drop rejection.
- [ ] Test player load, decode, and unsupported-format failures as non-blocking preview states without proxy generation.
- [ ] Test native preview-as-is rotation behavior, custom target height without presets, Preferences-menu settings access, and removal of the main-window External Tools button.
- [x] Test queue Status/Job Name columns, completion messages in `Global Messages`, and session history/minimum five-line message widgets.
- [ ] Test that retry actions are absent for failed and cancelled jobs.
- [ ] Test width-driven resizing, exact aspect preservation, and native preview rotation behavior.
- [ ] Add regression tests for thread affinity, state transitions, and frozen job intent.
- [ ] Run `make check` and record the result below.
- [ ] Complete the manual macOS acceptance checklist.
- [ ] Update README, architecture, changelog, screenshots, and this phase status.

## Implementation handoff

The specification is ready for the GUI implementation agent. Use one vertical
slice at a time and keep the checklist and evidence synchronized:

1. Build the presentation shell: centralized identity/metrics, dark-theme
   tokens, the 1536 × 1024 window, left navigation rail, two view surfaces, and
   the persistent message-area splitter.
2. Build the Job Creation surface: filename-only drop/list editing, the
   Preferences menu path, and the selected-source preview boundary.
3. Build Queue Monitoring and messages: `Status`/`Job Name`/`Remove` columns,
   selected-job details, stage/whole-job progress, complete session message history, and terminal
   actions.
4. Add the fixed preview controls, native-player lifecycle, and remaining
   inline validation behavior.
5. Add focused headless tests for each slice before moving to the next one.

Do not update the architecture document with planned modules until they exist;
record each completed slice in Implementation evidence with its exact checks.

## Acceptance criteria

- A first-time user can configure tools, order clips, choose output intent, understand preflight, and queue a job without consulting CLI documentation.
- Selecting a source clip updates only that clip's preview; no queue item, merged intermediate, completed output, or simulated processed result is presented as the Phase 1 preview.
- The preview is playback-only and cannot create or mutate trim points, timeline edits, filters, frame exports, or concat boundaries.
- The preview provides previous-clip, play/pause, go-to-first-frame, go-to-last-frame, and next-clip controls, starts playback when a source clip is selected or navigated to, disables navigation at list boundaries, and provides no loop controls in v2.
- Preview controls are icon-only with the approved clip-navigation and playback glyphs; each exposes an accessible action name and tooltip and remains understandable without color.
- Preview starts muted on first launch, never autoplays audio, and remembers mute/volume only as non-safety preferences.
- Selection changes stop and asynchronously load the new local source without changing concat order; processing start pauses preview without automatic resume; window shutdown releases the player.
- URL and remote sources are rejected, and player failures appear inline without bypassing or replacing authoritative preflight errors.
- The main window opens at 1536 × 1024 pixels and cannot be resized below that minimum; the message widget height is user-resizable and the preview does not scroll.
- Source rows show filenames only, duplicate clips are accepted, and the generated output name appears in the selected job's `Job Messages` tab immediately after job start.
- Advanced options are available through `Edit` → `Preferences`, and the temporary v2 display identity is `Advanced AI Video Tools`.
- Playback uses PySide6 `QMediaPlayer` and `QVideoWidget`; the preview presentation layer contains no FFmpeg, FFprobe, Real-ESRGAN, or processing-command integration.
- The GUI visibly and accessibly identifies the widget as a convenience preview that is neither color-accurate nor authoritative for processing.
- Rotation, HDR, color, timing, stream inventory, compatibility, and processing decisions come only from FFprobe-backed preflight and the processing pipeline, never from player state or appearance.
- Native preview failure shows “Preview unavailable; preflight can still inspect this clip.” and does not remove the clip or prevent authoritative preflight or queue submission when the media otherwise satisfies processing policy.
- No FFmpeg proxy video or alternative preview media is created after native playback failure.
- The displayed video fills the available preview width, derives height from the exact display aspect ratio, is never cropped or stretched, and follows native preview rotation behavior.
- Every long-running discovery, probe, media, and inference operation remains off the GUI thread.
- Queue state and available actions are unambiguous for every legal job state. The queue has textual `Status`, `Job Name`, and `Remove` columns; stage and whole-job progress are both shown, and cancelled/failed rows can be removed without confirmation.
- Errors are concise in the interface and traceable to detailed local diagnostics.
- Required stream-drop acknowledgement cannot be bypassed or persisted.
- Settings edits cannot mutate requests already queued or running.
- Core workflows retain ordinary native Qt focus and accessibility behavior; no additional v2 shortcut, VoiceOver, or reduced-motion feature is required.
- The interface behaves correctly in the approved dark theme, increased-contrast mode, and at the supported minimum window size.
- The main window places the source-clip preview at the far right and provides a bottom integrated two-tab message widget with `Global Messages` and `Job Messages`.
- The main window provides a far-left two-icon navigation rail. Job Creation and Queue Monitoring controls are mutually exclusive by view, and switching views preserves each view's state without cancelling jobs or mutating job intent.
- The bottom integrated message widget remains visible, with its active tab and contents preserved, in both navigation views.
- The v1 `Video processing jobs` and `One job runs at a time • Default output height: {settings.target_height}p` labels are absent, with no replacement persistent heading introduced by this decision.
- The GUI uses the approved dark theme, and all Phase 1 icons are Codex-created app-owned artwork with accessible names.
- Users can drag local files from the operating-system file manager into the source list; files append in drop order, while URL/remote drops are rejected.
- Native preview playback is used as-is for v2, with no preview rotation gate or custom rotation renderer, and no output-height presets are exposed.
- `Edit` → `Preferences` opens a separate External Tools settings window, and the main-window `External Tools…` button is absent.
- Retry actions are absent in v2.
- The default preview pane uses a 3:4 width-to-height geometry calculated from the available height after the message widget; resizing preserves the source video's exact aspect ratio without crop or stretch while following native preview rotation behavior.
- Global and job messages are concise local-timestamped log lines delivered without blocking the GUI thread. Completed jobs append to `Global Messages`; each tab shows complete session-only history with at least five visible lines, no severity filtering or message actions are provided, and sensitive exact command lines remain out of the GUI.
- Existing v1 CLI and media-pipeline behavior remains unchanged unless separately approved.
- Automated checks pass and target-macOS manual verification is recorded.

## Out of scope

- Selecting the new project name or executing the full rename.
- Previewing completed outputs, queued-job media, merged intermediates, or simulated normalized/upscaled/final output.
- Trim points, timeline editing, filters, frame export, and concat-boundary editing in the preview.
- FFmpeg-generated preview proxies or Real-ESRGAN processing inside the preview component.
- Output-height preset controls.
- Retry actions or retry execution for failed/cancelled jobs.
- Persisted message history, message clear/copy/reveal actions, and severity filtering.
- New v2-specific keyboard shortcuts, VoiceOver announcement features, or reduced-motion behavior.
- Changing accepted color spaces, HDR policy, codecs, audio policy, or concat behavior.
- Concurrent processing jobs.
- Automatic downloads, telemetry, or update checks.
- Mid-job persistence or resume unless explicitly moved into this phase.
- Supporting operating systems or hardware outside the approved target.

## Implementation evidence

### Audit and interaction specification — completed

- Added [Phase 1 GUI Audit and Interaction Specification](1-enhance-gui-audit.md) covering the current hierarchy, focus-order risk, workflows, findings, state transitions, target wireframes, accessibility criteria, and minimum-window behavior.

### Presentation architecture specification — completed

- Added [Phase 1 Presentation Architecture](1-enhance-gui-presentation-architecture.md) covering typed presentation state, ownership, identity/UI semantics, Qt thread boundaries, shutdown, and view binding.

### Header simplification slice — completed

- Removed the `Video processing jobs` and `One job runs at a time • Default output height: {settings.target_height}p` labels from `src/ai_video_tools/gui/window.py`.
- Preserved the External Tools action and existing settings synchronization behavior.
- Updated `tests/test_gui.py` to assert both removed labels are absent.
- Validation run: `UV_CACHE_DIR=/private/tmp/ai-videol-tools-uv-cache uv run pytest tests/test_gui.py` — 4 passed.

Record subsequent completed slices here with links to the relevant modules/tests and the exact checks run. Do not mark the phase complete based only on scaffold or visual mockups.

### Integrated message widget slice — completed

- Added [the typed session message presenter](../../src/ai_video_tools/gui/messages.py) with local timestamps, complete in-memory global/job history, selection-driven tab activation, and no persistence or message actions.
- Connected immutable queue snapshots through `JobListModel.snapshot_changed`; global notices consume startup, settings, preflight, tool-validation, shutdown, and completion events while job notices consume queue, stage/progress, lifecycle, and cancellation events.
- Added a vertical splitter so message height is user-resizable while the existing 1536 × 1024 minimum window remains the layout lower bound.
- Added GUI regression coverage in `tests/test_gui.py`.
- Validation run: `UV_CACHE_DIR=/private/tmp/ai-videol-tools-uv-cache make check` — 182 passed; Black, Pylint, and pycodestyle passed.

### Navigation shell slice — completed

- Added the accessible two-control navigation rail and stacked Job Creation / Queue Monitoring surfaces in `src/ai_video_tools/gui/window.py`.
- Kept both surfaces session-owned and preserved the persistent message splitter outside the view stack.
- Added switching coverage in `tests/test_gui.py`.
- Validation run: `UV_CACHE_DIR=/private/tmp/ai-videol-tools-uv-cache make check` — 182 passed; Black, Pylint, and pycodestyle passed.

### Source preview boundary slice — completed

- Added the far-right `SourcePreviewPane` presentation boundary with width-driven 3:4 geometry, selected-source filename binding, and an explicit convenience-preview disclaimer.
- Kept the pane independent of FFmpeg, FFprobe, Real-ESRGAN, preflight, and processing intent; native playback and controls remain subsequent slices.
- Added headless coverage for source selection and aspect-ratio geometry in `tests/test_gui.py`.
- Validation run: `UV_CACHE_DIR=/private/tmp/ai-videol-tools-uv-cache make check` — 182 passed; Black, Pylint, and pycodestyle passed.

### Preview control surface slice — completed

- Added previous, play/pause, first-frame, last-frame, and next icon-only controls with accessible names, tooltips, and source-list boundary enablement.
- Navigation changes only the editor's current source selection and cannot reorder clips or affect frozen processing intent; native playback wiring remains the next preview slice.
- Added headless coverage for control enablement and previous/next selection behavior in `tests/test_gui.py`.
- Validation run: `UV_CACHE_DIR=/private/tmp/ai-videol-tools-uv-cache make check` — 182 passed; Black, Pylint, and pycodestyle passed.

### Native preview playback slice — completed

- Connected `SourcePreviewPane` to PySide6 `QMediaPlayer`, `QAudioOutput`, and `QVideoWidget`; local source selection stops and reloads the selected file, starts playback muted, and keeps processing independent.
- Added native `KeepAspectRatio` rendering, required inline preview failure text, and explicit player/output shutdown handling in `MainWindow.closeEvent`.
- Added headless coverage for muted audio and aspect-ratio configuration in `tests/test_gui.py`.
- Validation run: `UV_CACHE_DIR=/private/tmp/ai-videol-tools-uv-cache make check` — 182 passed; Black, Pylint, and pycodestyle passed.

### Local file drop slice — completed

- Added local video-file drag-and-drop to `JobEditor`; supported `.mov`, `.mp4`, `.mkv`, and `.m4v` files append in drop order and automatically select/autoplay the newest source through the existing preview binding.
- Non-video files, remote URLs, non-local URLs, and non-file paths are rejected without application-initiated network activity.
- Added headless coverage for local-file acceptance and remote-URL rejection in `tests/test_gui_submission.py`.
- Validation run: `UV_CACHE_DIR=/private/tmp/ai-videol-tools-uv-cache make check` — 183 passed; Black, Pylint, and pycodestyle passed.

### Filename-only source rows slice — completed

- `JobEditor` now renders only `Path.name` in the source list while retaining ordered full paths in typed editor state for preview binding and frozen request construction.
- Reordering, removal, queue clearing, and newly added-clip autoplay continue to operate on the retained full paths.
- Added regression coverage for filename-only rendering and full-path request preservation.
- Validation run: `UV_CACHE_DIR=/private/tmp/ai-videol-tools-uv-cache make check` — 183 passed; Black, Pylint, and pycodestyle passed.

### Welcome guidance slice — completed

- Removed the persistent `Create processing job` and concat-order instruction labels from the editor.
- Added a startup welcome instruction to the session-only `Global Messages` history describing the required add, output-directory, and preflight/queue flow.
- Added GUI regression coverage for the welcome message.
- Validation run: `UV_CACHE_DIR=/private/tmp/ai-videol-tools-uv-cache make check` — 183 passed; Black, Pylint, and pycodestyle passed.

### Preferences menu slice — completed

- Moved External Tools access to `Edit` → `Preferences` and removed the main-window `External Tools…` button.
- Preserved the existing asynchronous validation and persistence behavior for future drafts.
- Added headless coverage for the Preferences action and button removal in `tests/test_gui.py`.
- Validation run: `UV_CACHE_DIR=/private/tmp/ai-videol-tools-uv-cache make check` — 183 passed; Black, Pylint, and pycodestyle passed.

### Single-instance startup slice — completed

- Added a Qt `QLockFile` guard for the GUI process lifetime; a second launch reports that the application is already running and exits before creating the runtime/window.
- Added regression coverage for exclusive lock ownership in `tests/test_gui.py`.
- Validation run: `UV_CACHE_DIR=/private/tmp/ai-videol-tools-uv-cache make check` — 184 passed; Black, Pylint, and pycodestyle passed.

### Queue table slice — completed

- Replaced the queue list with a three-column table: textual `Status`, `Job Name`, and terminal-row `Remove` action.
- Preserved typed queue snapshots, row selection, progress/details, reorder, cancellation, and backend queue ownership; Remove only clears failed/cancelled rows from session presentation.
- Added regression coverage for the queue headers and table presentation in `tests/test_gui.py`.
- Validation run: `UV_CACHE_DIR=/private/tmp/ai-videol-tools-uv-cache make check` — 184 passed; Black, Pylint, and pycodestyle passed.

### Queue progress slice — completed

- Added a separate whole-job progress bar alongside the existing measured stage progress bar in Queue Monitoring.
- Whole-job progress is presentation-derived from the typed pipeline stage and measured stage fraction; backend progress emission and queue ownership are unchanged.
- Added GUI regression coverage for both progress surfaces.
- Validation run: `UV_CACHE_DIR=/private/tmp/ai-videol-tools-uv-cache make check` — 184 passed; Black, Pylint, and pycodestyle passed.

### Progress-state clarity slice — completed

- Stage progress now explicitly renders measured `Stage: completed/total` values or `Stage: … (measuring…)` for indeterminate work, with accessible names for both stage and whole-job controls.
- Added regression coverage for determinate stage formatting.
- Validation run: `UV_CACHE_DIR=/private/tmp/ai-videol-tools-uv-cache make check` — 184 passed; Black, Pylint, and pycodestyle passed.

### Selected-job details slice — completed

- Added a dedicated `Selected Job` details surface showing job name, status, stage, current message, and output path alongside the stage and whole-job progress controls.
- The details surface updates from immutable queue snapshots and shows `No job selected` when the queue table has no active selection.
- Added regression coverage for selected-job details in `tests/test_gui.py`.
- Validation run: `UV_CACHE_DIR=/private/tmp/ai-videol-tools-uv-cache make check` — 184 passed; Black, Pylint, and pycodestyle passed.

### Accessible queue rows slice — completed

- Added concise accessible row text and contextual cell tooltips for queue status, job name, and terminal Remove actions.
- Added regression coverage for queue accessibility text and tooltips in `tests/test_gui.py`.
- Validation run: `UV_CACHE_DIR=/private/tmp/ai-videol-tools-uv-cache make check` — 184 passed; Black, Pylint, and pycodestyle passed.

### Queue action clarity slice — completed

- Added an accessible `Available actions` summary that reflects the selected job state and the guarded Cancel, reorder, and Remove controls.
- Illegal actions remain disabled and backend transition guards are unchanged.
- Added regression coverage for running-job action presentation.

### Upscale message summaries slice — completed

- Converted typed `UPSCALE` progress events into concise job-message summaries with frame counts and integer percentages.
- Emit summaries at 10-percent intervals and at completion so the `Job Messages` history remains readable while a job runs; progress remains presentation-only on the GUI thread.
- Added regression coverage proving repeated progress events are throttled to `0%`, `10%`, `20%`, and `100%` summaries.
- The upscale service observes frame outputs on its worker-side monitor and emits typed progress events; no probing or polling work runs on the GUI thread.
- Validation run: `UV_CACHE_DIR=/private/tmp/ai-videol-tools-uv-cache make check` — 184 passed; Black, Pylint, and pycodestyle passed.

### Preflight issue grouping slice — completed

- Grouped typed preflight findings under non-interactive `Blocking issues` and `Warnings` headings while retaining native severity text and the dropped-stream acknowledgement gate.
- Added regression coverage for grouped blocking findings in `tests/test_gui_submission.py`.
- Validation run: `UV_CACHE_DIR=/private/tmp/ai-videol-tools-uv-cache make check` — 184 passed; Black, Pylint, and pycodestyle passed.

## Risks

- The later project rename may cause rework if application identity remains scattered through widgets, settings paths, logs, and packaging metadata.
- Visual changes can accidentally obscure media-safety warnings or make acknowledgement appear optional.
- Custom styling can reduce native accessibility, dark-mode correctness, and maintainability.
- A bottom message area can consume vertical space needed by the editor and preview; splitter proportions and spacing must be explicit before implementation.
- Mixing application-wide and job-scoped events can make message ownership ambiguous; typed event sources and a clear selected-job policy are required.
- Native preview rotation behavior may differ from the authoritative processing interpretation; this is accepted in v2 because preview playback is explicitly convenience-only.
- Offscreen Qt tests cannot prove VoiceOver behavior or complete native macOS appearance.
