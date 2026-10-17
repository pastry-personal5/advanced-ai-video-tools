"""Tests for strict Real-ESRGAN policy and shell-free command construction."""

from pathlib import Path

import pytest

from advanced_ai_video_tools.core.models import UpscaleBackend, UpscalePassPlan
from advanced_ai_video_tools.upscaling.realesrgan import AUTOMATIC_TILE_SIZE, MEMORY_RETRY_TILE_SIZES, REAL_IMAGE_MODEL, create_realesrgan_command, create_realesrgan_plan, is_vulkan_memory_failure, select_ai_scale


def _models(tmp_path: Path) -> Path:
    models = tmp_path / "models"
    models.mkdir()
    (models / f"{REAL_IMAGE_MODEL}.param").touch()
    (models / f"{REAL_IMAGE_MODEL}.bin").touch()
    return models


def _pass(tmp_path: Path, models: Path, *, scale: int = 2, backend: UpscaleBackend = UpscaleBackend.REALESRGAN) -> UpscalePassPlan:
    return UpscalePassPlan(1, backend, scale, 64, 36, 64 * scale, 36 * scale, tmp_path / "realesrgan-ncnn-vulkan", models)


def test_real_image_command_uses_directory_mode_and_explicit_safe_defaults(tmp_path: Path) -> None:
    """The adapter never inherits the executable's anime-model default."""

    frames = tmp_path / "job" / "frames"
    frames.mkdir(parents=True)
    models = _models(tmp_path)
    plan = create_realesrgan_plan(_pass(tmp_path, models), REAL_IMAGE_MODEL, input_directory=frames, output_directory=frames.parent / "upscaled", frame_count=10)
    command = create_realesrgan_command(plan, AUTOMATIC_TILE_SIZE)

    assert command[command.index("-i") + 1] == str(frames)
    assert command[command.index("-o") + 1] == str(frames.parent / "upscaled")
    assert command[command.index("-m") + 1] == str(models)
    assert command[command.index("-n") + 1] == REAL_IMAGE_MODEL
    assert command[command.index("-s") + 1] == "2"
    assert command[command.index("-t") + 1] == "0"
    assert command[command.index("-f") + 1] == "png"
    assert "-g" not in command and "-j" not in command and "-x" not in command


def test_scale_policy_and_plan_reject_unsupported_models_backends_and_tiles(tmp_path: Path) -> None:
    """Only a real-image x4plus pass with its model files can reach execution."""

    assert select_ai_scale(1080, 2160) == 2
    assert select_ai_scale(720, 2160) == 3
    assert select_ai_scale(540, 2160) == 4
    assert select_ai_scale(2160, 2160) is None
    frames = tmp_path / "job" / "frames"
    frames.mkdir(parents=True)
    models = _models(tmp_path)
    output = frames.parent / "upscaled"
    with pytest.raises(ValueError, match="real-image model"):
        create_realesrgan_plan(_pass(tmp_path, models), "realesrgan-x4plus-anime", input_directory=frames, output_directory=output, frame_count=1)
    with pytest.raises(ValueError, match="Real-ESRGAN pass"):
        create_realesrgan_plan(_pass(tmp_path, models, backend=UpscaleBackend.SPANDREL), REAL_IMAGE_MODEL, input_directory=frames, output_directory=output, frame_count=1)
    with pytest.raises(ValueError, match="scale"):
        create_realesrgan_plan(_pass(tmp_path, models, scale=5), REAL_IMAGE_MODEL, input_directory=frames, output_directory=output, frame_count=1)
    (models / f"{REAL_IMAGE_MODEL}.bin").unlink()
    with pytest.raises(ValueError, match=r"realesrgan-x4plus\.bin"):
        create_realesrgan_plan(_pass(tmp_path, models), REAL_IMAGE_MODEL, input_directory=frames, output_directory=output, frame_count=1)
    (models / f"{REAL_IMAGE_MODEL}.bin").touch()
    plan = create_realesrgan_plan(_pass(tmp_path, models), REAL_IMAGE_MODEL, input_directory=frames, output_directory=output, frame_count=1)
    with pytest.raises(ValueError, match="tile size"):
        create_realesrgan_command(plan, 16)


@pytest.mark.parametrize("diagnostic", ["vkAllocateMemory failed -2", "VK_ERROR_OUT_OF_DEVICE_MEMORY", "Memory allocation failed.", "Could not allocate 4096 bytes of device memory", "Out of heap memory"])
def test_only_recognized_memory_diagnostics_enable_tile_retries(diagnostic: str) -> None:
    """Known allocation messages are distinguished from unrelated failures."""

    assert is_vulkan_memory_failure("", diagnostic)
    assert not is_vulkan_memory_failure("", "invalid gpu device")
    assert not is_vulkan_memory_failure("", "failed to load model")
    assert not is_vulkan_memory_failure("", "vkAllocateMemory failed -4")
    assert MEMORY_RETRY_TILE_SIZES == (512, 256, 128, 64, 32)
