"""Tests for exact, typed domain values."""

from pathlib import Path

import pytest

from advanced_ai_video_tools.core.models import PipelineStage, ProgressEvent, Rational


def test_rational_normalizes_sign_and_common_divisor() -> None:
    """Equivalent rational inputs have one stable representation."""

    assert Rational(60000, -2002) == Rational(-30000, 1001)
    assert str(Rational.parse("30000/1001")) == "30000/1001"
    assert Rational.parse("4:3") == Rational(4, 3)


def test_rational_rejects_zero_denominator() -> None:
    """An invalid FFprobe fraction never enters a job plan."""

    with pytest.raises(ValueError, match="denominator"):
        Rational(1, 0)


def test_progress_preview_images_are_limited_to_upscale_events() -> None:
    """Only measured upscale progress may expose paired sampled frames to the GUI."""

    original = Path("original-frame-000000016.png")
    upscaled = Path("upscaled-frame-000000016.png")
    event = ProgressEvent(PipelineStage.UPSCALE, 16, 32, "Upscaling", original, upscaled)
    assert event.original_preview_image_path == original
    assert event.upscaled_preview_image_path == upscaled
    with pytest.raises(ValueError, match="upscale"):
        ProgressEvent(PipelineStage.ENCODE, 16, 32, "Encoding", original)
