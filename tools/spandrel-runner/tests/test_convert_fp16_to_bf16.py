"""Round-trip checks for the standalone checkpoint converter."""

from __future__ import annotations

import sys
import tempfile
import unittest
from collections import OrderedDict
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from convert_fp16_to_bf16 import convert_checkpoint, inspect_checkpoint, print_inspection  # noqa: E402  # pylint: disable=wrong-import-position


class CheckpointConversionTests(unittest.TestCase):
    def test_inspection_reports_container_and_tensor_dtypes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "input.pth"
            torch.save({"params": {"half": torch.ones(1, dtype=torch.float16), "float": torch.ones(1, dtype=torch.float32)}}, input_path)

            checkpoint = torch.load(input_path, weights_only=True)
            inspection = inspect_checkpoint(input_path, checkpoint)

            self.assertEqual(inspection.serialization_format, "PyTorch ZIP archive")
            self.assertEqual(inspection.root_type, "dict")
            self.assertEqual(inspection.top_level_keys, ("params",))
            self.assertEqual(inspection.tensor_count, 2)
            self.assertEqual(inspection.dtype_counts, (("torch.float16", 1), ("torch.float32", 1)))
            self.assertEqual(inspection.float16_tensor_count, 1)
            output = StringIO()
            with redirect_stdout(output):
                print_inspection(input_path, inspection)
            self.assertIn("Serialization: PyTorch ZIP archive", output.getvalue())
            self.assertIn("Tensor dtypes: torch.float16=1, torch.float32=1", output.getvalue())
            self.assertIn("Float16 tensors eligible for conversion: 1", output.getvalue())

    def test_converts_nested_float16_and_preserves_other_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "input.pth"
            output_path = Path(directory) / "output.pth"
            weights = OrderedDict(
                (name, tensor)
                for name, tensor in (
                    ("half", torch.tensor([1.5, -2.0], dtype=torch.float16)),
                    ("float", torch.tensor([3.0], dtype=torch.float32)),
                    ("integer", torch.tensor([4], dtype=torch.int64)),
                )
            )
            weights._metadata = {"": {"version": 1}}  # pylint: disable=protected-access
            torch.save({"params_ema": weights, "extras": [torch.ones(1, dtype=torch.float16), ("label", 7)]}, input_path)

            self.assertEqual(convert_checkpoint(input_path, output_path), 2)
            original = torch.load(input_path, weights_only=True)
            converted = torch.load(output_path, weights_only=True)
            self.assertEqual(original["params_ema"]["half"].dtype, torch.float16)
            self.assertEqual(converted["params_ema"]["half"].dtype, torch.bfloat16)
            self.assertEqual(converted["params_ema"]["float"].dtype, torch.float32)
            self.assertEqual(converted["params_ema"]["integer"].dtype, torch.int64)
            self.assertEqual(converted["params_ema"]._metadata, weights._metadata)  # pylint: disable=protected-access
            self.assertEqual(converted["extras"][0].dtype, torch.bfloat16)
            self.assertEqual(converted["extras"][1], ("label", 7))

    def test_rejects_existing_output_and_checkpoint_without_float16(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "input.pth"
            output_path = Path(directory) / "output.pth"
            torch.save({"weight": torch.ones(1, dtype=torch.float16)}, input_path)
            output_path.write_bytes(b"keep")
            with self.assertRaisesRegex(ValueError, "output already exists"):
                convert_checkpoint(input_path, output_path)
            self.assertEqual(output_path.read_bytes(), b"keep")
            output_path.unlink()
            torch.save({"weight": torch.ones(1, dtype=torch.float32)}, input_path)
            with self.assertRaisesRegex(ValueError, "no float16 tensors"):
                convert_checkpoint(input_path, output_path)
            self.assertFalse(output_path.exists())


if __name__ == "__main__":
    unittest.main()
