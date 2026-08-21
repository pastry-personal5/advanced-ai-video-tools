"""Strict Real-ESRGAN NCNN Vulkan policy and shell-free commands."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ai_video_tools.core.models import JobPlan, Toolchain

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
    scale: int | None
    expected_frame_count: int
    input_width: int
    input_height: int

    @property
    def skipped(self) -> bool:
        """Whether final FFmpeg scaling should consume the extracted frames."""

        return self.scale is None


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


def build_upscale_plan(job: JobPlan, toolchain: Toolchain, workspace: Path, *, input_directory: Path, frame_count: int, input_width: int, input_height: int) -> UpscalePlan:
    """Validate the frozen job decision and create its directory-mode plan."""

    workspace_path = workspace.resolve(strict=False)
    if input_directory.resolve(strict=False).parent != workspace_path:
        raise ValueError("extracted frames must be a direct child of the owned workspace")
    if frame_count <= 0 or input_width <= 0 or input_height <= 0:
        raise ValueError("extracted frame inventory is invalid")
    if job.model_name != REAL_IMAGE_MODEL:
        raise ValueError(f"version 1 supports only the {REAL_IMAGE_MODEL} real-image model")
    expected_scale = select_ai_scale(input_height, job.output_height)
    if job.ai_scale != expected_scale:
        raise ValueError("job AI scale is inconsistent with the extracted frame height")
    required_models = (toolchain.model_directory / f"{REAL_IMAGE_MODEL}.param", toolchain.model_directory / f"{REAL_IMAGE_MODEL}.bin")
    missing_models = tuple(path.name for path in required_models if not path.is_file())
    if missing_models:
        raise ValueError("Real-ESRGAN model directory is missing: " + ", ".join(missing_models))
    return UpscalePlan(input_directory, workspace_path / "upscaled", toolchain.realesrgan.path, toolchain.model_directory, job.model_name, job.ai_scale, frame_count, input_width, input_height)


def build_realesrgan_command(plan: UpscalePlan, tile_size: int) -> tuple[str, ...]:
    """Build one explicit directory-mode invocation with safe v1 defaults."""

    if plan.scale not in SUPPORTED_SCALES:
        raise ValueError("a skipped upscale plan has no Real-ESRGAN command")
    if tile_size not in _SUPPORTED_TILE_SIZES:
        raise ValueError(f"unsupported Real-ESRGAN tile size: {tile_size}")
    if plan.input_directory.resolve(strict=False) == plan.output_directory.resolve(strict=False):
        raise ValueError("Real-ESRGAN input and output directories must differ")
    return (str(plan.executable), "-i", str(plan.input_directory), "-o", str(plan.output_directory), "-m", str(plan.model_directory), "-n", plan.model_name, "-s", str(plan.scale), "-t", str(tile_size), "-f", "png")


def is_vulkan_memory_failure(stdout_tail: str, stderr_tail: str) -> bool:
    """Recognize only allocation failures for which smaller tiles are relevant."""

    diagnostic = "\n".join((stdout_tail, stderr_tail)).lower()
    return any(marker in diagnostic for marker in _VULKAN_MEMORY_MARKERS) or _VULKAN_MEMORY_CODE.search(diagnostic) is not None
