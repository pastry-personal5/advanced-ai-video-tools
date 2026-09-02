"""Tests for strict Real-ESRGAN policy and shell-free command construction."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from advanced_ai_video_tools.core.models import ColorMatrix, ColorProfile, ConcatStrategy, JobPlan, Rational, ToolInfo, Toolchain
from advanced_ai_video_tools.upscaling.realesrgan import AUTOMATIC_TILE_SIZE, MEMORY_RETRY_TILE_SIZES, REAL_IMAGE_MODEL, create_realesrgan_command, create_upscale_plan, is_vulkan_memory_failure, select_ai_scale


def _toolchain(tmp_path: Path) -> Toolchain:
    models = tmp_path / "models"
    models.mkdir()
    (models / f"{REAL_IMAGE_MODEL}.param").touch()
    (models / f"{REAL_IMAGE_MODEL}.bin").touch()
    tool = ToolInfo(tmp_path / "tool", "version")
    return Toolchain(tool, tool, ToolInfo(tmp_path / "realesrgan-ncnn-vulkan", "usage"), models)


def _job(*, scale: int | None = 2, height: int = 72, model_name: str = REAL_IMAGE_MODEL) -> JobPlan:
    return JobPlan(datetime(2026, 8, 21, tzinfo=timezone.utc), Path("output.mp4"), True, (), Rational(10, 1), 128, height, scale, ConcatStrategy.NORMALIZE, None, (), 100, 120, ColorProfile(ColorMatrix.BT709, "bt709", "bt709"), model_name=model_name)


def test_real_image_command_uses_directory_mode_and_explicit_safe_defaults(tmp_path: Path) -> None:
    """The adapter never inherits the executable's anime-model default."""

    frames = tmp_path / "job" / "frames"
    frames.mkdir(parents=True)
    plan = create_upscale_plan(_job(), _toolchain(tmp_path), frames.parent, input_directory=frames, frame_count=10, input_width=64, input_height=36)
    command = create_realesrgan_command(plan, AUTOMATIC_TILE_SIZE)

    assert command[command.index("-i") + 1] == str(frames)
    assert command[command.index("-o") + 1] == str(frames.parent / "upscaled")
    assert command[command.index("-m") + 1] == str(tmp_path / "models")
    assert command[command.index("-n") + 1] == REAL_IMAGE_MODEL
    assert command[command.index("-s") + 1] == "2"
    assert command[command.index("-t") + 1] == "0"
    assert command[command.index("-f") + 1] == "png"
    assert "-g" not in command and "-j" not in command and "-x" not in command


def test_scale_policy_and_plan_reject_inconsistent_or_anime_decisions(tmp_path: Path) -> None:
    """Only the smallest useful real-image scale can reach execution."""

    assert select_ai_scale(1080, 2160) == 2
    assert select_ai_scale(720, 2160) == 3
    assert select_ai_scale(540, 2160) == 4
    assert select_ai_scale(2160, 2160) is None
    frames = tmp_path / "job" / "frames"
    frames.mkdir(parents=True)
    tools = _toolchain(tmp_path)
    with pytest.raises(ValueError, match="inconsistent"):
        create_upscale_plan(_job(scale=3), tools, frames.parent, input_directory=frames, frame_count=1, input_width=64, input_height=36)
    with pytest.raises(ValueError, match="real-image model"):
        create_upscale_plan(_job(model_name="realesrgan-x4plus-anime"), tools, frames.parent, input_directory=frames, frame_count=1, input_width=64, input_height=36)
    with pytest.raises(ValueError, match="tile size"):
        create_realesrgan_command(create_upscale_plan(_job(), tools, frames.parent, input_directory=frames, frame_count=1, input_width=64, input_height=36), 16)


@pytest.mark.parametrize("diagnostic", ["vkAllocateMemory failed -2", "VK_ERROR_OUT_OF_DEVICE_MEMORY", "Memory allocation failed.", "Could not allocate 4096 bytes of device memory", "Out of heap memory"])
def test_only_recognized_memory_diagnostics_enable_tile_retries(diagnostic: str) -> None:
    """Known allocation messages are distinguished from unrelated failures."""

    assert is_vulkan_memory_failure("", diagnostic)
    assert not is_vulkan_memory_failure("", "invalid gpu device")
    assert not is_vulkan_memory_failure("", "failed to load model")
    assert not is_vulkan_memory_failure("", "vkAllocateMemory failed -4")
    assert MEMORY_RETRY_TILE_SIZES == (512, 256, 128, 64, 32)
