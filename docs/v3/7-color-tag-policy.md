# V3 Phase 7 — Color Tag Policy and Frame Inventory Robustness

## Status

Complete. Phase 7 was implemented before Phase 6 by explicit authorization.

## Implemented behavior

- `JobRequest` and `JobPlan` freeze `allow_mixed_color_tags`, defaulting to
  `False`. The CLI exposes `--allow-mixed-color-tags`; GUI jobs copy the saved
  **Input and Output → Color Policy → Allow mixed color tags** preference when
  submitted.
- Strict preflight rejects a mixture of missing and declared matrix, transfer,
  or primaries tags. It cannot issue a runnable plan which the command builder
  later rejects.
- With opt-in enabled, untagged clips are accepted only when all declared
  supported SDR matrix, transfer, and primaries tags agree. That consensus,
  with the normal BT.709 defaults only when no value is declared, is frozen for
  normalization, merged media, and final output. Any missing color tag forces
  normalization because stream copy cannot assign the frozen profile. Explicit
  conflicts, HDR, wide gamut, unsupported tags, and cross-profile conversion
  remain rejected.
- Frame extraction treats the contiguous, structurally verified RGB PNG
  sequence as the decoded timeline. Metadata-derived count remains an estimate
  for progress and disk planning. A difference is logged, while exact observed
  inventory is passed unchanged through upscaling and final encoding.

## Verification

`make check` passed on 2026-10-14: Black, Pylint, pycodestyle, and 309 tests.
The FFmpeg integration suite generated an untagged `f0` plus tagged `f1`/`f2`
fixtures at 124 frames each, verified opt-in BT.709 normalization, and extracted
the expected 372-frame timeline on the supported macOS environment.
