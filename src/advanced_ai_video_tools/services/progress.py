"""Consistent progress event emission for pipeline stages."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from advanced_ai_video_tools.core.models import PipelineStage, ProgressEvent

ProgressCallback = Callable[[ProgressEvent], None]


class ProgressEmitter:
    """Consistent progress event emission across all pipeline stages."""

    @staticmethod
    def emit(
        callback: ProgressCallback | None,
        stage: PipelineStage,
        completed: int,
        total: int | None,
        message: str,
        *,
        original_preview_image_path: Path | None = None,
        upscaled_preview_image_path: Path | None = None,
    ) -> None:
        """Emit progress event with optional preview paths.

        Args:
            callback: Progress callback to invoke, or None to skip.
            stage: The current pipeline stage.
            completed: Number of completed units.
            total: Total units, or None if unknown.
            message: Human-readable progress message.
            original_preview_image_path: Path to original frame preview, if any.
            upscaled_preview_image_path: Path to upscaled frame preview, if any.
        """
        if callback is not None:
            callback(
                ProgressEvent(
                    stage=stage,
                    completed=completed,
                    total=total,
                    message=message,
                    original_preview_image_path=original_preview_image_path,
                    upscaled_preview_image_path=upscaled_preview_image_path,
                )
            )
