"""Strict Real-ESRGAN NCNN Vulkan policy and shell-free commands."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from advanced_ai_video_tools.core.models import UpscaleBackend, UpscalePassPlan

REAL_IMAGE_MODEL = "realesrgan-x4plus"
SUPPORTED_SCALES = (2, 3, 4)
AUTOMATIC_TILE_SIZE = 0
MEMORY_RETRY_TILE_SIZES = (512, 256, 128, 64, 32)
_SUPPORTED_TILE_SIZES = (AUTOMATIC_TILE_SIZE,) + MEMORY_RETRY_TILE_SIZES
_VULKAN_MEMORY_CODE = re.compile(r"vk(?:allocatememory|createbuffer|createimage) failed -(?:1|2|1000069000)\b", re.IGNORECASE)
_VULKAN_MEMORY_MARKERS = (
    "vk_error_out_of_host_memory",
    "vk_error_out_of_device_memory",
    "vk_error_out_of_pool_memory",
    "out of memory",
    "out of heap memory",
    "memory allocation failed",
    "could not allocate",
)


@dataclass(frozen=True)
class UpscalePlan:
    """Frozen directory-mode Real-ESRGAN invocation inputs."""

    input_directory: Path
    output_directory: Path
    executable: Path
    model_directory: Path
    model_name: str
    scale: int
    expected_frame_count: int
    input_width: int
    input_height: int


def select_ai_scale(source_height: int, target_height: int) -> int | None:
    """Choose the smallest supported AI scale that reaches the target."""

    if source_height <= 0 or target_height <= 0:
        raise ValueError("source and target heights must be positive")
    if source_height >= target_height:
        return None
    for scale in SUPPORTED_SCALES:
        if source_height * scale >= target_height:
            return scale
    return 4


def create_realesrgan_plan(upscale_pass: UpscalePassPlan, model_name: str, *, input_directory: Path, output_directory: Path, frame_count: int) -> UpscalePlan:
    """Validate one frozen Real-ESRGAN pass and create its directory-mode plan."""

    if upscale_pass.backend is not UpscaleBackend.REALESRGAN:
        raise ValueError("not a Real-ESRGAN pass")
    if upscale_pass.scale not in SUPPORTED_SCALES:
        raise ValueError(f"Real-ESRGAN scale must be one of {SUPPORTED_SCALES}")
    if frame_count <= 0 or upscale_pass.input_width <= 0 or upscale_pass.input_height <= 0:
        raise ValueError("extracted frame inventory is invalid")
    if model_name != REAL_IMAGE_MODEL:
        raise ValueError(f"version 1 supports only the {REAL_IMAGE_MODEL} real-image model")
    required_models = (upscale_pass.model_path / f"{REAL_IMAGE_MODEL}.param", upscale_pass.model_path / f"{REAL_IMAGE_MODEL}.bin")
    missing_models = tuple(path.name for path in required_models if not path.is_file())
    if missing_models:
        raise ValueError("Real-ESRGAN model directory is missing: " + ", ".join(missing_models))
    return UpscalePlan(input_directory, output_directory, upscale_pass.executable_path, upscale_pass.model_path, model_name, upscale_pass.scale, frame_count, upscale_pass.input_width, upscale_pass.input_height)


def create_realesrgan_command(plan: UpscalePlan, tile_size: int) -> tuple[str, ...]:
    """Create one explicit directory-mode invocation with safe v1 defaults."""

    if plan.scale not in SUPPORTED_SCALES:
        raise ValueError(f"Real-ESRGAN scale must be one of {SUPPORTED_SCALES}")
    if tile_size not in _SUPPORTED_TILE_SIZES:
        raise ValueError(f"unsupported Real-ESRGAN tile size: {tile_size}")
    if plan.input_directory.resolve(strict=False) == plan.output_directory.resolve(strict=False):
        raise ValueError("Real-ESRGAN input and output directories must differ")
    return (str(plan.executable), "-i", str(plan.input_directory), "-o", str(plan.output_directory), "-m", str(plan.model_directory), "-n", plan.model_name, "-s", str(plan.scale), "-t", str(tile_size), "-f", "png")


def is_vulkan_memory_failure(stdout_tail: str, stderr_tail: str) -> bool:
    """Recognize only allocation failures for which smaller tiles are relevant."""

    diagnostic = "\n".join((stdout_tail, stderr_tail)).lower()
    return any(marker in diagnostic for marker in _VULKAN_MEMORY_MARKERS) or _VULKAN_MEMORY_CODE.search(diagnostic) is not None
