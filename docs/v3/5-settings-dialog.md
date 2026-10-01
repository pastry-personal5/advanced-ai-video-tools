# V3 Phase 5 — Unified Settings Dialog

## Status

- State: Complete
- Predecessor: [Phase 4 — Modularity Refactoring](4-refactoring.md) (complete)
- Successor: Phase 6 (unassigned)
- Approved: 2026-09-06
- Completed: 2026-09-06

## Objective

Replace the nested standalone preferences dialogs with one searchable Settings
dialog while preserving typed settings, asynchronous tool validation, atomic
persistence, GUI-thread safety, and application-wide settings propagation.

## Approved experience

- Replace **Edit → Preferences** with **Preferences → Settings**. The Settings
  action uses `QAction.MenuRole.NoRole` so Qt does not relocate it on macOS.
  It is also available with the standard macOS **Command-,** shortcut.
- Open one modal, resizable dialog with a full-width search field, a tall left
  navigation tree, a right page stack, shared status, and **Cancel**/**OK**.
- Use an invisible tree root with **Editor → File** for Automatic File Deletion
  Rules and **Tools → External Tools** for tool and model paths.
- Remember dialog size, sidebar width, and selected leaf for the current GUI
  session only. Default the first selection to **Editor → File**.
- Filter pages case-insensitively by path, headings, labels, help text, and
  keywords. Preserve the previous page when search clears and show an explicit
  empty result when no page matches.

## Dimensions

- Default client size: `1080 × 720` logical pixels; minimum: `960 × 600`.
- Center over the parent and clamp session-restored size to the active display
  with 24 px clearance where the supported display can accommodate it.
- Use 24 px outer margins, 16 px major gaps, 8 px related-control gaps, 32 px
  search/control height, and an 8 px splitter handle.
- Start the non-collapsible sidebar at 272 px and constrain it to 240–360 px.
  At minimum size, retain about 640 px for the settings-page viewport.
- Keep search, tree, status, and commit controls fixed. Scroll only the active
  right page vertically; never show a horizontal page scrollbar.
- Use 32 px tree rows, 16 px indentation, right elision, and complete tooltip
  and accessibility text. Limit shared status to two lines/72 px so errors do
  not displace the main content.

## Draft, validation, and persistence

- Both pages edit one dialog-local `ApplicationSettings` draft. Navigation and
  search never save or discard it.
- **OK** validates the complete draft and performs one atomic save. A no-op OK
  closes without writing or emitting a settings update. **Cancel** discards
  immediately; title-bar close and Escape confirm before discarding a dirty
  draft.
- Cheap structural validation remains beside the affected control. Pages with
  expensive validation expose **Validate**, and OK automatically validates any
  changed or stale page that still requires it.
- Show accessible `Saved`, `Needs validation`, `Validating`, `Valid`, and
  `Invalid` states on leaf pages; category rows aggregate blocking descendants.
- Validate expensive pages sequentially and key results to the exact immutable
  page draft. An edit invalidates the prior result; stale results are ignored.
- Manual validation locks only its page. OK-initiated validation freezes all
  editors to protect the commit snapshot while leaving Cancel available.
- Failures remain inline, retain the draft, reveal and focus the first blocking
  control, and explain what failed, what stayed safe, and how to recover.
- Closing during validation abandons the draft immediately. The runtime-owned,
  bounded worker may finish in the background, but its result cannot persist or
  update a later dialog. A newly opened dialog loads persisted settings, keeps
  External Tools read-only until the old worker finishes, and leaves unrelated
  settings editable and saveable.

## Implementation boundaries

- Rename `gui.preferences` to `gui.settings_dialog` and rename the validator to
  `ExternalToolsValidator`; no compatibility shim is needed for internal GUI
  imports.
- `SettingsDialog` owns search, navigation, validation coordination, the shared
  draft, and the `settings_saved(ApplicationSettings)` signal.
- `FileSettingsPage` embeds ordered deletion-rule editing;
  `ExternalToolsPage` embeds coherent tool overrides; `DeletionRuleDialog`
  remains the editor for one rule.
- Keep `ApplicationSettings`, `SettingsStore`, YAML schema version 2, the CLI,
  queued-job freezing, media behavior, and subprocess/network contracts
  unchanged.

## Acceptance

- Cover menu role/path, tree hierarchy, search, dimensions, splitter bounds,
  page-only scrolling, session restoration, focus, accessibility, and long
  content at minimum/default/enlarged sizes.
- Cover shared-draft cancellation, no-op OK, combined atomic save, validation
  success/failure/retry, stale and abandoned results, storage failure, and
  saving File settings while an older tool validation finishes.
- Run focused GUI/settings tests, `git diff --check`, `make check`, and the
  supported native GUI capture check.

## Evidence

- Focused Settings/window suite: 64 passed.
- `make check`: Black, Pylint 10/10, pycodestyle, and 298 tests passed; four
  opt-in native checks skipped as designed.
- `make gui-capture-test`: three Cocoa capture checks passed, including the
  unified Settings dialog at its approved default size. Post-review reruns
  reached every layout assertion, but macOS then rejected all three screenshot
  rectangles, including the two unchanged main-window captures.
- All 38 Markdown documents were reviewed; local links resolve.

## Deferred

- Persistent dialog geometry or navigation state.
- Additional settings pages, control-level search results, Apply/per-page Save,
  parallel validation, and cancellable tool-discovery subprocesses.
