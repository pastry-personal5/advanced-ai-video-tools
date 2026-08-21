# Phase 1: Enhance GUI

## Status

- Phase: 1
- State: Active planning
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

- Provide only these playback controls: go to the previous clip, play/pause, go to the beginning of the selected clip, go to the end of the selected clip, and go to the next clip.
- Selecting a clip in the ordered source list automatically starts playback for that clip.
- The previous-clip and next-clip controls move selection by one row in the ordered source list and automatically start playback for the newly selected clip. They do not reorder clips or mutate frozen job intent.
- Disable previous-clip at the first source clip and next-clip at the last source clip; navigation does not wrap around.
- “Go to the beginning” seeks to the start of the selected clip; “go to the end” seeks to its end without changing the ordered input list or job intent.
- Do not provide loop, repeat, A/B, trim, timeline-editing, filtering, frame-export, or concat-boundary controls in v2.
- Autoplay, seeking, and control state remain convenience-preview behavior and never become authoritative preflight or processing input.
- Render the five controls as icon-only buttons: previous clip uses a leading vertical bar with double left-pointing triangles; play/pause uses the conventional play triangle and pause bars; go-to-beginning uses a leading vertical bar with one left-pointing triangle; go-to-end uses one right-pointing triangle with a trailing vertical bar; next clip uses double right-pointing triangles with a trailing vertical bar. The double- versus single-triangle treatment distinguishes clip navigation from seeking within the selected clip.
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
- The preview pane's default geometry uses a 3:4 width-to-height ratio. Its default height tracks the available application content height after the bottom message area, allowing for the title/header, spacing, and window margins. The default width is therefore three quarters of that preview height.
- Use an initial and minimum main-window size of 1536 × 1536 pixels. The window must not shrink below that minimum.
- Make the integrated message widget's height user-resizable. Do not introduce preview scrolling; the minimum window size is the lower bound for the layout.
- The pane geometry is a layout default, not a video distortion rule. The currently selected source clip remains the only preview source, and the displayed video preserves the native player's display aspect ratio with no crop or stretch. Unused space inside the pane is acceptable when the source aspect ratio differs from the pane's 3:4 default.
- Add one integrated message widget along the bottom of the application window. It spans the main content width and remains visible while editing and monitoring jobs.
- Implement the message widget as a two-tab `QTabWidget`. The tabs are named `Global Messages` and `Job Messages`.
- `Global Messages` presents application-wide log-style notices such as startup, tool-configuration, settings, preflight-gate, and shutdown events. `Job Messages` presents log-style notices for the selected/current job, including stage changes, measured progress summaries, warnings, failures, cancellation, cleanup, and publication results.
- Message entries include a local timestamp without timezone information and concise text. Do not add severity levels or filtering controls in v2; state must remain understandable from the message text and native control state, not color alone. Exact sensitive subprocess command lines remain in the diagnostic log rather than being shown in the widget.
- Each tab contains a read-only log-tail widget showing exactly the latest five lines for that tab, with the newest line at the bottom. Five lines are sufficient; do not add an expansion control in v2.
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

### Source-list input and preview interpretation

- Allow users to drag local video files from the operating system file manager into the source-clip list. Dropped files are appended in drop order and remain subject to the existing local-file validation and duplicate policy.
- Retain the file-picker workflow alongside drag-and-drop. Reject URL and remote-media drops.
- Use native preview playback as-is in v2. Do not add a preview rotation gate, rotation correction, or custom no-rotation renderer. Authoritative FFprobe preflight and processing validation continue to govern rotation and all media policy.
- Do not add output-height presets in v2; retain the custom target-height control and its existing validation.

### Preferences menu

- Add an application menu item `Edit` → `Preferences`.
- Selecting `Preferences` opens a separate preferences window for External Tools configuration and validation.
- Remove the `External Tools…` button from the main window. External-tool settings remain available through the Preferences menu and continue to apply only to future drafts after successful validation and persistence.

### Queue and message presentation

- Do not implement retry support in v2. Failed and cancelled jobs retain their existing terminal behavior without a retry action.
- When a job reaches `COMPLETED`, append a concise completion message to the `Global Messages` stream in the integrated message widget.
- Each integrated-message tab contains a read-only log-tail widget showing the latest five message lines for that tab, with the newest line at the bottom. The tail is presentation-only and does not expose sensitive exact subprocess command lines by default.
- Present the job queue with a multi-column Qt model/view widget. The first column is `Status` and contains the textual job status; the second column is `Job Name`. Additional columns may be added only through a later approved decision.
- Add a third queue column containing a `Remove` action. The action is available for cancelled and failed jobs; the user controls when those terminal rows leave the session history.
- Show both stage progress and whole-job progress in Queue Monitoring.
- Do not add retry actions or retry execution in v2.

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

Do not begin visual implementation until the decisions affecting that slice are approved.

### Information architecture

- The Phase 1 information architecture is approved as a single-window layout with a far-left two-icon navigation rail, mutually exclusive Job Creation and Queue Monitoring views, a far-right source-preview region in the Job Creation view, and a persistent bottom message widget.
- Whether selected-job details appear inline, in an inspector, or in a separate dialog.
- Selected-job details are shown in the `Job Messages` tab of the integrated message widget.
- The minimum window size prevents further shrinking; no narrow-window scrolling behavior is required.

The Phase 1 layout direction above is approved for implementation. Remaining
layout detail is limited to the exact splitter proportions and spacing within
the fixed 1536 × 1536 minimum window.

### Visual direction

- The dark-theme visual direction is approved. Remaining decisions are limited to implementation details.
- Typography, spacing, density, and color-token policy.
- Generated-icon sizing and the final icon inventory beyond the approved controls.
- Temporary v1 identity treatment is approved as `Advanced AI Video Tools` until the project rename is decided.

### Job creation experience

- Accept duplicate clips without warning or rejection.
- Show filenames only; do not add inline metadata or thumbnails.
- Control presentation details not fixed above. Audio defaults, resource lifecycle, local-source policy, non-blocking player-failure behavior, native preview-as-is behavior, and drag-and-drop acceptance are already fixed.
- Show the generated output name immediately after job start in the selected job's `Job Messages` tab.
- Show advanced options in `Edit` → `Preferences`.

### Queue and progress experience

- Queue columns are `Status`, `Job Name`, and `Remove`; status is textual and appears to the left of the job name.
- Show both stage progress and whole-job progress.
- Show selected-job details in the `Job Messages` tab.
- Keep completed, cancelled, and failed jobs visible for the session; provide removal actions for cancelled and failed rows.
- Removing cancelled or failed jobs requires no confirmation.

### Integrated message behavior

- Keep messages for the running application session only.
- Show exactly five lines per tab; do not provide expansion, clear, copy, or
  diagnostics-reveal actions.
- Do not add severity levels or filtering controls in v2.
- Selecting a job activates `Job Messages`; show `No job is selected.` when
  there is no selected job.
- Use local timestamps without timezone information.

### Errors and warnings

- Present validation and player errors inline for now.
- Do not expose exact subprocess command lines or add copy/reveal actions in the
  GUI in v2.

### Accessibility and input

- No additional v2-specific keyboard shortcuts, VoiceOver announcements, or
  reduced-motion behavior are required; retain ordinary native Qt focus and
  accessibility behavior.
- Minimum contrast and non-color-only state indicators.

## Recommended Phase 1 defaults

These are recommendations, not approved design decisions:

- Use a native single-window layout with the approved far-left icon rail, view-specific central content, and the source preview at the far right of Job Creation.
- Follow the approved dark-theme direction without a custom theme engine.
- Use native Qt/macOS controls and a small, centralized set of spacing and semantic color tokens.
- Retain the file picker alongside approved drag-and-drop and preserve exact visible concat order.
- Show the approved queue table beginning with textual Status and Job Name, a Remove action for cancelled/failed rows, and selected-job details in the `Job Messages` tab.
- Use a right-side preview pane with an initial 3:4 frame; for example, 740 px of post-message-area height yields a 555 px preview width. Keep this as a geometry baseline until the supported minimum and initial window sizes are approved.
- Keep preflight acknowledgement modal because it is a safety gate; move ordinary field validation inline.
- Retain terminal jobs for the current session, with no-confirmation removal for cancelled and failed rows and no retry action.
- Do not display exact command lines by default; provide access through the clearly marked sensitive diagnostic log.
- Retain ordinary native Qt focus and accessibility behavior without adding v2-specific shortcuts or announcement features.

## Work breakdown

### 1. Audit and interaction specification

- [ ] Capture the current GUI hierarchy, workflows, focus order, and state transitions.
- [ ] Identify usability failures using concrete scenarios: first run, valid job, blocked preflight, acknowledgement, queued job, active cancellation, failure, and tool misconfiguration.
- [x] Approve the information architecture: a far-left two-icon rail, mutually exclusive Job Creation and Queue Monitoring views, and a persistent bottom message area.
- [x] Approve removal of the v1 `Video processing jobs` and `One job runs at a time • Default output height: {settings.target_height}p` labels.
- [x] Approve the dark-theme visual direction and Codex-created app-owned icon set.
- [ ] Define typography, spacing, density, and final icon inventory details.
- [ ] Define wireframes for empty, editing, validating, queued, running, failed, cancelled, and completed states.
- [ ] Establish measurable accessibility and window-resizing criteria.

### 2. Presentation architecture

- [ ] Separate durable presentation state from declarative widget construction where this improves testability.
- [ ] Centralize application identity strings and brand-neutral UI constants in preparation for the later rename.
- [ ] Define reusable spacing, status, and icon semantics without introducing an unnecessary theme framework.
- [ ] Preserve Qt ownership, signal/slot thread boundaries, and clean shutdown.
- [x] Define the main-window content layout with the editor/queue region, the far-right source-preview pane, and the bottom integrated message widget.
- [x] Define the preview-pane initial geometry as 3:4 width-to-height, derive its width from the post-message-area available height, keep the window at or above 1536 × 1536, make message height user-resizable, and avoid preview scrolling.
- [x] Define typed global-message and job-message events, session-only ownership, five-line per-tab tails, completion routing, and GUI-thread delivery without changing backend logging or queue semantics.
- [x] Define the two-view navigation state, icon semantics, state preservation, keyboard traversal, and visibility boundaries for creation versus queue controls.
- [ ] Define the five-line per-tab log-tail model and completion-event routing to `Global Messages`.

### 3. Job editor enhancement

- [ ] Implement the approved layout and field hierarchy.
- [ ] Remove the two v1 heading labels without changing job state, settings behavior, or External Tools configuration behavior.
- [ ] Add the integrated two-tab message widget at the bottom of the main window and connect it to global and selected-job event streams.
- [ ] Add the far-left two-icon navigation rail and switch between Job Creation and Queue Monitoring views without losing either view's state.
- [ ] Add the far-right source-preview pane and verify its default 3:4 geometry, available-height calculation, and responsive behavior.
- [ ] Add previous-clip, play/pause, go-to-beginning, go-to-end, and next-clip controls; start playback automatically when the selected source clip changes; disable navigation at list boundaries; provide no loop controls.
- [ ] Use the approved icon-only glyphs, accessible names, tooltips, enabled/disabled states, and keyboard focus behavior for all source-preview controls.
- [ ] Add drag-and-drop from the operating-system file manager, append accepted files in drop order, retain the picker, and reject URL/remote drops.
- [ ] Add approved clip summaries or metadata without probing on the GUI thread.
- [ ] Add a video preview whose source is exclusively the currently selected source clip.
- [ ] Implement playback with PySide6 `QMediaPlayer` and `QVideoWidget` behind a small, testable presentation boundary.
- [ ] Use `Qt.AspectRatioMode.KeepAspectRatio` and a width-driven container whose height follows the exact display aspect ratio without adding application-level rotation handling.
- [ ] Verify that preview resizing never crops, stretches, or substitutes a rounded aspect ratio.
- [ ] Label and describe the widget visibly and accessibly as a convenience preview that is not color-accurate or processing-authoritative.
- [ ] Ensure selection-driven preview changes cannot reorder clips, mutate frozen job intent, or influence authoritative preflight results.
- [ ] Start muted on first launch, persist only mute/volume preferences, stop and asynchronously reload on selection changes, and preserve concat order independently from preview selection.
- [ ] Pause preview at processing start, avoid automatic resume, and release the player during window shutdown.
- [ ] Reject URL/remote preview sources and accept only local files already in the editor.
- [ ] Ensure player metadata, rendering, duration, errors, and playback success cannot influence rotation, HDR, color, timing, stream, compatibility, or processing decisions.
- [ ] Map native player load, decode, and unsupported-format errors to the inline message “Preview unavailable; preflight can still inspect this clip.”
- [ ] Keep a preview-unavailable source clip in the ordered input list and allow authoritative preflight and queue submission to proceed.
- [ ] Do not generate proxy media or launch FFmpeg as a preview fallback.
- [ ] Keep native preview playback as-is for v2; do not add a preview rotation gate or custom rotation renderer, while retaining authoritative preflight rotation policy.
- [ ] Keep preview state isolated from processing intent and expose no editing, filtering, trimming, frame-export, or concat-boundary controls.
- [ ] Keep FFmpeg, FFprobe, Real-ESRGAN, command builders, and processing services out of the preview presentation layer.
- [ ] Implement the separately approved controls, audio, error, and cleanup policies around the fixed playback backend.
- [ ] Improve output-directory, height, and generated-name feedback.
- [ ] Keep custom target-height input without adding output-height presets.
- [ ] Provide inline, accessible field errors while preserving authoritative preflight.

### 4. Queue and job details

- [ ] Implement concise, accessible job-row presentation.
- [ ] Present the queue in a multi-column widget with textual `Status` first and `Job Name` second.
- [ ] Add the approved selected-job details surface.
- [ ] Distinguish measured determinate progress from indeterminate work.
- [ ] Make legal actions obvious for each job state and guard illegal transitions.
- [ ] Implement the approved session-history policy and omit retry support in v2.

### 5. Preflight, settings, and diagnostics

- [ ] Improve issue grouping and inline presentation without adding severity controls or weakening acknowledgement gates.
- [ ] Improve external-tool validation status and resolved-tool feedback.
- [ ] Add `Edit` → `Preferences` as a separate settings window for External Tools and remove the main-window `External Tools…` button.
- [ ] Append completed-job messages to `Global Messages` and show the latest five lines in each message tab's read-only log-tail widget.
- [ ] Add approved log-reveal and copy-diagnostics actions with sensitive-path warnings.
- [ ] Ensure settings changes continue to affect only future drafts, never frozen queued requests.

### 6. Accessibility and macOS polish

- [ ] Define and test complete keyboard navigation and shortcuts.
- [ ] Add accessible names, descriptions, and status announcements.
- [ ] Verify the approved dark theme and increased-contrast behavior.
- [ ] Verify resizing, long paths, localization-length expansion, and high-DPI rendering.
- [ ] Perform native-dialog, dark-theme, and minimum-window checks on supported macOS hardware; no new VoiceOver feature is required in v2.

### 7. Verification and documentation

- [ ] Add headless GUI tests for every changed critical interaction.
- [ ] Test dark-theme rendering, Codex-created icon accessibility, file-manager drag-and-drop, and URL/remote-drop rejection.
- [ ] Test player load, decode, and unsupported-format failures as non-blocking preview states without proxy generation.
- [ ] Test native preview-as-is rotation behavior, custom target height without presets, Preferences-menu settings access, and removal of the main-window External Tools button.
- [ ] Test queue Status/Job Name columns, completion messages in `Global Messages`, and five-line tails in both message tabs.
- [ ] Test that retry actions are absent for failed and cancelled jobs.
- [ ] Test width-driven resizing, exact aspect preservation, and native preview rotation behavior.
- [ ] Add regression tests for thread affinity, state transitions, and frozen job intent.
- [ ] Run `make check` and record the result below.
- [ ] Complete the manual macOS acceptance checklist.
- [ ] Update README, architecture, changelog, screenshots, and this phase status.

## Acceptance criteria

- A first-time user can configure tools, order clips, choose output intent, understand preflight, and queue a job without consulting CLI documentation.
- Selecting a source clip updates only that clip's preview; no queue item, merged intermediate, completed output, or simulated processed result is presented as the Phase 1 preview.
- The preview is playback-only and cannot create or mutate trim points, timeline edits, filters, frame exports, or concat boundaries.
- The preview provides previous-clip, play/pause, go-to-beginning, go-to-end, and next-clip controls, starts playback when a source clip is selected or navigated to, disables navigation at list boundaries, and provides no loop controls in v2.
- Preview controls are icon-only with the approved clip-navigation and playback glyphs; each exposes an accessible action name and tooltip and remains understandable without color.
- Preview starts muted on first launch, never autoplays audio, and remembers mute/volume only as non-safety preferences.
- Selection changes stop and asynchronously load the new local source without changing concat order; processing start pauses preview without automatic resume; window shutdown releases the player.
- URL and remote sources are rejected, and player failures appear inline without bypassing or replacing authoritative preflight errors.
- The main window opens at 1536 × 1536 pixels and cannot be resized below that minimum; the message widget height is user-resizable and the preview does not scroll.
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
- A completed job appends a message to `Global Messages`; each message tab shows a read-only tail of its latest five log lines.
- The queue widget has a textual `Status` column to the left of a `Job Name` column.
- The default preview pane uses a 3:4 width-to-height geometry calculated from the available height after the message widget; resizing preserves the source video's exact aspect ratio without crop or stretch while following native preview rotation behavior.
- Global and job messages are concise local-timestamped log lines delivered without blocking the GUI thread. Each tab shows exactly its latest five lines, messages are session-only, no severity filtering or message actions are provided, and sensitive exact command lines remain out of the GUI.
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

No Phase 1 implementation has started.

Record completed slices here with links to the relevant modules/tests and the exact checks run. Do not mark the phase complete based only on scaffold or visual mockups.

## Risks

- The later project rename may cause rework if application identity remains scattered through widgets, settings paths, logs, and packaging metadata.
- Visual changes can accidentally obscure media-safety warnings or make acknowledgement appear optional.
- Thumbnail or metadata enhancements can block the GUI if they bypass the existing worker boundary.
- Custom styling can reduce native accessibility, dark-mode correctness, and maintainability.
- A bottom message area can consume vertical space needed by the editor and preview; the minimum-size, splitter, and narrow-window policy must be explicit before implementation.
- Mixing application-wide and job-scoped events can make message ownership ambiguous; typed event sources and a clear selected-job policy are required.
- Native preview rotation behavior may differ from the authoritative processing interpretation; this is accepted in v2 because preview playback is explicitly convenience-only.
- Offscreen Qt tests cannot prove VoiceOver behavior or complete native macOS appearance.
