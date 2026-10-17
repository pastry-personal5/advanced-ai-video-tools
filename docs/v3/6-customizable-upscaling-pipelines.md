# V3 Phase 6 — Customizable Upscaling Pipelines

## Status

- State: Complete (2026-10-17)
- Predecessor: [Phase 5 — Unified Settings Dialog](5-settings-dialog.md) (complete)
- Design recorded: 2026-10-11
- Implementation approval: 2026-10-17 (user request to complete the interrupted implementation)
- Acceptance evidence: Complete (see [Implementation record and evidence](#implementation-record-and-evidence))

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

For the first Phase 6 implementation and native evaluation, use the
user-supplied `2xPublic_realplksr_dysample_layernorm_real_nn.pth` checkpoint for
2× and `DAT_x3_bf16.safetensors` for 3× (amended 2026-10-17 from `DAT_x2.safetensors` and
`DAT_x3.safetensors`; see the checkpoint-trust amendment below). The bf16 file is a DAT
3× RGB model; under the amended precision policy below it runs in bfloat16. Keep the existing 4×
`realesrgan-x4plus`/Real-ESRGAN path unchanged. These initial checkpoint
selections do not authorize bundling or downloading model files and remain
subject to the runner inspection, MPS, size, and acceptance gates below.

**Factory-default tool–model pair** (recorded 2026-10-17, "for now"):

| Scale | Tool | Model |
| --- | --- | --- |
| 2× | `spandrel-runner` (`tools/spandrel-runner/spandrel-runner`) | `2xPublic_realplksr_dysample_layernorm_real_nn.pth` (PLKSR, float32) |
| 3× | `spandrel-runner` (`tools/spandrel-runner/spandrel-runner`) | `DAT_x3_bf16.safetensors` (DAT, bfloat16) |
| 4× | `realesrgan-ncnn-vulkan` | `realesrgan-x4plus` |

The application applies this pair when nothing is configured (scope amendment
2026-10-17, at the user's direction; the original design named the checkpoints only as
acceptance defaults). An unset runner resolves to the checkout's
`tools/spandrel-runner/spandrel-runner` and is never looked up on `PATH`. An unset 2× or
3× model resolves to the default file in the `models` directory beside the resolved
runner, so an explicit runner elsewhere moves the default models beside itself. A
configured runner or model always wins. The resolution lives in `ToolDiscovery`, so the
CLI and GUI share it, and the frozen plan records the resolved paths. A missing default is
a blocking preflight error that names the expected path and the `--spandrel-runner`,
`--model-2x`, or `--model-3x` override. It never blocks a pipeline that does not need it,
and Settings validation never requires it. The default location is the source checkout: an
installed package without `tools/spandrel-runner` reports the missing launcher instead of
searching `PATH`. The model files stay user-supplied, unbundled, and gitignored
(`tools/spandrel-runner/models/`); the native acceptance suite
(`make phase6-native-test`) uses the same two files by default.

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
  `.safetensors` or `.pth` model file for each of 2× and 3×. Add the user-installed
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
  architectures, unsupported formats (TorchScript `.pt`, `.ckpt`, and others), or model-load failures
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

- Use the isolated, user-installed Spandrel batch runner in
  `tools/spandrel-runner` (its own uv workspace member) with a documented
  `inspect` command and a manifest-driven PNG `run` command whose outputs are
  confined to one job-owned directory. Do not add Spandrel or PyTorch to the
  main application's runtime dependencies or download them from the
  application. Define and test a versioned JSON inspection result,
  line-delimited progress records, stable exit/error codes, absolute
  input/output paths, and compatibility checks before integrating the runner
  with the application. Inspection must not create processing output. Both
  commands accept only `.safetensors` and `.pth` checkpoints and use the same
  restricted loader policy: a `.pth` is read only by Spandrel's restricted
  state-dict unpickler (tensor rebuilds and `OrderedDict` only; any other global
  raises), and TorchScript `.pt` and `.ckpt` files are never loaded.
- The runner requires Apple Silicon MPS for supported jobs; lack of MPS is an
  actionable failure. It must check `torch.backends.mps.is_available()` before
  loading a model and launch with `PYTORCH_ENABLE_MPS_FALLBACK=0`, so unsupported
  MPS operations fail rather than running on CPU. It never silently switches
  device. Precision comes only from the checkpoint's own floating dtype (see the
  precision amendment under Resolved design decisions). The runner checks the model descriptor and native scale,
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
  and codec checks. Exercise unsupported runner protocol, `.pt`/`.ckpt` and
  other unsupported-format rejection, model descriptor, channel/scale, size-requirement,
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
3. **Checkpoint trust (amended 2026-10-17):** support `.safetensors` and `.pth`
   only. Originally `.safetensors` only; the user chose to allow `.pth` so the
   supplied RealPLKSR 2× checkpoint can be used. A `.pth` is loaded solely through
   Spandrel's restricted unpickler, and a runner test proves a booby-trapped `.pth`
   raises without running its payload. This is defense in depth, not a promise that
   an untrusted file is safe: only choose checkpoints you trust. TorchScript `.pt`
   and `.ckpt` stay rejected in inspection and execution because their loaders are
   unrestricted. The goal is unchanged: do not treat a model file as executable Python
   merely because it is local.
4. **Precision (amended 2026-10-17):** the runner may execute in bfloat16. A checkpoint
   whose floating-point tensors are all bfloat16 runs in bfloat16 on MPS; every other
   checkpoint, including fp16-only files, runs in float32. The choice comes only from the
   file, is published as `precision` (`float32` or `bfloat16`) in the inspection record
   (which the application rejects if it is anything else), and is never float16 and never
   changed silently. An architecture without bfloat16 support is rejected as
   `incompatible_model`. Frames are converted to the model dtype on input and rounded to
   8-bit in float32 on output; bfloat16 carries about 8 bits of mantissa, so subtle
   banding is possible and the output should be judged visually. Runner version 0.5.0.

## Technical references

- [Spandrel model loading and image descriptors](https://github.com/chainner-org/spandrel)
  provide reported scale, channel count, purpose, and image size requirements.
- [PyTorch MPS guidance](https://github.com/pytorch/pytorch/blob/main/docs/source/notes/mps.md)
  documents device availability and MPS execution. Native tests must prove
  the selected models run without CPU fallback.
- [FFmpeg concat demuxer and stream-copy documentation](https://ffmpeg.org/ffmpeg-all.html)
  inform the direct-copy branch; the app still has to validate the selected
  source streams and published result.

This phase changes the at-most-one-upscale contract only for the explicit 2× → 3× pipeline.
It is implemented, and [the architecture contract](../ARCHITECTURE.md) describes the active runtime.

## Implementation record and evidence

Recorded 2026-10-17 on an Apple M5 Max (128 GB), macOS 26.7.1, FFmpeg 8.1.1,
Python 3.13.5, PyTorch 2.14.1, Spandrel 0.4.2. Only verified results are listed.

### Implemented and covered by automated checks

- `make check`: Black, Pylint 10.00/10, pycodestyle, and 412 passed / 13 skipped
  (the skips are the opt-in native suites). The runner's own suite
  (`uv run --package spandrel-runner --with pytest python -m pytest tools/spandrel-runner/tests`)
  passed 32 tests. `git diff --check` is clean.
- Unit tests no longer reach host tools: fakes implement the real
  `discover_media`/`complete_for_passes` boundary, and the default suite passes with
  FFmpeg and Real-ESRGAN absent from `PATH`.
- `tests/test_phase6_pipelines.py` drives real preflight, tool discovery, the
  protocol parser, executors, cancellation, and FFmpeg over scripted AI backends:
  native 2×/3×/4×, 2× → 3× → resize with monotonic aggregate progress and final-pass
  previews, 4× then resize, resize-only skips that need no AI tool, the 4×/6× ceiling,
  MP4 and MOV concat only (one `-c copy` command, no filter or encoder), blocking
  normalization reasons, a second-pass failure that keeps the old output and the
  workspace, cancellation of the second pass, and a model replaced after review.
- Factory defaults: `tests/test_tools.py` covers the default runner and models, an explicit
  runner moving the default models beside itself, an explicit model winning, the missing
  default runner and model errors, unused defaults never blocking, and `PATH` never being
  used. `tests/test_phase6_pipelines.py` runs native 2×, native 3×, and the two-pass
  pipeline with nothing configured, rejects a missing default in preflight, rejects a
  default checkpoint replaced after review (the queued-job path the GUI shares), and checks
  that the upscale log names each pass's real model. `tests/test_gui_settings_dialog.py` covers
  the placeholders and the **Use default** runner button, and `tests/test_cli.py` the help
  text. An end-to-end CLI native 2× and 3× run from outside the repository, with no runner
  or model flags and no runner on `PATH`, published 192×144 and 288×216 MP4s from a 96×72
  clip.

### Rulings made during implementation

1. `tools/spandrel-runner` is the Phase 6 protocol-1 runner; no second runner exists.
2. One ordered-pass executor serves every AI pipeline, Auto included. Progress is the
   observed count of completed output frames for both backends, not parsed runner
   stdout. Real-ESRGAN keeps its bounded memory retries; Spandrel passes never retry.
3. `ai_scale` is the product of the frozen pass scales (6 for 2× → 3×).
4. A native pass whose result height is odd is rejected in preflight (`yuv420p`).
5. A separate destination filesystem is charged only the final partial; the workspace
   is charged the rest.
6. The runner's published maximum input size is 640×360 (230,400 px), runner 0.4.1.
   The earlier 16,777,216 was never run. See below.

### Native acceptance on the supplied models

The first native run (recorded under "Earlier run") used `DAT_x2.safetensors` and
`DAT_x3.safetensors`. On 2026-10-17 the selection changed to
`2xPublic_realplksr_dysample_layernorm_real_nn.pth` for 2× (architecture PLKSR, native
scale 2, RGB, no size constraints) and `DAT_x3_bf16.safetensors` for 3× (architecture DAT,
native scale 3, RGB, minimum size 16, weights stored as bfloat16). The two subsections
below ran on those selected checkpoints with the final code.

#### Consolidated native suite

`make phase6-native-test` ran 9 checks, and all 9 passed in 48.9 s. They cover a real
2× → 3× job publishing a verified MP4 with source audio retained, native 2× and 3×,
cancellation of the real second pass (runner killed, workspace cleaned, old output
preserved), runner and model failures that are actionable and never fall back (including an
unavailable MPS device, corrupt models, and wrong-scale models), a model replaced after
review and rejected by authoritative preflight, and CLI concat-only MP4 and MOV plus a CLI
native job.

#### 640×360 acceptance

`advanced-ai-video-tools process --pipeline native --scale N`, with explicit runner and
model flags, ran one 640×360 frame (cut from a 640×480 H.264 sample, so its pixel aspect
ratio is 3:4 and its display aspect is 4:3) through each selected checkpoint. The frozen
plan's pass input was 640×360 (230,400 px, the published limit), the models produced
1280×720 and 1920×1080, and the final encode resolved the display sizes to 960×720 and
1440×1080.

| Scale | Model | Device and precision | Result | Job wall time | Peak resident memory |
| --- | --- | --- | --- | --- | --- |
| 2× | `2xPublic_realplksr_dysample_layernorm_real_nn.pth` | `mps`, float32 | exit 0, 960×720, 1 frame | 4.6 s | 0.51 GB |
| 3× | `DAT_x3_bf16.safetensors` | `mps`, bfloat16 | exit 0, 1440×1080, 1 frame | 8.5 s | 1.23 GB |

Wall time includes startup, normalization, and encoding. Peak memory is the largest
resident set reported by `/usr/bin/time -l`. As a sanity check, the PSNR of each output
against a Lanczos upscale of the source at the same size was 30.1 dB (2×) and 37.7 dB (3×),
and a visual check of both frames showed sharp, plausible upscales with no black or
corrupt output; no stricter image-quality criterion was applied. The published 230,400-pixel
limit is therefore verified for the selected checkpoints and was not raised.

Native GUI capture (`make gui-capture-test`) was not run for Phase 6 at the user's
direction; this phase's native acceptance list does not require it.

#### Earlier run (superseded float32 DAT files)

`make phase6-native-test` first ran 9 checks on `DAT_x2.safetensors` and
`DAT_x3.safetensors`: 8 passed and 1 failed in 150 s. The failure was the test's own
MPS-unavailable simulation (it patched PyTorch before importing the runner); after fixing
the test it passed alone.

#### Earlier smoke run

On 2026-10-17, before the acceptance above, one 4-frame, 96×72 clip went through the
selected checkpoints with `process --pipeline native --scale N`:

| Scale | Model | Device reported | Result | Job wall time |
| --- | --- | --- | --- | --- |
| 2× | `2xPublic_realplksr_dysample_layernorm_real_nn.pth` | PLKSR, `mps`, float32 | exit 0, 192×144, 4 frames | 4.5 s |
| 3× | `DAT_x3_bf16.safetensors` | DAT, `mps`, bfloat16 | exit 0, 288×216, 4 frames | 8.7 s |
| 4× | `realesrgan-x4plus` | Vulkan, Apple M5 Max | exit 0, 384×288, 4 frames | 1.3 s |

This was the first recorded bfloat16 inference on MPS. A visual check showed a few faint
speckles in the 3× frame that were not compared against float32.

### Measured performance and the input-size limit

`DAT_x2.safetensors` and `DAT_x3.safetensors` each ran one 640×360 frame on MPS
(about 183 s and 170 s per frame, under 2 GB). Diagnostic timings of 128×72 to 256×144
frames grew faster than linearly with pixel count and were not faster than the CPU at
128×72. Full-HD frames are therefore impractical with these float32 models in direct
inference, and larger inputs are unverified and rejected by preflight. Tiling or a
faster model is deferred by the design above. Real-ESRGAN pipelines are unaffected.

The selected checkpoints took far less at the same size: a 640×360 job took 4.6 s with
the PLKSR checkpoint and 8.5 s with the bfloat16 DAT checkpoint, against about 170–183 s
per frame for the float32 DAT files. The 230,400-pixel limit stays; a larger limit needs new
native evidence and a runner version bump.

Diagnostic, not acceptance evidence: on 2026-10-17 a scratch driver lifted the runner's
own limit in memory (production code unchanged, application and preflight not involved) and
ran `DAT_x3_bf16.safetensors` through the real `run` path on a 1280×720 frame (921,600 px,
four times the limit) to 3840×2160. Eight frames took 67.8 s in total: the first took 16.1 s
(model load and MPS compilation), and frames 2–7 took 8.1–8.9 s each, so about 8.5 s per
frame once warm. The last frame's progress arrives right after the one before it because
the runner overlaps encoding with the next frame, so that gap is not inference time. The
process held 3.0 GB resident, and the MPS driver allocator held about 21 GB at the end,
which is approximate because it includes cached blocks. The output was a valid 3840×2160
PNG that matched its input at 55.8 dB PSNR after downscaling back, a consistency check only,
since the input was itself upscaled from a 640×480 sample. Not run: the 2× checkpoint at
that size, a full application job at that size (4K intermediate frames, final encode, and
the free-space estimate are application-side), and anything above 1280×720.
