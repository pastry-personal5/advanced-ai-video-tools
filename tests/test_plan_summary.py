"""Tests for the frontend-neutral AI plan summary."""

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from advanced_ai_video_tools.core.models import ColorMatrix, ColorProfile, ConcatStrategy, JobPlan, ProcessingPipeline, Rational, UpscaleBackend, UpscalePassPlan
from advanced_ai_video_tools.services.plan_summary import PIPELINE_LABELS, ai_plan_summary, ai_skipped, pipeline_stage_summaries, source_dimensions


def _plan(pipeline: ProcessingPipeline, passes: tuple[UpscalePassPlan, ...] = ()) -> JobPlan:
    return JobPlan(
        datetime(2026, 8, 21, tzinfo=timezone.utc),
        Path("output.mp4"),
        True,
        (),
        Rational(24, 1),
        3840,
        2160,
        None,
        ConcatStrategy.NORMALIZE,
        None,
        (),
        100,
        120,
        ColorProfile(ColorMatrix.BT709, "bt709", "bt709"),
        pipeline=pipeline,
        upscale_passes=passes,
    )


def _pass(index: int, backend: UpscaleBackend, scale: int) -> UpscalePassPlan:
    return UpscalePassPlan(index, backend, scale, 100, 100, 100 * scale, 100 * scale, Path("tool"), Path("model"))


def test_summary_names_every_ordered_pass_and_backend() -> None:
    """The user can see exactly which models run, and in which order."""

    two_pass = _plan(ProcessingPipeline.TWO_X_THREE_X_RESIZE, (_pass(1, UpscaleBackend.SPANDREL, 2), _pass(2, UpscaleBackend.SPANDREL, 3)))
    assert ai_plan_summary(two_pass) == "2× Spandrel → 3× Spandrel"
    assert ai_plan_summary(_plan(ProcessingPipeline.AUTO, (_pass(1, UpscaleBackend.REALESRGAN, 4),))) == "4× Real-ESRGAN"
    assert not ai_skipped(two_pass)
    assert source_dimensions(two_pass) == (100, 100)
    assert pipeline_stage_summaries(two_pass) == (
        "Normalize and concatenate — FFmpeg",
        "Extract RGB frames — FFmpeg",
        "AI upscale 2× — model (Spandrel)",
        "AI upscale 3× — model (Spandrel)",
        "Resize to 3840×2160 and encode — FFmpeg",
        "Verify and publish — FFprobe and atomic publication",
    )


def test_summary_discloses_a_skip_for_ai_pipelines_only() -> None:
    """A missing scale is reported as a skip, while concat only is never called a skip."""

    for pipeline in (ProcessingPipeline.AUTO, ProcessingPipeline.FOUR_X_RESIZE, ProcessingPipeline.TWO_X_THREE_X_RESIZE):
        plan = _plan(pipeline)
        assert ai_skipped(plan)
        assert ai_plan_summary(plan) == "skipped (source height already meets the desired height)"
    concat = _plan(ProcessingPipeline.CONCAT)
    assert not ai_skipped(concat)
    assert ai_plan_summary(concat) == "not used (concat only; streams are copied, never re-encoded)"
    assert replace(concat, pipeline=ProcessingPipeline.CONCAT) == concat


def test_every_pipeline_has_one_user_facing_label_in_roadmap_order() -> None:
    """Both frontends share the same names for the five pipeline choices."""

    assert [pipeline for pipeline, _label in PIPELINE_LABELS] == list(ProcessingPipeline)
    assert [label for _pipeline, label in PIPELINE_LABELS] == ["Auto", "Concat only", "Native upscale", "4× then resize", "2× → 3× → resize"]
