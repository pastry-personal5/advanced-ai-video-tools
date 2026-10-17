"""Convert float16 tensors in a PyTorch checkpoint to bfloat16."""

from __future__ import annotations

import argparse
import os
import pickle
import tempfile
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import torch


@dataclass(frozen=True)
class CheckpointInspection:
    """Human-readable facts collected from a safely loaded checkpoint."""

    serialization_format: str
    root_type: str
    top_level_keys: tuple[str, ...]
    additional_top_level_keys: int
    tensor_count: int
    dtype_counts: tuple[tuple[str, int], ...]
    float16_tensor_count: int


def _describe_serialization(input_path: Path) -> str:
    """Identify the container without unpickling it."""

    if not zipfile.is_zipfile(input_path):
        return "legacy PyTorch pickle archive"
    with zipfile.ZipFile(input_path) as archive:
        if any(name.endswith("constants.pkl") for name in archive.namelist()):
            return "TorchScript ZIP archive"
    return "PyTorch ZIP archive"


def _tensor_dtype_counts(value: object) -> Counter[str]:
    """Count tensor dtypes through standard checkpoint containers."""

    if isinstance(value, torch.Tensor):
        return Counter({str(value.dtype): 1})
    if isinstance(value, dict):
        return sum((_tensor_dtype_counts(item) for item in value.values()), Counter())
    if isinstance(value, (list, tuple)):
        return sum((_tensor_dtype_counts(item) for item in value), Counter())
    return Counter()


def inspect_checkpoint(input_path: Path, checkpoint: object) -> CheckpointInspection:
    """Summarize checkpoint contents before modifying any tensor values."""

    top_level_keys: tuple[str, ...] = ()
    additional_top_level_keys = 0
    if isinstance(checkpoint, dict):
        keys = tuple(str(key) for key in checkpoint)
        top_level_keys = keys[:12]
        additional_top_level_keys = len(keys) - len(top_level_keys)
    dtype_counts = _tensor_dtype_counts(checkpoint)
    return CheckpointInspection(
        serialization_format=_describe_serialization(input_path),
        root_type=type(checkpoint).__name__,
        top_level_keys=top_level_keys,
        additional_top_level_keys=additional_top_level_keys,
        tensor_count=sum(dtype_counts.values()),
        dtype_counts=tuple(sorted(dtype_counts.items())),
        float16_tensor_count=dtype_counts[str(torch.float16)],
    )


def print_inspection(input_path: Path, inspection: CheckpointInspection) -> None:
    """Show the exact input format and tensor precision before conversion."""

    print(f"Input checkpoint: {input_path}")
    print(f"Serialization: {inspection.serialization_format}")
    print(f"Top-level value: {inspection.root_type}")
    if inspection.top_level_keys:
        suffix = f" (+{inspection.additional_top_level_keys} more)" if inspection.additional_top_level_keys else ""
        print("Top-level keys: " + ", ".join(inspection.top_level_keys) + suffix)
    print(f"Tensors: {inspection.tensor_count}")
    if inspection.dtype_counts:
        print("Tensor dtypes: " + ", ".join(f"{dtype}={count}" for dtype, count in inspection.dtype_counts))
    print(f"Float16 tensors eligible for conversion: {inspection.float16_tensor_count}")


def convert_float16_tensors(value: object) -> tuple[object, int]:
    """Preserve checkpoint containers and all values except float16 tensors."""

    if isinstance(value, torch.Tensor):
        if value.dtype == torch.float16:
            return value.to(dtype=torch.bfloat16), 1
        return value, 0

    if isinstance(value, dict):
        count = 0
        for key, item in value.items():
            value[key], converted = convert_float16_tensors(item)
            count += converted
        return value, count

    if isinstance(value, list):
        count = 0
        for index, item in enumerate(value):
            value[index], converted = convert_float16_tensors(item)
            count += converted
        return value, count

    if isinstance(value, tuple):
        converted_items = [convert_float16_tensors(item) for item in value]
        return tuple(item for item, _ in converted_items), sum(count for _, count in converted_items)

    return value, 0


def convert_checkpoint(input_path: Path, output_path: Path, checkpoint: object | None = None) -> int:
    """Load safely on CPU and publish a converted checkpoint without overwrite."""

    if not input_path.is_file():
        raise ValueError(f"input checkpoint does not exist: {input_path}")
    if input_path.suffix.lower() != ".pth" or output_path.suffix.lower() != ".pth":
        raise ValueError("input and output paths must end in .pth")
    if input_path.resolve() == output_path.resolve():
        raise ValueError("input and output paths must differ")
    if output_path.exists() or output_path.is_symlink():
        raise ValueError(f"output already exists: {output_path}")
    if not output_path.parent.is_dir():
        raise ValueError(f"output directory does not exist: {output_path.parent}")

    if checkpoint is None:
        checkpoint = torch.load(input_path, map_location="cpu", weights_only=True)
    checkpoint, count = convert_float16_tensors(checkpoint)
    if count == 0:
        raise ValueError("checkpoint contains no float16 tensors")

    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{output_path.stem}-", suffix=".pth", dir=output_path.parent)
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        torch.save(checkpoint, temporary_path)
        os.link(temporary_path, output_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="source .pth checkpoint")
    parser.add_argument("output", type=Path, help="new .pth checkpoint; must not exist")
    args = parser.parse_args()
    try:
        checkpoint = torch.load(args.input, map_location="cpu", weights_only=True)
        print_inspection(args.input, inspect_checkpoint(args.input, checkpoint))
        count = convert_checkpoint(args.input, args.output, checkpoint)
    except (OSError, RuntimeError, ValueError, pickle.UnpicklingError) as error:
        parser.exit(1, f"error: {error}\n")
    print(f"Converted {count} float16 tensor(s) to bfloat16: {args.output}")


if __name__ == "__main__":
    main()
