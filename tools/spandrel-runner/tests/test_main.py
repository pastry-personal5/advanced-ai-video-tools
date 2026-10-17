"""Protocol tests for the runner's manifest boundary without MPS inference."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Callable

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main as runner  # noqa: E402  # pylint: disable=wrong-import-position
from main import MAXIMUM_INPUT_PIXELS, PNG_COMPRESSION_LEVEL, PROTOCOL_VERSION, RunnerError, _publish_png, file_identity, load_manifest, preflight_batch, stat_identity  # noqa: E402  # pylint: disable=wrong-import-position


class _SizeRequirements:
    def check(self, width: int, height: int) -> bool:
        return width % 2 == 0 and height % 2 == 0


class _Descriptor:
    size_requirements = _SizeRequirements()


def _png(path: Path, size: tuple[int, int] = (4, 2)) -> Path:
    Image.new("RGB", size, color=0).save(path)
    return path


def _document(model: Path, output_directory: Path, input_path: Path, output_path: Path, *, width: int = 4, height: int = 2, output_width: int = 8, output_height: int = 4) -> dict[str, object]:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "model_identity": file_identity(model).__dict__,
        "output_directory": str(output_directory),
        "jobs": [{"input": {"path": str(input_path), "identity": file_identity(input_path).__dict__, "width": width, "height": height}, "output": {"path": str(output_path), "width": output_width, "height": output_height}}],
    }


def _manifest(path: Path, document: dict[str, object]) -> Path:
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_load_manifest_binds_exact_input_identity_and_output_directory(tmp_path: Path) -> None:
    model_path = tmp_path / "model.safetensors"
    model_path.write_bytes(b"model")
    input_path = _png(tmp_path / "input.png")
    output_directory = tmp_path / "outputs"
    output_directory.mkdir()
    output_path = output_directory / "output.png"
    request = load_manifest(_manifest(tmp_path / "jobs.json", _document(model_path, output_directory, input_path, output_path)))
    assert request.model_identity == file_identity(model_path)
    assert request.jobs[0].input.path == input_path.resolve()
    assert request.jobs[0].output.path == output_path.resolve()


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda value: value.update({"protocol_version": 2}), "unsupported protocol"),
        (lambda value: value.pop("model_identity"), "exactly"),
        (lambda value: value["jobs"][0]["input"].update({"path": "relative.png"}), "absolute path"),
        (lambda value: value["jobs"][0]["output"].update({"path": "/tmp/not-owned.png"}), "output_directory"),
    ],
)
def test_load_manifest_rejects_invalid_protocol(tmp_path: Path, mutator: Callable[[dict[str, object]], None], message: str) -> None:
    model = tmp_path / "model.safetensors"
    model.write_bytes(b"model")
    input_path = _png(tmp_path / "input.png")
    output_directory = tmp_path / "outputs"
    output_directory.mkdir()
    document = _document(model, output_directory, input_path, output_directory / "output.png")
    mutator(document)
    with pytest.raises(RunnerError, match=message):
        load_manifest(_manifest(tmp_path / "jobs.json", document))


def test_preflight_rejects_changed_inputs_before_creating_outputs(tmp_path: Path) -> None:
    model = tmp_path / "model.safetensors"
    model.write_bytes(b"model")
    input_path = _png(tmp_path / "input.png")
    output_directory = tmp_path / "outputs"
    output_directory.mkdir()
    output_path = output_directory / "output.png"
    request = load_manifest(_manifest(tmp_path / "jobs.json", _document(model, output_directory, input_path, output_path)))
    input_path.write_bytes(b"changed")
    with pytest.raises(RunnerError, match="input identity differs"):
        preflight_batch(_Descriptor(), file_identity(model), request, 2)
    assert not output_path.exists()


def test_preflight_rejects_wrong_output_size_and_existing_output(tmp_path: Path) -> None:
    model = tmp_path / "model.safetensors"
    model.write_bytes(b"model")
    input_path = _png(tmp_path / "input.png")
    output_directory = tmp_path / "outputs"
    output_directory.mkdir()
    output_path = output_directory / "output.png"
    request = load_manifest(_manifest(tmp_path / "jobs.json", _document(model, output_directory, input_path, output_path, output_width=7)))
    with pytest.raises(RunnerError, match="do not match"):
        preflight_batch(_Descriptor(), file_identity(model), request, 2)
    request = load_manifest(_manifest(tmp_path / "jobs.json", _document(model, output_directory, input_path, output_path)))
    output_path.write_bytes(b"occupied")
    with pytest.raises(RunnerError, match="output already exists"):
        preflight_batch(_Descriptor(), file_identity(model), request, 2)


def test_file_identity_contains_hash_and_stat_identity(tmp_path: Path) -> None:
    path = tmp_path / "model.safetensors"
    path.write_bytes(b"model")
    identity = file_identity(path)
    assert identity.path == str(path.resolve())
    assert identity.size_bytes == 5
    assert len(identity.sha256) == 64
    assert identity.inode > 0
    assert stat_identity(path).size_bytes == identity.size_bytes


def test_inspect_rejects_a_changed_manifest_model_before_loading(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The run boundary must compare the frozen identity before any checkpoint loader sees the file."""

    path = tmp_path / "model.safetensors"
    path.write_bytes(b"reviewed model")
    expected = file_identity(path)
    path.write_bytes(b"replacement model")
    monkeypatch.setattr(runner.torch.backends.mps, "is_available", lambda: True)
    loader_reached = False

    def unexpected_load(_path: Path) -> str:
        nonlocal loader_reached
        loader_reached = True
        return "float32"

    monkeypatch.setattr(runner, "checkpoint_precision", unexpected_load)
    with pytest.raises(RunnerError, match="model identity differs") as captured:
        runner.inspect_model(path, expected_identity=expected)

    assert captured.value.code == "invalid_request"
    assert not loader_reached


def test_publish_png_uses_fast_lossless_encoding_without_clobbering(tmp_path: Path) -> None:
    import numpy

    destination = tmp_path / "output.png"
    output = numpy.zeros((4, 8, 3), dtype=numpy.uint8)
    _publish_png(output, destination)
    with Image.open(destination) as image:
        image.verify()
        assert image.size == (8, 4)
    with pytest.raises(RunnerError, match="output appeared"):
        _publish_png(output, destination)
    assert PNG_COMPRESSION_LEVEL == 1


def test_process_batch_preserves_ordered_progress_with_bounded_workers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import numpy

    model = tmp_path / "model.safetensors"
    model.write_bytes(b"model")
    output_directory = tmp_path / "outputs"
    output_directory.mkdir()
    documents: list[dict[str, object]] = []
    for index in range(2):
        input_path = _png(tmp_path / f"input-{index}.png")
        documents.append(_document(model, output_directory, input_path, output_directory / f"output-{index}.png")["jobs"][0])  # type: ignore[index]
    document = _document(model, output_directory, tmp_path / "input-0.png", output_directory / "unused.png")
    document["jobs"] = documents
    request = load_manifest(_manifest(tmp_path / "jobs.json", document))
    published: list[Path] = []
    monkeypatch.setattr(runner, "_decode_rgb_png", lambda job: numpy.zeros((job.input.height, job.input.width, 3), dtype=numpy.uint8))
    monkeypatch.setattr(runner, "_infer_frame", lambda _descriptor, job, _input: numpy.zeros((job.output.height, job.output.width, 3), dtype=numpy.uint8))
    monkeypatch.setattr(runner, "_publish_png", lambda _output, destination: published.append(destination))
    progress: list[str] = []
    runner.process_batch(object(), request, progress.append)
    assert published == [job.output.path for job in request.jobs]
    assert [json.loads(record)["completed"] for record in progress] == [1, 2]


@pytest.mark.parametrize("name", ["model.safetensors", "model.PTH"])
def test_supported_model_suffixes_are_accepted(tmp_path: Path, name: str) -> None:
    assert runner._validate_model_path(tmp_path / name) == (tmp_path / name).resolve()  # pylint: disable=protected-access


@pytest.mark.parametrize("name", ["model.pt", "model.ckpt", "model.bin", "model"])
def test_torchscript_and_other_model_suffixes_are_rejected(tmp_path: Path, name: str) -> None:
    with pytest.raises(RunnerError, match=r"\.safetensors or \.pth") as captured:
        runner._validate_model_path(tmp_path / name)  # pylint: disable=protected-access
    assert captured.value.code == "invalid_request"


def test_published_input_limit_is_only_the_size_verified_on_the_supported_host() -> None:
    """Raising the limit requires new native evidence; DAT_x2 and DAT_x3 were run at 640x360 on 2026-10-17."""

    assert MAXIMUM_INPUT_PIXELS == 640 * 360
    assert runner.RUNNER_VERSION == "0.5.0"


def test_pth_loading_runs_no_pickle_payload_through_the_pinned_spandrel(tmp_path: Path) -> None:
    """A booby-trapped .pth is refused by Spandrel's restricted unpickler and its payload never runs."""

    import torch
    from spandrel import ModelLoader

    marker = tmp_path / "payload-ran"

    class Payload:
        def __reduce__(self):  # type: ignore[no-untyped-def]
            import os

            return (os.system, (f"touch {marker}",))

    checkpoint = tmp_path / "trap.pth"
    torch.save({"payload": Payload()}, checkpoint)

    with pytest.raises(Exception, match="forbidden|Unpickl"):
        ModelLoader(device="cpu").load_from_file(str(checkpoint))

    assert not marker.exists()


def _save_safetensors(path: Path, **tensors: "torch.Tensor") -> Path:
    from safetensors.torch import save_file

    save_file(tensors, str(path))
    return path


@pytest.mark.parametrize(
    ("dtypes", "expected"),
    [
        (("bfloat16",), "bfloat16"),
        (("bfloat16", "bfloat16"), "bfloat16"),
        (("float32",), "float32"),
        (("bfloat16", "float32"), "float32"),
        (("float16",), "float32"),
    ],
)
def test_precision_follows_the_checkpoint_dtype_and_is_never_float16(tmp_path: Path, dtypes: tuple[str, ...], expected: str) -> None:
    """Only an all-bfloat16 checkpoint runs in bfloat16; everything else stays float32."""

    import torch

    tensors = {f"w{index}": torch.zeros(4, dtype=getattr(torch, dtype)) for index, dtype in enumerate(dtypes)}
    tensors["counter"] = torch.zeros(1, dtype=torch.int64)
    path = _save_safetensors(tmp_path / "model.safetensors", **tensors)
    assert runner.checkpoint_precision(path) == expected


def test_precision_of_a_pth_checkpoint_uses_the_restricted_loader(tmp_path: Path) -> None:
    import torch

    path = tmp_path / "model.pth"
    torch.save({"w": torch.zeros(4, dtype=torch.bfloat16)}, path)
    assert runner.checkpoint_precision(path) == "bfloat16"
    torch.save({"w": torch.zeros(4)}, path)
    assert runner.checkpoint_precision(path) == "float32"


def test_unreadable_checkpoint_is_an_incompatible_model_not_a_crash(tmp_path: Path) -> None:
    path = tmp_path / "corrupt.safetensors"
    path.write_bytes(b"\x00" * 16)
    with pytest.raises(RunnerError) as captured:
        runner.checkpoint_precision(path)
    assert captured.value.code == "incompatible_model"


@pytest.mark.parametrize("dtype_name", ["bfloat16", "float32"])
def test_inference_runs_in_the_model_dtype_and_publishes_exact_uint8(tmp_path: Path, dtype_name: str) -> None:
    """The input is cast to the model's dtype and the result is rounded in float32."""

    import numpy
    import torch

    dtype = getattr(torch, dtype_name)

    class Descriptor:
        device = torch.device("cpu")

        def __init__(self) -> None:
            self.dtype = dtype
            self.seen: list[torch.dtype] = []

        def __call__(self, image: "torch.Tensor") -> "torch.Tensor":
            self.seen.append(image.dtype)
            return torch.nn.functional.interpolate(image, scale_factor=2)

    descriptor = Descriptor()
    job = runner.ManifestJob(runner.ManifestInput(tmp_path / "in.png", file_identity(_png(tmp_path / "in.png")), 4, 2), runner.ManifestOutput(tmp_path / "out.png", 8, 4))
    source = numpy.full((2, 4, 3), 128, dtype=numpy.uint8)
    source[0, 0] = 255
    source[1, 3] = 0

    output = runner._infer_frame(descriptor, job, source)  # pylint: disable=protected-access

    assert descriptor.seen == [dtype]
    assert output.dtype == numpy.uint8 and output.shape == (4, 8, 3)
    assert tuple(output[0, 0]) == (255, 255, 255) and tuple(output[3, 7]) == (0, 0, 0)
    assert int(output[3, 0, 0]) in range(127, 130)
