"""Frontend-neutral wording for the frozen AI portion of a job plan."""

from __future__ import annotations

from advanced_ai_video_tools.core.models import JobPlan, ProcessingPipeline, UpscaleBackend

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
