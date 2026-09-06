# V2 Phase 2 — Rename Project

## Status

- State: Complete
- Completed: 2026-08-26
- Predecessor: Phase 1

## Outcome

- Product/organization: `Advanced AI Video Tools` / `Pastry Personal 5`.
- Distribution/import/primary CLI: `advanced-ai-video-tools`,
  `advanced_ai_video_tools`, and `advanced-ai-video-tools`.
- Retained `ai-video-tools` as a warning compatibility alias through v2 and
  retained the `ai-` generated-output prefix.
- Centralized runtime/packaging identity and adopted bundle ID
  `com.pastrypersonal5.advancedaivideotools`.
- Moved application data to the new Qt identity and removed only guarded legacy
  settings files; symlinks and unrelated files remain untouched.
- Updated packaging, metadata, docs, legal ownership, imports, tests, and entry
  points together. See [the migration reference](rename-migration.md).

## Evidence and limitations

- `make check`: 221 passed; Black, Pylint, pycodestyle, and `git diff --check`
  passed. Wheel/sdist metadata and macOS plist were inspected.
- Supported-hardware upgrade validation and production signing/notarization were
  deferred to release work; external tools and artifacts were never bundled.
