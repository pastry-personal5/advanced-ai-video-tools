# V3 Phase 6 — Customizable Upscaling Pipelines

## Status

- State: Planned; implementation has not started
- Predecessor: [Phase 5 — Unified Settings Dialog](5-settings-dialog.md) (complete)
- Design recorded: 2026-10-11
- Implementation approval and evidence: Pending

## Objective

Let users choose a processing pipeline, its relevant upscaler, and a desired
output height in the unified Settings dialog. Expose the same processing intent
per GUI job and through the CLI, freeze it when a job is queued, and execute it
through the shared typed service. Preserve the current Auto behavior as the
default for existing users.

## Pipelines

| Choice | Operations after clip compatibility checks | Desired height |
| --- | --- | --- |
| Auto | Current target-driven Real-ESRGAN scale selection, then final resize | Used |
| Concat only | Stream-copy compatible `.mp4` and `.mov` clips into the first clip's MP4 or MOV container | Ignored |
| Native upscale | One selected native 2× or 3× Spandrel pass, or one 4× Real-ESRGAN pass | Ignored |
| 4× then resize | Real-ESRGAN 4×, then resize | Used |
| 2× → 3× → resize | Spandrel 2×, Spandrel 3×, then resize | Used |

- Concat always precedes AI. Concat only takes a separate terminal branch after
  direct stream-copy concat and verification. It skips normalization, frame
  extraction, AI, and final frame encoding; it never re-encodes source video or
  audio. Incompatible inputs fail with the exact normalization reason instead
  of silently entering the normal path.
- Native upscale runs even when the source is already tall. Its requested AI
  scale is the model's reported native scale, not a resize instruction: 2× and
  3× select the corresponding Spandrel model, while 4× selects the existing
  `realesrgan-x4plus` path. Final encoding uses the existing square-pixel H.264
  `yuv420p` profile. It resolves display width with the current exact
  aspect-ratio calculation rounded to the nearest even integer; preflight
  discloses that resolved width and height before queueing.
- In either explicit resize pipeline, skip AI if source height already meets or
  exceeds desired height. Otherwise run every selected AI pass in order, then
  resize to the desired even height with the existing aspect-preserving policy.
  Reject a desired height above the selected pipeline's native 4× or 6× result
  rather than conventionally enlarging beyond that result. Auto keeps its
  existing scale selection, skip rule, and over-4× warning/resize behavior.
- The desired-height control is disabled for concat only and native upscale;
  its saved value remains available for the other pipelines. Ignored height
  never affects request validation, sizing, tool selection, disk estimates, or
  execution for those two choices. An omitted pipeline choice keeps the
  existing Auto behavior.

The plan must expose the resolved output dimensions, ordered passes, any skip,
and predicted workspace use in both frontends before submission. Only the
explicit two-pass choice may invoke AI twice. The final output for every AI
path remains MP4; concat only may also publish MOV.

## Settings and interfaces

- Add **Processing → Upscaling** to the searchable Settings dialog for default
  pipeline, native scale, desired height, and one explicit user-selected
  `.safetensors` model file for each of 2× and 3×. Add the user-installed
  Spandrel runner executable to **Tools → External Tools**. Keep the existing
  Real-ESRGAN executable and `realesrgan-x4plus` model for 4× and Auto. Device,
  precision, frame-size gating, and retry policy remain internal.
- Version the settings schema. Load existing documents as Auto without
  rewriting them, and migrate on the next successful save without changing the
  saved target height. Fresh settings use Auto and 2160 px. Reject unsupported
  newer schemas as before. Settings saves remain one atomic draft. Validate
  changed runner/model choices off the GUI thread using a versioned runner
  inspection protocol. The protocol response must include its protocol version,
  runner version, resolved model path, file identity, model architecture,
  purpose, input/output channel counts, native scale, size requirements, and
  the runner's conservative maximum input-pixel count. Require an
  image-to-image descriptor with RGB input and output, a super-resolution
  purpose, and the expected native 2× or 3× scale; report unsupported
  architectures, unsupported `.pth`/`.pt` inputs, or model-load failures
  without falling back to another model. Preflight rejects a pass whose exact
  input dimensions fail the descriptor's size requirements or exceed its
  maximum input-pixel count; Phase 6 does not silently pad, crop, or tile a
  frame. Recheck the exact selected prerequisites during job preflight.
  Unconfigured 2×/3× models do not block unrelated jobs.
- Show pipeline, native scale when applicable, and desired height when used in
  Job Creation. The 2× and 3× file selectors live in Settings; a job selects
  the pipeline and, for native upscale, its scale. Queueing a job saves these
  intent choices as defaults for later GUI jobs without changing model files.
  Already queued jobs retain their frozen request, including the tool and model
  paths and inspection records copied from Settings at submission. Authoritative
  preflight repeats after dequeue and rejects a missing file or a changed
  recorded file identity before processing. The runner resolves the selected
  path and checks that same identity immediately before loading it; this is a
  change-detection guard, not a claim to eliminate adversarial filesystem
  races. Freezing a path never freezes its bytes.
- Add typed pipeline and scale choices to `JobRequest` and `JobPlan`, with the
  ordered pass plan and resolved tool/model paths frozen at preflight. Extend
  CLI preflight and process with `--pipeline` values `auto`, `concat`, `native`,
  `4x-resize`, and `2x-3x-resize`; `--scale` is required only for `native` and
  accepts 2, 3, or 4. Add `--spandrel-runner`, `--model-2x`, and `--model-3x`.
  Reject `--scale` outside `native`, reject non-2/3/4 values, and reject
  Spandrel flags unless the selected pipeline can execute a Spandrel pass.
  Existing `--height` remains accepted but is ignored for `concat` and `native`.
  The CLI remains independent of saved GUI Settings: omitted new flags retain
  Auto and the existing 2160 px default. Keep the existing `--model` argument
  compatible with its current `realesrgan-x4plus` value; do not overload it
  with a Spandrel checkpoint path. Extend CLI JSON/text preflight and result
  output with pipeline, passes, sizing/skip decisions, and relevant paths while
  retaining existing fields for Auto.

## Runner and execution

- Create a new isolated, user-installed Spandrel batch runner with a documented
  `inspect` command and directory-to-directory PNG `run` command. Keep the
  experimental `tools/spandrel-runner` prototype separate. Do not add Spandrel
  or PyTorch to the main application's runtime dependencies or download them
  from the application. Define and test a versioned JSON inspection result,
  line-delimited progress records, stable exit/error codes, absolute
  input/output paths, and compatibility checks before integrating the runner
  with the application. Inspection must not create processing output. Both
  commands accept only `.safetensors` checkpoints and use the same restricted
  loader policy; they never deserialize Python-pickle `.pth` or `.pt` files.
- The runner requires Apple Silicon MPS for supported jobs; lack of MPS is an
  actionable failure. It must check `torch.backends.mps.is_available()` before
  loading a model and launch with `PYTORCH_ENABLE_MPS_FALLBACK=0`, so unsupported
  MPS operations fail rather than running on CPU. It never silently switches
  device or precision. The runner checks the model descriptor and native scale,
  keeps loading and inference outside the GUI thread, emits progress only after
  a complete frame has been atomically written, and writes only into its
  assigned job-owned output directory. It uses direct single-frame inference,
  not tiling. Each supported runner/model release publishes a conservative
  maximum input-pixel count, verified on the supported host; preflight applies
  it to every pass input. An allocation failure within that published limit is
  an actionable failure, never a CPU fallback or unbounded retry.
- Discover only the tools needed by the resolved path: FFmpeg and FFprobe for
  concat only; add Real-ESRGAN and its model for an actual Real-ESRGAN pass;
  add the Spandrel runner and selected model file for each planned Spandrel
  pass. A resize-only skip requires no AI backend. Keep the current Auto path's
  existing Real-ESRGAN validation behavior unless separately approved.
- The shared pipeline executes the frozen ordered passes. Freeze the selected
  pipeline, pass order, backend, native scale, resolved paths, inspection
  records, exact input/output dimensions, and file identities in the runnable
  plan. Verify exact frame names, count, structural RGB readability, and
  expected coded dimensions after every pass before the next pass or final
  encode. Give each pass a separate owned output directory; a retry may reset
  only that directory.
  Retain the merged audio source through all passes. Account for the source
  extraction set, both intermediate sets, merged media, final partial, and a
  20% margin in preflight. Check free space separately at the workspace and
  destination filesystems when they differ. Preserve process-group cancellation,
  bounded output, shell-free argument arrays, bounded retry behavior where
  applicable, workspace retention on failure, cleanup on cancellation, and
  atomic output publication. Final MP4 encoding retains the existing color,
  frame-rate, audio, and verification policy.
- Keep one public `UPSCALE` stage but report pass index, model scale, completed
  frames, and total frames with a monotonic aggregate across all passes. The
  Queue preview's Original/Upscaled pair must refer to the same source frame
  and the final selected pass; it may remain empty until that pass produces a
  matched frame. A skipped AI path reports the skip without fabricating work.
- For concat only, accept `.mp4` and `.mov` inputs only when FFprobe reports a
  QuickTime/ISO base-media container; extend the typed probe with FFprobe's
  normalized `format_name` values rather than trusting a filename alone. The
  first clip's lowercase `.mp4` or `.mov` suffix selects the explicit MP4 or
  MOV output muxer. Require the existing strict stream-copy compatibility result
  and the current SDR, rotation, timing, and
  stream-drop safety gates. Reject any reason that would require normalization,
  padding, trimming, or frame-rate conversion. Reject video and audio codecs
  the selected output container cannot mux with stream copy; validate the
  actual muxer result as well as the preflight allowlist. Generated output uses
  the first clip's lowercase suffix; an explicit path must use the same suffix.
  Generalize automatic-name parsing and generation to bind the frozen allowed
  suffix (`.mp4` or `.mov`) to the generated identity, while keeping AI-path
  names MP4-only. Freeze the suffix with the generated identity when the GUI
  job is created, then recheck that the first clip has not changed at
  authoritative preflight.
  Preserve existing per-job acknowledgement before dropping secondary streams or
  chapters. Build one direct concat-demuxer `-c copy` command with explicit
  stream maps and no normalization, extraction, video/audio filter, or encoder.
  Verify the stream-copied MP4 or MOV partial, including selected codec IDs,
  coded dimensions, sample aspect ratio, frame timing, SDR color and range,
  expected audio codec/presence, and plausible duration and A/V alignment,
  before publishing it atomically. Extend destination naming, reservation,
  same-filesystem partial allocation, and publication ownership checks to MOV
  without loosening existing MP4 rules. Existing output survives any failure.

## Acceptance and evidence

- Cover schema migration and atomic Settings save; GUI and CLI choices; GUI
  default updates and frozen queued jobs; ignored-height behavior; every
  sizing/skip/rejection branch; model and MPS failures; and MP4/MOV destination
  and codec checks. Exercise unsupported runner protocol, `.pth`/`.pt` and
  unsafe-format rejection, model descriptor, channel/scale, size-requirement,
  maximum-pixel, file-change, and unavailable-backend failures.
- Use fakes and tiny FFmpeg fixtures to cover pass order, exact frame
  inventories, monotonic measured progress, cancellation, cleanup, old-output
  preservation on failure, and concat-only publication without video or audio
  encoding. Include first-clip MOV output, a rejected MP4-incompatible codec,
  audio/timing incompatibility, and queued Settings changes. Keep default
  checks independent of GPU, downloads, and model files.
- Run focused checks, `git diff --check`, and `make check`. Run supported-macOS
  native acceptance with the supplied 2× and 3× model files, including a
  two-pass job, runner MPS/format failure cases, cancellation, and both MP4/MOV
  concat-only output before recording Phase 6 as complete. Update the
  architecture contract, CLI/GUI guides, roadmap, and phase evidence only with
  implemented and verified behavior.

## Resolved design decisions

1. **Native dimensions:** retain the existing aspect-preserving nearest-even
   output-width rule. The resolved dimensions are part of preflight in both
   frontends, so a user can review the one-pixel rounding consequence before
   submission.
2. **Spandrel memory policy:** Phase 6 supports direct single-frame inference
   only. A runner/model release must declare a conservative maximum input-pixel
   count that native acceptance validates; preflight rejects every pass above
   that limit. Tiled inference, overlap policy, and generalized memory retry
   are deferred rather than guessed.
3. **Checkpoint trust:** support `.safetensors` only. The app and runner reject
   pickle-based `.pth` and `.pt` checkpoints in inspection and execution. This
   avoids treating a model file as executable Python merely because it is local.

## Technical references

- [Spandrel model loading and image descriptors](https://github.com/chainner-org/spandrel)
  provide reported scale, channel count, purpose, and image size requirements.
- [PyTorch MPS guidance](https://github.com/pytorch/pytorch/blob/main/docs/source/notes/mps.md)
  documents device availability and MPS execution. Native tests must prove
  the selected models run without CPU fallback.
- [FFmpeg concat demuxer and stream-copy documentation](https://ffmpeg.org/ffmpeg-all.html)
  inform the direct-copy branch; the app still has to validate the selected
  source streams and published result.

This phase explicitly changes the current at-most-one-upscale contract only
for the selected 2× → 3× pipeline when implemented. Until then,
[the architecture contract](../ARCHITECTURE.md) describes the active runtime.
