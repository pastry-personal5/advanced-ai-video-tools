"""Tests for consistent immutable pipeline progress emission."""

from pathlib import Path

from advanced_ai_video_tools.core.models import PipelineStage, ProgressEvent
from advanced_ai_video_tools.services.progress import ProgressEmitter


def test_emitter_creates_one_typed_event_with_optional_preview_paths() -> None:
    """Stage services can forward measured progress and paired preview samples."""

    events: list[ProgressEvent] = []
    original = Path("frames/frame-000000016.png")
    upscaled = Path("upscaled/frame-000000016.png")

    ProgressEmitter.emit(
        events.append,
        PipelineStage.UPSCALE,
        16,
        32,
        "Upscaling frame 16 of 32",
        original_preview_image_path=original,
        upscaled_preview_image_path=upscaled,
    )

    assert events == [ProgressEvent(PipelineStage.UPSCALE, 16, 32, "Upscaling frame 16 of 32", original, upscaled)]


def test_emitter_skips_event_construction_without_a_callback() -> None:
    """Progress remains optional at every synchronous service boundary."""

    ProgressEmitter.emit(None, PipelineStage.VALIDATE, 0, None, "Validating")
