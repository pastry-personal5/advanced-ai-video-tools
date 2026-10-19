# GUI user guide

Advanced AI Video Tools provides a native PySide6 desktop application for
macOS on Apple Silicon. It processes the same typed job service used by the
CLI.

## Start the application

From the repository:

```bash
uv sync --dev
uv run advanced-ai-video-tools gui
```

You can also open the unsigned development `.app`/`.dmg` built with
`make package-dev-dmg`.

The application requires macOS 26.5.2 or later on Apple Silicon, installed
FFmpeg and FFprobe, and a working user-managed Real-ESRGAN Vulkan installation
with the `realesrgan-x4plus` model files.

## Settings

Open **Preferences → Settings** (or press **Command-,**). Search all settings from the field at the top,
or choose a page from the left tree:

- **Editor → File** configures ordered automatic related-file deletion rules.
- **Processing → Upscaling** sets the default pipeline, native scale, and desired
  height, and chooses the 2× and 3× `.safetensors` or `.pth` model files. The
  factory-default models are `2xPublic_realplksr_dysample_layernorm_real_nn.pth` (2×) and
  `DAT_x3_bf16.safetensors` (3×), run by `tools/spandrel-runner/spandrel-runner`. A blank
  field uses its default, shown as placeholder text.
- **Tools → External Tools** configures FFmpeg, FFprobe, Real-ESRGAN, its
  model directory, and the Spandrel runner executable.
- **Input and Output → Color Policy** contains the off-by-default **Allow mixed
  color tags** preference. Enable it only if untagged clips are known to match
  the other clips' unanimous declared supported SDR profile.

Leave an executable blank to use `PATH` (the Spandrel runner instead uses the
factory-default `tools/spandrel-runner/spandrel-runner`); leave the model directory
blank to use the `models` directory beside Real-ESRGAN. **Use PATH**, **Use default**
(runner), and **Automatic** clear explicit overrides. **Validate** checks executable launchability, model files,
and a small Vulkan inference away from the GUI thread. A chosen Spandrel runner
and 2×/3× model are inspected by the runner away from the GUI thread; TorchScript
`.pt`, `.ckpt`, and other formats are refused (a `.pth` is read only by a restricted
tensor-only loader; choose only models you trust), and a model whose scale or channels do not fit its slot
is reported without falling back to another model. A model left blank never
blocks a pipeline that does not use it.

All pages share one draft. **OK** validates changed tools when necessary and
atomically saves the whole draft; **Cancel** discards it. Validation and save
failures leave existing settings unchanged and show recovery guidance inside
the dialog. Finder-launched bundles preserve the inherited `PATH` and add
standard Homebrew and MacPorts locations.

Deletion rules apply only after the source clip itself moves successfully to
Trash. The first enabled source rule matches immediate sibling regular files;
related-file failures are reported without rolling back the source move.

## Create a job

1. Add local video clips in the desired top-to-bottom concatenation order.
2. Choose an output directory, the **pipeline**, and, if needed, the native scale
   or target height. The height box is disabled for **Concat only** and
   **Native upscale**, which ignore it; its value is kept for the other pipelines.
3. Select **Preflight** and review every warning and blocking issue.
4. Acknowledge the listed extra streams when you explicitly accept dropping
   them. This acknowledgement applies only to the reviewed job and is never
   saved as a preference.
5. Submit the accepted job to the queue.

Preflight runs away from the GUI thread. The review lists the original and
target dimensions plus every resolved processing stage, including its action
and AI model filename or model name when applicable, and the free workspace
space the job needs. The authoritative preflight runs again
when the queued job starts, so changes to inputs or settings cannot silently
alter a submitted job: a queued job keeps the tool and model paths it was
submitted with and is rejected if its model file was replaced in the meantime.
Queueing a job also saves its pipeline and scale as the defaults for later jobs;
it never changes your model files.

The source Preview remembers its mute choice when you move between clips. A
muted preview shows the output-volume bar at zero; unmuting restores the volume
level you had selected. These audio choices also apply to Queue Preview and are
saved as non-safety preferences.

The pipelines are **Auto** (the default, same as earlier versions), **Concat only**
(stream-copies compatible MP4/MOV clips into the first clip's container with no
re-encoding and no AI), **Native upscale** (one AI pass at the model's own 2×, 3×,
or 4× scale), **4× then resize**, and **2× → 3× → resize** (the only choice that
runs AI twice).

## Monitor and control jobs

Queue Monitoring shows **Active**, **Up Next**, and **History** regions. The
Selected Job panel shows the first input's full file path and appends `, ...` when
the job contains additional input clips. The Input row appears immediately
above the output destination. The queue runs one job at a time. You can cancel
the active job, remove pending or
terminal jobs, select jobs with the keyboard, and inspect progress, output
paths, errors, and diagnostics. When a queued job starts, **Global Messages**
shows the dimensions and stage/model summary from its authoritative preflight.

The queue preview provides **Original**, **Upscaled**, and **Final Video** tabs.
During upscaling, matched frame samples appear as they become available; a
two-pass job shows samples from its final pass only, and its message names the
current pass. After
completion, the published final video plays once and then stops on its last
frame.

The application closes cooperatively: pending and active work is cancelled,
preview resources are released, owned temporary state is cleaned according to
job outcome, and the queue worker is joined before exit.

## Fullscreen source preview

Open fullscreen preview from the preview pane or a source-row action. Fullscreen
playback is keyboard-driven:

- `0` / `9`: first / last frame
- `j` / `l`: previous / next clip, starting playback
- `Space` / `k`: play or pause
- `Shift-P` / `Shift-N`: play the previous or next clip from its start
- `Esc`: close fullscreen
- `?`: show shortcut help

## Settings and files

The application stores non-secret preferences and local diagnostics in its
standard macOS application-support location. It stores job workspaces in the
standard macOS cache location. Do not place model weights, generated media, or
credentials in the repository.
