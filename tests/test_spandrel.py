"""Tests for the application's versioned Spandrel runner boundary."""

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from advanced_ai_video_tools.system.spandrel import SpandrelProtocolError, create_spandrel_inspect_command, create_spandrel_run_command, dimensions_satisfy, parse_spandrel_inspection, spandrel_failure_summary


def _inspection(model: Path, *, scale: int = 2, protocol: int = 1) -> str:
    return json.dumps(
        {
            "protocol_version": protocol,
            "runner_version": "0.4.0",
            "model_identity": {"path": str(model.resolve()), "device": 1, "inode": 2, "size_bytes": 3, "modified_ns": 4, "sha256": "a" * 64},
            "architecture": "DAT",
            "purpose": "SR",
            "input_channels": 3,
            "output_channels": 3,
            "scale": scale,
            "size_requirements": {"minimum": 8, "multiple_of": 4, "square": False},
            "maximum_input_pixels": 1000,
            "device": "mps",
            "precision": "float32",
        }
    )


def test_inspection_freezes_protocol_descriptor_identity_and_size_policy(tmp_path: Path) -> None:
    """A valid response freezes every execution-critical descriptor field."""

    model = tmp_path / "DAT_x2.safetensors"
    model.write_bytes(b"model")
    inspection = parse_spandrel_inspection(_inspection(model), expected_model=model, expected_scale=2)
    assert inspection.architecture == "DAT"
    assert inspection.model_identity.path == model.resolve()
    assert dimensions_satisfy(inspection, 20, 20)
    assert not dimensions_satisfy(inspection, 21, 20)
    assert not dimensions_satisfy(inspection, 40, 40)
    assert create_spandrel_inspect_command(tmp_path / "runner", model)[1] == "inspect"


@pytest.mark.parametrize(("change", "message"), [(lambda value: value.update({"protocol_version": 2}), "protocol"), (lambda value: value.update({"scale": 3}), "RGB 2x"), (lambda value: value.update({"device": "cpu"}), "MPS")])
def test_inspection_rejects_unsupported_runner_or_model_contract(tmp_path: Path, change: Callable[[dict[str, object]], None], message: str) -> None:
    """Protocol, scale, and MPS deviations fail before a processing launch."""

    model = tmp_path / "DAT_x2.safetensors"
    model.write_bytes(b"model")
    document = json.loads(_inspection(model))
    change(document)
    with pytest.raises(SpandrelProtocolError, match=message):
        parse_spandrel_inspection(json.dumps(document), expected_model=model, expected_scale=2)


@pytest.mark.parametrize("name", ["model.safetensors", "model.SAFETENSORS", "model.pth", "model.PTH"])
def test_safetensors_and_restricted_pth_models_cross_the_runner_boundary(tmp_path: Path, name: str) -> None:
    """The two supported formats become shell-free inspect and run commands."""

    inspect = create_spandrel_inspect_command(tmp_path / "runner", tmp_path / name)
    run = create_spandrel_run_command(tmp_path / "runner", tmp_path / name, tmp_path / "jobs.json")
    assert inspect[:3] == (str(tmp_path / "runner"), "inspect", "--model") and run[1] == "run"


@pytest.mark.parametrize("name", ["model.pt", "model.ckpt", "model.bin", "model.onnx", "model"])
def test_torchscript_and_other_formats_are_rejected_before_launch(tmp_path: Path, name: str) -> None:
    """TorchScript .pt and every other format never reach the runner."""

    with pytest.raises(SpandrelProtocolError, match=r"\.safetensors or \.pth"):
        create_spandrel_inspect_command(tmp_path / "runner", tmp_path / name)
    with pytest.raises(SpandrelProtocolError, match=r"\.safetensors or \.pth"):
        create_spandrel_run_command(tmp_path / "runner", tmp_path / name, tmp_path / "jobs.json")


def test_runner_failure_summary_uses_the_last_stable_error_record() -> None:
    """Only the runner's documented JSON error record becomes user-facing text."""

    stderr = 'torch warning noise\n{"code": "mps_unavailable", "event": "error", "message": "MPS is unavailable"}\n'
    assert spandrel_failure_summary(stderr) == "mps_unavailable: MPS is unavailable"
    assert spandrel_failure_summary("Traceback (most recent call last):\nValueError") is None
    assert spandrel_failure_summary('{"event": "progress", "completed": 1}') is None
    assert spandrel_failure_summary('{"event": "error", "code": 7, "message": "bad"}') is None


@pytest.mark.parametrize("precision", ["float32", "bfloat16"])
def test_inspection_accepts_only_the_published_precisions(tmp_path: Path, precision: str) -> None:
    """The runner may report float32 or bfloat16; anything else, such as float16, is refused."""

    model = tmp_path / "model.safetensors"
    document = json.loads(_inspection(model))
    document["precision"] = precision
    assert parse_spandrel_inspection(json.dumps(document), expected_model=model, expected_scale=2).precision == precision
    document["precision"] = "float16"
    with pytest.raises(SpandrelProtocolError, match="precision"):
        parse_spandrel_inspection(json.dumps(document), expected_model=model, expected_scale=2)
