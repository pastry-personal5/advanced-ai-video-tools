"""MPS-only, inspected-model PNG batch runner for V3 Phase 6."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Annotated, Any, Callable

os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "0"

import numpy
import torch
import typer
from PIL import Image
from spandrel import ModelLoader

PROTOCOL_VERSION = 1
# Verified on the supported host (Apple M5 Max, macOS 26.7.1): DAT_x2 and DAT_x3 each ran one
# 640x360 frame on MPS. Larger sizes are unverified and therefore not published.
RUNNER_VERSION = "0.5.0"
MAXIMUM_INPUT_PIXELS = 640 * 360
PNG_COMPRESSION_LEVEL = 1
# Spandrel loads `.pth` only through its restricted state-dict unpickler (tensor rebuilds and
# OrderedDict only; any other global raises), so a booby-trapped checkpoint cannot run code.
# TorchScript `.pt` and `.ckpt` are rejected because their loaders are not restricted.
SUPPORTED_MODEL_SUFFIXES = (".safetensors", ".pth")
# Precision policy: a checkpoint whose floating-point tensors are all bfloat16 runs in bfloat16 on
# MPS; every other checkpoint runs in float32. The choice comes only from the file, is published
# by `inspect`, and is never float16, never silently changed, and never moved off MPS.
EXIT_CODES = {"invalid_request": 2, "incompatible_model": 3, "mps_unavailable": 4, "inference_failed": 5, "output_conflict": 6}
app = typer.Typer(no_args_is_help=True, add_completion=False, help="Run one inspected Spandrel super-resolution model over an exact PNG manifest.")

ModelPath = Annotated[Path, typer.Option("--model", exists=True, file_okay=True, dir_okay=False, readable=True, resolve_path=True, help="Trusted .safetensors or .pth RGB super-resolution checkpoint.")]
ManifestPath = Annotated[Path, typer.Option("--manifest", exists=True, file_okay=True, dir_okay=False, readable=True, resolve_path=True, help="Phase 6 versioned batch manifest.")]
ProtocolVersion = Annotated[int, typer.Option("--protocol-version", help="Phase 6 runner protocol expected by the caller.")]


class RunnerError(RuntimeError):
    """A stable machine-readable runner failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class FileIdentity:
    """Path, stat identity, and content hash used for replacement detection."""

    path: str
    device: int
    inode: int
    size_bytes: int
    modified_ns: int
    sha256: str


@dataclass(frozen=True)
class StatIdentity:
    """Cheap identity used after the content hash has already been verified."""

    path: str
    device: int
    inode: int
    size_bytes: int
    modified_ns: int


@dataclass(frozen=True)
class ManifestInput:
    path: Path
    identity: FileIdentity
    width: int
    height: int


@dataclass(frozen=True)
class ManifestOutput:
    path: Path
    width: int
    height: int


@dataclass(frozen=True)
class ManifestJob:
    """One ordered source frame and its exact expected published frame."""

    input: ManifestInput
    output: ManifestOutput


@dataclass(frozen=True)
class BatchManifest:
    """The full preflightable run request, before any output is written."""

    model_identity: FileIdentity
    output_directory: Path
    jobs: tuple[ManifestJob, ...]


def _request_error(message: str) -> RunnerError:
    return RunnerError("invalid_request", message)


def _absolute_path(value: object, field_name: str) -> Path:
    if not isinstance(value, str) or not value:
        raise _request_error(f"{field_name} must be a non-empty absolute path")
    path = Path(value)
    if not path.is_absolute():
        raise _request_error(f"{field_name} must be an absolute path: {value!r}")
    return path.resolve(strict=False)


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise _request_error(f"{field_name} must be a positive integer")
    return value


def _validate_model_path(model_path: Path) -> Path:
    if model_path.suffix.lower() not in SUPPORTED_MODEL_SUFFIXES:
        raise _request_error("model must use .safetensors or .pth; TorchScript .pt, .ckpt, and other formats are not supported")
    return model_path.resolve()


def _validate_protocol(protocol_version: int) -> None:
    if protocol_version != PROTOCOL_VERSION:
        raise _request_error(f"unsupported protocol version {protocol_version}; expected {PROTOCOL_VERSION}")


def file_identity(path: Path) -> FileIdentity:
    """Return the complete file identity emitted by `inspect` and used by `run`."""

    try:
        before = stat_identity(path)
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        after = stat_identity(path)
    except OSError as error:
        raise _request_error(f"could not identify {path}: {error}") from error
    if before != after:
        raise _request_error(f"file changed while its identity was being calculated: {path}")
    return FileIdentity(before.path, before.device, before.inode, before.size_bytes, before.modified_ns, digest.hexdigest())


def stat_identity(path: Path) -> StatIdentity:
    """Read identity fields without rereading the file contents."""

    try:
        stat = path.stat()
    except OSError as error:
        raise _request_error(f"could not inspect {path}: {error}") from error
    return StatIdentity(str(path.resolve()), stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)


def _expected_stat(identity: FileIdentity) -> StatIdentity:
    return StatIdentity(identity.path, identity.device, identity.inode, identity.size_bytes, identity.modified_ns)


def _decode_identity(value: object, field_name: str) -> FileIdentity:
    if not isinstance(value, dict) or set(value) != {"path", "device", "inode", "size_bytes", "modified_ns", "sha256"}:
        raise _request_error(f"{field_name} must be a file identity from inspect")
    path = _absolute_path(value["path"], f"{field_name}.path")
    integers = {name: _positive_int(value[name], f"{field_name}.{name}") for name in ("device", "inode", "size_bytes", "modified_ns")}
    digest = value["sha256"]
    if not isinstance(digest, str) or len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise _request_error(f"{field_name}.sha256 must be a lowercase SHA-256 hex digest")
    return FileIdentity(str(path), integers["device"], integers["inode"], integers["size_bytes"], integers["modified_ns"], digest)


def _decode_manifest_input(value: object, index: int) -> ManifestInput:
    field_name = f"jobs[{index}].input"
    if not isinstance(value, dict) or set(value) != {"path", "identity", "width", "height"}:
        raise _request_error(f"{field_name} must contain path, identity, width, and height")
    path = _absolute_path(value["path"], f"{field_name}.path")
    identity = _decode_identity(value["identity"], f"{field_name}.identity")
    if identity.path != str(path):
        raise _request_error(f"{field_name}.identity.path must match {field_name}.path")
    return ManifestInput(path, identity, _positive_int(value["width"], f"{field_name}.width"), _positive_int(value["height"], f"{field_name}.height"))


def _decode_manifest_output(value: object, index: int, output_directory: Path) -> ManifestOutput:
    field_name = f"jobs[{index}].output"
    if not isinstance(value, dict) or set(value) != {"path", "width", "height"}:
        raise _request_error(f"{field_name} must contain path, width, and height")
    path = _absolute_path(value["path"], f"{field_name}.path")
    if path.parent != output_directory or path.suffix.lower() != ".png":
        raise _request_error(f"{field_name}.path must be a .png direct child of output_directory")
    return ManifestOutput(path, _positive_int(value["width"], f"{field_name}.width"), _positive_int(value["height"], f"{field_name}.height"))


def load_manifest(manifest_path: Path) -> BatchManifest:
    """Decode an exact, versioned batch that cannot name arbitrary outputs."""

    try:
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise _request_error(f"could not read JSON manifest {manifest_path}: {error}") from error
    if not isinstance(document, dict) or set(document) != {"protocol_version", "model_identity", "output_directory", "jobs"}:
        raise _request_error("manifest must contain exactly protocol_version, model_identity, output_directory, and jobs")
    version = document["protocol_version"]
    if isinstance(version, bool) or not isinstance(version, int):
        raise _request_error("manifest.protocol_version must be an integer")
    _validate_protocol(version)
    model_identity = _decode_identity(document["model_identity"], "manifest.model_identity")
    output_directory = _absolute_path(document["output_directory"], "manifest.output_directory")
    if output_directory.is_symlink() or not output_directory.is_dir():
        raise _request_error("manifest.output_directory must be an existing non-symlink directory")
    raw_jobs = document["jobs"]
    if not isinstance(raw_jobs, list) or not raw_jobs:
        raise _request_error("manifest.jobs must be a non-empty list")
    jobs: list[ManifestJob] = []
    output_paths: set[Path] = set()
    for index, raw_job in enumerate(raw_jobs):
        if not isinstance(raw_job, dict) or set(raw_job) != {"input", "output"}:
            raise _request_error(f"jobs[{index}] must contain exactly input and output")
        input_frame = _decode_manifest_input(raw_job["input"], index)
        output_frame = _decode_manifest_output(raw_job["output"], index, output_directory)
        if input_frame.path.suffix.lower() != ".png":
            raise _request_error(f"jobs[{index}].input.path must use .png")
        if output_frame.path in output_paths:
            raise _request_error(f"manifest reuses output path: {output_frame.path}")
        output_paths.add(output_frame.path)
        jobs.append(ManifestJob(input_frame, output_frame))
    return BatchManifest(model_identity, output_directory, tuple(jobs))


def _descriptor_value(descriptor: Any, name: str) -> Any:
    value = getattr(descriptor, name, None)
    return value.value if hasattr(value, "value") else value


def _size_requirements(descriptor: Any) -> dict[str, object]:
    requirements = getattr(descriptor, "size_requirements", None)
    return {"minimum": int(getattr(requirements, "minimum", 0)), "multiple_of": int(getattr(requirements, "multiple_of", 1)), "square": bool(getattr(requirements, "square", False))}


def checkpoint_precision(model_path: Path) -> str:
    """Return the execution precision implied by the checkpoint's own floating-point dtype."""

    try:
        state = ModelLoader(device="cpu").load_state_dict_from_file(str(model_path))
    except Exception as error:
        raise RunnerError("incompatible_model", f"could not read checkpoint tensors: {error}") from error
    dtypes = {tensor.dtype for tensor in state.values() if isinstance(tensor, torch.Tensor) and tensor.is_floating_point()}
    return "bfloat16" if dtypes == {torch.bfloat16} else "float32"


def inspect_model(model_path: Path, *, expected_identity: FileIdentity | None = None) -> tuple[Any, dict[str, object], FileIdentity]:
    """Verify, load, and describe one supported model on MPS."""

    model_path = _validate_model_path(model_path)
    if not torch.backends.mps.is_available():
        raise RunnerError("mps_unavailable", "MPS is unavailable; the runner does not fall back to CPU")
    model_identity = file_identity(model_path)
    if expected_identity is not None and model_identity != expected_identity:
        raise _request_error("model identity differs from the inspected model_identity in the manifest")
    precision = checkpoint_precision(model_path)
    try:
        descriptor = ModelLoader(device="mps").load_from_file(str(model_path)).to("mps").eval()
        if precision == "bfloat16":
            descriptor.to(torch.bfloat16)
    except Exception as error:
        raise RunnerError("incompatible_model", f"could not load model on MPS in {precision}: {error}") from error
    if stat_identity(model_path) != _expected_stat(model_identity):
        raise _request_error("model changed while it was being loaded")
    purpose = str(_descriptor_value(descriptor, "purpose")).upper()
    input_channels = _descriptor_value(descriptor, "input_channels")
    output_channels = _descriptor_value(descriptor, "output_channels")
    scale = _descriptor_value(descriptor, "scale")
    if purpose != "SR" or input_channels != 3 or output_channels != 3 or not isinstance(scale, int) or scale not in {2, 3}:
        raise RunnerError("incompatible_model", "model must be an RGB 2x or 3x super-resolution descriptor")
    inspection = {
        "protocol_version": PROTOCOL_VERSION,
        "runner_version": RUNNER_VERSION,
        "model_identity": asdict(model_identity),
        "architecture": str(_descriptor_value(getattr(descriptor, "architecture", None), "id") or getattr(descriptor, "architecture", "unknown")),
        "purpose": purpose,
        "input_channels": input_channels,
        "output_channels": output_channels,
        "scale": scale,
        "size_requirements": _size_requirements(descriptor),
        "maximum_input_pixels": MAXIMUM_INPUT_PIXELS,
        "device": "mps",
        "precision": precision,
    }
    return descriptor, inspection, model_identity


def _verify_rgb_png(path: Path, expected_width: int, expected_height: int) -> None:
    """Verify PNG structure and metadata without decoding and copying pixels."""

    try:
        with Image.open(path) as image:
            if image.format != "PNG" or image.mode != "RGB":
                raise _request_error(f"input must be an RGB PNG: {path}")
            if image.size != (expected_width, expected_height):
                raise _request_error(f"input dimensions changed for {path}: expected {expected_width}x{expected_height}, got {image.width}x{image.height}")
            image.verify()
    except (OSError, SyntaxError) as error:
        raise _request_error(f"could not verify input PNG {path}: {error}") from error


def _decode_rgb_png(job: ManifestJob) -> numpy.ndarray[Any, numpy.dtype[numpy.uint8]]:
    """Decode one preflighted frame into a compact CPU uint8 staging array."""

    if stat_identity(job.input.path) != _expected_stat(job.input.identity):
        raise _request_error(f"input identity changed before inference: {job.input.path}")
    try:
        with Image.open(job.input.path) as image:
            if image.format != "PNG" or image.mode != "RGB" or image.size != (job.input.width, job.input.height):
                raise _request_error(f"input PNG changed before inference: {job.input.path}")
            decoded = numpy.array(image, dtype=numpy.uint8, copy=True)
    except (OSError, SyntaxError) as error:
        raise _request_error(f"could not decode input PNG {job.input.path}: {error}") from error
    if stat_identity(job.input.path) != _expected_stat(job.input.identity):
        raise _request_error(f"input identity changed during decode: {job.input.path}")
    return decoded


def _validate_dimensions(descriptor: Any, width: int, height: int) -> None:
    if width * height > MAXIMUM_INPUT_PIXELS:
        raise _request_error(f"input dimensions {width}x{height} exceed the {MAXIMUM_INPUT_PIXELS}-pixel runner limit")
    requirements = getattr(descriptor, "size_requirements", None)
    if requirements is not None and not requirements.check(width, height):
        raise _request_error(f"input dimensions {width}x{height} do not meet the model size requirements")


def preflight_batch(descriptor: Any, model_identity: FileIdentity, manifest: BatchManifest, scale: int) -> None:
    """Validate all identities, PNGs, dimensions, and outputs before inference."""

    if model_identity != manifest.model_identity:
        raise _request_error("model identity differs from the inspected model_identity in the manifest")
    for job in manifest.jobs:
        if file_identity(job.input.path) != job.input.identity:
            raise _request_error(f"input identity differs from the reviewed manifest: {job.input.path}")
        _verify_rgb_png(job.input.path, job.input.width, job.input.height)
        _validate_dimensions(descriptor, job.input.width, job.input.height)
        if (job.output.width, job.output.height) != (job.input.width * scale, job.input.height * scale):
            raise _request_error(f"output dimensions for {job.output.path} do not match the {scale}x model scale")
        if job.output.path.exists() or job.output.path.is_symlink():
            raise RunnerError("output_conflict", f"output already exists: {job.output.path}")


def _publish_png(output: numpy.ndarray[Any, numpy.dtype[numpy.uint8]], destination: Path) -> None:
    """Encode, verify, and atomically create one lossless low-compression PNG."""

    image = Image.fromarray(output)
    descriptor, raw_path = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".partial.png", dir=destination.parent)
    temporary_path = Path(raw_path)
    try:
        os.close(descriptor)
        image.save(temporary_path, format="PNG", compress_level=PNG_COMPRESSION_LEVEL)
        with Image.open(temporary_path) as encoded:
            if encoded.format != "PNG" or encoded.mode != "RGB" or encoded.size != image.size:
                raise RunnerError("inference_failed", f"encoded output verification failed: {destination}")
            encoded.verify()
        os.link(temporary_path, destination)
        temporary_path.unlink()
    except FileExistsError as error:
        raise RunnerError("output_conflict", f"output appeared while processing: {destination}") from error
    except OSError as error:
        raise RunnerError("inference_failed", f"could not publish output {destination}: {error}") from error
    finally:
        temporary_path.unlink(missing_ok=True)


def _infer_frame(descriptor: Any, job: ManifestJob, input_array: numpy.ndarray[Any, numpy.dtype[numpy.uint8]]) -> numpy.ndarray[Any, numpy.dtype[numpy.uint8]]:
    """Infer one frame while minimizing CPU allocations and device transfer size."""

    input_tensor = torch.from_numpy(input_array).permute(2, 0, 1).unsqueeze(0).to(device=descriptor.device, dtype=torch.float32).div_(255.0).to(descriptor.dtype)
    try:
        with torch.inference_mode():
            output_tensor = descriptor(input_tensor)
    except Exception as error:
        raise RunnerError("inference_failed", f"MPS inference failed for {job.input.path}: {error}") from error
    output = output_tensor.squeeze(0).permute(1, 2, 0)
    if tuple(output.shape) != (job.output.height, job.output.width, 3):
        raise RunnerError("inference_failed", f"model produced tensor shape {tuple(output.shape)}, expected ({job.output.height}, {job.output.width}, 3)")
    output_u8 = output.to(torch.float32).mul(255.0).round_().clamp_(0, 255).to(dtype=torch.uint8).to("cpu")
    return output_u8.numpy()


def _progress_record(completed: int, total: int, job: ManifestJob) -> str:
    return json.dumps({"event": "progress", "completed": completed, "total": total, "input": str(job.input.path), "output": str(job.output.path)}, sort_keys=True)


def process_batch(descriptor: Any, manifest: BatchManifest, progress: Callable[[str], None]) -> None:
    """Overlap one-frame-ahead decode and one-frame-behind encode around MPS."""

    jobs = manifest.jobs
    pending_encode: tuple[Future[None], int, ManifestJob] | None = None

    def finish_pending() -> None:
        nonlocal pending_encode
        if pending_encode is None:
            return
        future, completed, completed_job = pending_encode
        future.result()
        progress(_progress_record(completed, len(jobs), completed_job))
        pending_encode = None

    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="spandrel-decode") as decoder, ThreadPoolExecutor(max_workers=1, thread_name_prefix="spandrel-encode") as encoder:
        pending_decode = decoder.submit(_decode_rgb_png, jobs[0])
        try:
            for index, job in enumerate(jobs):
                input_array = pending_decode.result()
                if index + 1 < len(jobs):
                    pending_decode = decoder.submit(_decode_rgb_png, jobs[index + 1])
                output_array = _infer_frame(descriptor, job, input_array)
                finish_pending()
                pending_encode = (encoder.submit(_publish_png, output_array, job.output.path), index + 1, job)
            finish_pending()
        except Exception:
            finish_pending()
            raise


@app.command()
def inspect(model: ModelPath, protocol_version: ProtocolVersion = PROTOCOL_VERSION) -> None:
    """Print a single JSON inspection object and create no processing output."""

    _validate_protocol(protocol_version)
    _descriptor, inspection, _model_identity = inspect_model(model)
    typer.echo(json.dumps(inspection, sort_keys=True))


@app.command()
def run(model: ModelPath, manifest: ManifestPath, protocol_version: ProtocolVersion = PROTOCOL_VERSION) -> None:
    """Preflight a manifest, then emit one JSON progress record per PNG output."""

    _validate_protocol(protocol_version)
    manifest_request = load_manifest(manifest)
    descriptor, inspection, model_identity = inspect_model(model, expected_identity=manifest_request.model_identity)
    scale = inspection["scale"]
    if not isinstance(scale, int):
        raise RunnerError("incompatible_model", "validated model scale is not an integer")
    preflight_batch(descriptor, model_identity, manifest_request, scale)
    process_batch(descriptor, manifest_request, typer.echo)


def main() -> None:
    """Run Typer while preserving the runner's stable JSON error contract."""

    try:
        app(standalone_mode=False)
    except RunnerError as error:
        typer.echo(json.dumps({"event": "error", "code": error.code, "message": str(error)}, sort_keys=True), err=True)
        raise SystemExit(EXIT_CODES[error.code]) from error


if __name__ == "__main__":
    main()
