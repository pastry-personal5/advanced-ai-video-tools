# Phase 2: Rename Project

## Status

- Phase: 2
- State: Complete
- Established: 2026-08-22
- Predecessor: [Phase 1 — Enhance GUI](1-enhance-gui.md)
- Released baseline: v1.0.0
- Target: v2

Phase 2 is complete for the approved v2 scope. Signing/notarization and
supported-macOS upgrade validation are explicitly deferred to the human
release checklist.

## Objective

Replace the AI Video Tools identity with an approved new project identity across the application, package, command line, persistent storage, documentation, diagnostics, repository, and release artifacts without losing user settings, breaking existing automation without a stated policy, or weakening v1 media behavior.

A successful rename is a controlled identity migration, not a search-and-replace exercise.

## Entry criteria

Implementation may begin only after the owner approves:

- The new product display name and canonical spelling.
- The legal copyright-holder name.
- The Python distribution and import-package naming policy.
- The new CLI command and old-command compatibility period.
- The macOS bundle identifier and application-data migration policy.
- The output filename prefix policy.
- Repository and release-artifact names.
- The v2 version and release migration policy.

## Required design decisions

### Brand identity

- New product display name.
- Short name suitable for window titles, menus, dialogs, and disk-image presentation.
- ASCII slug for package names, commands, files, and URLs.
- Capitalization and punctuation rules.
- App icon, wordmark, and visual identity scope.
- Whether the old name may appear in migration or compatibility messages.

### Python identity

- Rename the distribution from `ai-video-tools` or retain it.
- Rename the import package from `advanced_ai_video_tools` or retain it as a stable internal namespace.
- Rename the console command from `ai-video-tools`.
- Decide whether the old command remains as a deprecated alias and for how long.
- Decide whether downstream Python imports are supported public API or internal implementation detail.

### macOS identity

- Reverse-DNS bundle identifier.
- Application display name, executable name, organization name, and organization domain.
- Signing identity, entitlements, notarization identity, and DMG name.
- Whether Launch Services should treat v2 as an upgrade to v1 or as a separate application.

### Persistent data migration

- Migrate or retain the existing `QStandardPaths` application-data directory.
- Migrate settings schema and validate tool overrides after migration.
- Migrate or retain logs and document their potentially sensitive exact command lines.
- Handle caches, failed job workspaces, and ownership markers without unsafe recursive movement or deletion.
- Define idempotence, rollback, interruption recovery, and behavior when old and new data both exist.
- Decide whether v1 and v2 may run side by side.

### User-visible compatibility

- Change or retain the `ai-video-` automatic output prefix.
- Preserve existing generated video files without renaming them.
- Decide whether project files, presets, or persisted queue records need legacy identity support if those features exist before Phase 2 starts.
- Define user-facing migration messages and release notes.

### Repository and legal identity

- Repository directory and remote repository name.
- Documentation links, badges, screenshots, examples, and support references.
- Copyright-holder identity in `LICENSE` and documentation.
- Third-party notices and attribution review.
- Source distribution, wheel, application bundle, DMG, and archive names.

## Recommended defaults

These recommendations remain unapproved until the owner selects the new identity and compatibility policy:

- Use one canonical display name and one lowercase ASCII slug derived from it.
- Rename the product, distribution, primary CLI command, bundle identity, release artifacts, and documentation consistently.
- Keep `advanced_ai_video_tools` as a deprecated compatibility import for one major release only if external Python imports are considered supported; otherwise perform one atomic internal-package rename with exhaustive import tests.
- Keep `ai-video-tools` as a warning-emitting CLI alias throughout v2 and remove it no earlier than v3.
- Create a new v2 application-data location without importing v1 settings; delete only the identified old v1 settings location after the new location is ready.
- Make the settings transition explicit and guarded so an interrupted or ambiguous path check never deletes unrelated data.
- Leave existing logs, caches, failed workspaces, and generated videos in place. Provide explicit discovery or migration where useful rather than moving large or sensitive data silently.
- Adopt a new output prefix for new v2 jobs only if the owner wants filenames to carry the new brand; never rename existing outputs.
- Centralize identity constants and keep media-policy constants independent from branding.
- Preserve a written old-to-new identity map for support, packaging, tests, and rollback.

## Identity inventory

The implementation must inventory and classify every occurrence before editing it.

| Surface | Current identity | Required action |
| --- | --- | --- |
| Product display name | AI Video Tools | Replace with approved display name |
| Python distribution | `ai-video-tools` | Decide rename and compatibility policy |
| Python import package | `advanced_ai_video_tools` | Decide rename or compatibility namespace |
| CLI command | `ai-video-tools` | Replace and optionally retain deprecated alias |
| GUI application name | AI Video Tools | Replace through centralized identity configuration |
| Qt organization name | AI Video Tools | Replace and account for persistent-path migration |
| Settings/log/cache locations | Derived from Qt identity | Migrate or retain according to approved policy |
| Automatic output prefix | `ai-video-` | Decide whether new jobs use a new prefix |
| Log filename | `ai-video-tools.log` | Replace or retain with migration rationale |
| Workspace ownership markers | Existing internal identity | Preserve safety and recognize only explicitly supported legacy markers |
| Package artifacts | `advanced_ai_video_tools-*` | Rename consistently with distribution policy |
| Repository and docs | AI Video Tools paths/text | Replace links, examples, screenshots, and prose |
| Proprietary license holder | AI Video Tools Project Owner | Replace with approved legal owner identity |

This table is a starting inventory, not proof that every occurrence has been found.

## Work breakdown

### 1. Approve identity and compatibility specification

- [x] Record the approved display name: `Advanced AI Video Tools`.
- [x] Record the approved legal owner/copyright holder/developer/contact/maintainer: `Pastry Personal 5`.
- [x] Record the approved Python distribution name: `advanced-ai-video-tools`.
- [x] Record the approved Python import package name: `advanced_ai_video_tools`.
- [x] Record the approved CLI command: `advanced-ai-video-tools`.
- [x] Record the compatibility policy: retain the old `ai-video-tools` command as a deprecated alias through v2; remove it no earlier than v3 unless the owner revises this policy.
- [x] Record the storage policy: create a new v2 storage location and delete the old v1 settings during the v2 transition; no settings migration or rollback source is retained.
- [x] Record the runtime policy: support only v2 after the transition; v1 and v2 are not supported side by side.
- [x] Record the output filename policy: retain the existing `ai-` prefix for new output files.
- [x] Record the canonical repository: `https://github.com/pastry-personal5/advanced-ai-video-tools`.
- [x] Approve the macOS bundle identifier: `com.pastrypersonal5.advancedaivideotools`; treat it as permanent after the first v2 release.
- [x] Approve the v2 distribution channel as outside the Mac App Store, using Developer ID distribution via `.dmg`; signing/notarization execution remains a manual release action.
- [x] Record compatibility duration and removal criteria for every retained old identity.
- [x] Define upgrade, side-by-side, rollback, and interrupted-migration behavior.

### 2. Build a complete identity map

- [x] Search source, tests, documentation, packaging, lockfiles, scripts, settings, logs, caches, ownership markers, and release assets.
- [x] Classify occurrences as product identity, stable compatibility surface, historical record, third-party text, or incidental wording.
- [x] Protect historical changelog entries from misleading rewrites while adding rename context.
- [x] Add identity-map consumer tests; historical and explicitly approved compatibility occurrences remain allowlisted.

### 3. Centralize identity configuration

- [x] Introduce one typed source for display, organization, command, package, bundle, storage, log, workspace-marker, and output-prefix identities where runtime sharing is appropriate.
- [x] Remove scattered GUI, diagnostics, workspace, and generated-output literals without coupling media behavior to branding.
- [x] Keep build-time metadata explicit where packaging tools require static values.
- [x] Test identity consumers independently.

### 4. Implement persistent-data migration

- [x] Detect v1 data without following unsafe symbolic links.
- [x] Resolve old/new coexistence deterministically.
- [x] Apply the approved fresh-storage policy: do not import v1 settings and remove only the identified settings files.
- [x] Do not retain a rollback copy because the approved policy explicitly rejects settings migration and rollback; preserve all other v1 data.
- [x] Handle unsupported settings schemas explicitly.
- [x] Avoid silently moving or deleting logs, caches, generated outputs, or failed workspaces.
- [x] Make migration idempotent and test publication safety and unrelated-file preservation.

### 5. Rename runtime and packaging surfaces

- [x] Update GUI identity, CLI identity, package metadata, entry points, module paths, bundle metadata, diagnostics, artifacts, and approved output prefix.
- [x] Implement only the approved compatibility aliases or shims.
- [x] Emit concise deprecation messages without polluting machine-readable output.
- [x] Refresh lockfiles and ensure source metadata contains the correct license and metadata. Bundle/artifact inspection remains release-owner verification.

### 6. Update documentation and release assets

- [x] Update README, architecture, contribution guidance, v2 plans, examples, screenshots, and support instructions.
- [x] Update LICENSE with the approved legal copyright holder.
- [x] Add [the v1-to-v2 migration guide](rename-migration.md) containing old-to-new command and path mappings.
- [x] Record the rename under `Unreleased` without rewriting the historical v1 release inaccurately.
- [x] Verify the canonical repository link and local source/wheel artifact names and metadata.

### 7. Verify upgrade and compatibility behavior

- [x] Run unit tests for identity mapping, migration, idempotence, conflicts, and aliases; rollback is intentionally not supported by the approved policy.
- [x] Run CLI tests using new and approved legacy command names.
- [x] Run GUI startup tests with clean, v1-only, v2-only, and conflicting settings states.
- [x] Defer v1-to-v2 upgrade verification on supported macOS hardware to the human release checklist.
- [x] Defer signing, notarization, and bundle-upgrade verification to the human release checklist; application-data behavior is covered by automated tests.
- [x] Run `make check` and build the approved Python v2 artifacts; application-bundle artifacts remain release-owner work.

## Acceptance criteria

- The approved new name is consistent across every current user-facing and release surface.
- The old identity appears only in historical records, migration code, compatibility aliases, and documentation where explicitly approved.
- A new v2 settings location is created without importing v1 settings, and only the identified old v1 settings location is deleted.
- A failed or interrupted transition cannot delete unrelated data or leave a partially written v2 settings document.
- Existing videos, logs, caches, and retained failed workspaces are not silently renamed or deleted.
- New and approved legacy CLI commands behave according to the compatibility specification.
- Machine-readable CLI output remains machine-readable when a legacy alias emits deprecation guidance.
- Package, wheel, application bundle, DMG, version output, license, and repository documentation report the intended new identity.
- GUI startup, queue behavior, media processing, publication safety, and v1 media invariants remain unchanged by branding work.
- Automated quality gates pass; target-macOS upgrade verification is explicitly deferred to the human release checklist.

## Out of scope

- Choosing a new name without owner approval.
- Changing media processing, accepted color profiles, output quality, audio behavior, or queue concurrency merely because the product name changes.
- Deleting v1 user data automatically.
- Rewriting third-party copyrights or licenses.
- Maintaining indefinite compatibility without a documented removal release.

## Implementation evidence

- Renamed the source package to `src/advanced_ai_video_tools`, updated all imports and tests, and changed the distribution metadata to `advanced-ai-video-tools` version 2.0.0.
- Added `src/advanced_ai_video_tools/identity.py` as the typed runtime identity map; GUI compatibility exports, diagnostics, generated output naming, and workspace ownership markers now consume it.
- Added the `advanced-ai-video-tools` primary entry point and retained `ai-video-tools` as a stderr-only deprecation alias through v2.
- Centralized the display, organization, CLI, bundle, and compatibility identities; added `packaging/macos/Info.plist` with `CFBundleName`, `CFBundleDisplayName`, and bundle identifier `com.pastrypersonal5.advancedaivideotools`.
- Created a fresh v2 Qt storage identity and guarded removal of only the known v1 settings files; added tests for unrelated-file preservation and symlink refusal.
- Kept the `ai-` automatic output prefix and left existing outputs, logs, caches, and failed workspaces untouched.
- Updated README, architecture, contribution guidance, changelog, scripts, lockfile, and migration documentation.
- Verification: `make check` — 221 passed; Black check — 76 unchanged; Pylint — 10.00/10; pycodestyle and `git diff --check` passed. `uv build` produced the v2 wheel and source distribution, and their metadata plus the macOS plist were inspected.

Application bundling, signing, notarization, and target-macOS upgrade
verification remain external release actions. The approved channel is outside
the Mac App Store using Developer ID distribution via `.dmg`; execution of
those release steps and target-macOS upgrade verification are deferred for v2.

## Risks

- Changing Qt organization/application names changes standard settings, log, and cache paths and can make v1 data appear lost without migration.
- Renaming both the import package and distribution can break entry points, internal imports, editable installs, test discovery, and downstream automation.
- A CLI alias can corrupt JSON output if deprecation text is written to stdout.
- Moving caches or failed workspaces can violate ownership checks and destructive-action safeguards.
- Repository hosting changes can leave broken documentation, release, and support links; the canonical URL is now recorded.
- Scattered identity literals will create inconsistent branding unless inventory and centralization happen before replacement.
