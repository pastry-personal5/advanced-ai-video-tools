"""Frontend-neutral wording for the frozen AI portion of a job plan."""

from __future__ import annotations

from advanced_ai_video_tools.core.models import ConcatStrategy, JobPlan, ProcessingPipeline, UpscaleBackend

PIPELINE_LABELS: tuple[tuple[ProcessingPipeline, str], ...] = (
    (ProcessingPipeline.AUTO, "Auto"),
    (ProcessingPipeline.CONCAT, "Concat only"),
    (ProcessingPipeline.NATIVE, "Native upscale"),
    (ProcessingPipeline.FOUR_X_RESIZE, "4× then resize"),
    (ProcessingPipeline.TWO_X_THREE_X_RESIZE, "2× → 3× → resize"),
)
_BACKEND_NAMES = {UpscaleBackend.REALESRGAN: "Real-ESRGAN", UpscaleBackend.SPANDREL: "Spandrel"}


def ai_skipped(plan: JobPlan) -> bool:
    """Whether an AI pipeline resolved to no pass because the source is tall enough."""

    return plan.pipeline is not ProcessingPipeline.CONCAT and not plan.upscale_passes


def ai_plan_summary(plan: JobPlan) -> str:
    """Describe the ordered passes, a skip, or concat only for either frontend."""

    if plan.pipeline is ProcessingPipeline.CONCAT:
        return "not used (concat only; streams are copied, never re-encoded)"
    if not plan.upscale_passes:
        return "skipped (source height already meets the desired height)"
    return " → ".join(f"{item.scale}× {_BACKEND_NAMES[item.backend]}" for item in plan.upscale_passes)


def source_dimensions(plan: JobPlan) -> tuple[int, int] | None:
    """Return the first clip's original coded dimensions when available."""

    if plan.probes:
        video = plan.probes[0].primary_video
        if video is not None:
            return video.width, video.height
    if plan.upscale_passes:
        first_pass = plan.upscale_passes[0]
        return first_pass.input_width, first_pass.input_height
    return None


def pipeline_stage_summaries(plan: JobPlan) -> tuple[str, ...]:
    """Describe each executable stage with its action and model when applicable."""

    if plan.pipeline is ProcessingPipeline.CONCAT:
        return (
            "Concatenate — stream copy with FFmpeg",
            "Verify and publish — FFprobe and atomic publication",
        )

    preparation = "Normalize and concatenate — FFmpeg" if plan.concat_strategy is ConcatStrategy.NORMALIZE else "Concatenate — stream copy with FFmpeg"
    stages = [preparation, "Extract RGB frames — FFmpeg"]
    if not plan.upscale_passes:
        stages.append("AI upscale — skipped; source height already meets the desired height")
    else:
        for upscale_pass in plan.upscale_passes:
            model = plan.model_name if upscale_pass.backend is UpscaleBackend.REALESRGAN else upscale_pass.model_path.name
            stages.append(f"AI upscale {upscale_pass.scale}× — {model} ({_BACKEND_NAMES[upscale_pass.backend]})")

    original = source_dimensions(plan)
    intermediate = (plan.upscale_passes[-1].output_width, plan.upscale_passes[-1].output_height) if plan.upscale_passes else original
    target = f"{plan.output_width}×{plan.output_height}"
    stages.append(f"Resize to {target} and encode — FFmpeg" if intermediate != (plan.output_width, plan.output_height) else f"Encode {target} — FFmpeg")
    stages.append("Verify and publish — FFprobe and atomic publication")
    return tuple(stages)
