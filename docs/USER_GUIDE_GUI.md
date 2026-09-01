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

## Configure external tools

Open **Edit → Preferences**. Leave an executable blank to discover it from
`PATH`, or select an explicit executable. Leave the model directory blank to
use the `models` directory beside the resolved Real-ESRGAN executable.

Use **Validate & Save** to check executable launchability, model files, and a
small Vulkan inference. Failed values are not persisted. **Use PATH** and
**Automatic** clear explicit overrides. Finder-launched bundles preserve the
inherited `PATH` and add standard Homebrew and MacPorts locations.

## Create a job

1. Add local video clips in the desired top-to-bottom concatenation order.
2. Choose an output directory and, if needed, change the target height.
3. Select **Preflight** and review every warning and blocking issue.
4. Acknowledge the listed extra streams when you explicitly accept dropping
   them. This acknowledgement applies only to the reviewed job and is never
   saved as a preference.
5. Submit the accepted job to the queue.

Preflight runs away from the GUI thread. The authoritative preflight runs again
when the queued job starts, so changes to inputs or settings cannot silently
alter a submitted job.

## Monitor and control jobs

Queue Monitoring shows **Active**, **Up Next**, and **History** regions. The
queue runs one job at a time. You can cancel the active job, remove pending or
terminal jobs, select jobs with the keyboard, and inspect progress, output
paths, errors, and diagnostics.

The queue preview provides **Original**, **Upscaled**, and **Final Video** tabs.
During upscaling, matched frame samples appear as they become available. After
completion, the published final video plays in a loop.

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

