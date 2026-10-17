"""Versioned JSON boundary for the user-installed Spandrel batch runner."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from advanced_ai_video_tools.core.models import FileIdentity, SpandrelInspection

SPANDREL_PROTOCOL_VERSION = 1
# `.pth` is loaded by the runner only through Spandrel's restricted state-dict unpickler, which
# refuses every global except tensor rebuilds; TorchScript `.pt` and `.ckpt` are never accepted.
SUPPORTED_MODEL_SUFFIXES = (".safetensors", ".pth")
# The runner derives precision from the checkpoint itself and reports it; it never uses float16.
SUPPORTED_PRECISIONS = ("float32", "bfloat16")
UNSUPPORTED_MODEL_MESSAGE = "Spandrel models must use .safetensors or .pth; TorchScript .pt, .ckpt, and other formats are not supported."
# Factory defaults, recorded 2026-10-17 "for now". The runner is the checkout's own launcher and is never
# looked up on PATH; an unset model resolves to this file inside the `models` directory beside the runner.
DEFAULT_SPANDREL_RUNNER = Path(__file__).resolve().parents[3] / "tools" / "spandrel-runner" / "spandrel-runner"
DEFAULT_SPANDREL_MODELS = {2: "2xPublic_realplksr_dysample_layernorm_real_nn.pth", 3: "DAT_x3_bf16.safetensors"}


class SpandrelProtocolError(ValueError):
    """The runner returned an unsupported or malformed inspection document."""


def create_spandrel_inspect_command(executable: Path, model: Path) -> tuple[str, ...]:
    """Build one shell-free model-inspection command."""

    if model.suffix.lower() not in SUPPORTED_MODEL_SUFFIXES:
        raise SpandrelProtocolError(UNSUPPORTED_MODEL_MESSAGE)
    return (str(executable), "inspect", "--model", str(model), "--protocol-version", str(SPANDREL_PROTOCOL_VERSION))


def create_spandrel_run_command(executable: Path, model: Path, manifest: Path) -> tuple[str, ...]:
    """Build one shell-free directory-batch command."""

    if model.suffix.lower() not in SUPPORTED_MODEL_SUFFIXES:
        raise SpandrelProtocolError(UNSUPPORTED_MODEL_MESSAGE)
    return (str(executable), "run", "--model", str(model), "--manifest", str(manifest), "--protocol-version", str(SPANDREL_PROTOCOL_VERSION))


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise SpandrelProtocolError(f"runner inspection field {name} must be an object")
    return value


def _integer(value: object, name: str, *, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise SpandrelProtocolError(f"runner inspection field {name} must be an integer of at least {minimum}")
    return value


def _string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise SpandrelProtocolError(f"runner inspection field {name} must be a non-empty string")
    return value


def _file_identity(value: object) -> FileIdentity:
    document = _mapping(value, "model_identity")
    expected = {"path", "device", "inode", "size_bytes", "modified_ns", "sha256"}
    if set(document) != expected:
        raise SpandrelProtocolError("runner inspection model_identity has unsupported fields")
    raw_path = _string(document["path"], "model_identity.path")
    path = Path(raw_path)
    if not path.is_absolute():
        raise SpandrelProtocolError("runner inspection model_identity.path must be absolute")
    digest = _string(document["sha256"], "model_identity.sha256")
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise SpandrelProtocolError("runner inspection model_identity.sha256 must be a lowercase SHA-256 digest")
    return FileIdentity(
        path=path.resolve(strict=False),
        device=_integer(document["device"], "model_identity.device", minimum=0),
        inode=_integer(document["inode"], "model_identity.inode", minimum=0),
        size_bytes=_integer(document["size_bytes"], "model_identity.size_bytes"),
        modified_ns=_integer(document["modified_ns"], "model_identity.modified_ns", minimum=0),
        sha256=digest,
    )


def parse_spandrel_inspection(output: str, *, expected_model: Path, expected_scale: int) -> SpandrelInspection:
    """Decode and validate the exact runner protocol used by preflight."""

    try:
        value = json.loads(output)
    except json.JSONDecodeError as error:
        raise SpandrelProtocolError("Spandrel runner returned invalid inspection JSON") from error
    document = _mapping(value, "root")
    expected_fields = {
        "protocol_version",
        "runner_version",
        "model_identity",
        "architecture",
        "purpose",
        "input_channels",
        "output_channels",
        "scale",
        "size_requirements",
        "maximum_input_pixels",
        "device",
        "precision",
    }
    if set(document) != expected_fields:
        raise SpandrelProtocolError("Spandrel runner inspection has unsupported fields")
    protocol = _integer(document["protocol_version"], "protocol_version")
    if protocol != SPANDREL_PROTOCOL_VERSION:
        raise SpandrelProtocolError(f"Spandrel runner protocol {protocol} is unsupported; expected {SPANDREL_PROTOCOL_VERSION}")
    identity = _file_identity(document["model_identity"])
    if identity.path != expected_model.expanduser().resolve(strict=False):
        raise SpandrelProtocolError("Spandrel runner resolved a different model path")
    purpose = _string(document["purpose"], "purpose").upper()
    input_channels = _integer(document["input_channels"], "input_channels")
    output_channels = _integer(document["output_channels"], "output_channels")
    scale = _integer(document["scale"], "scale")
    if purpose != "SR" or input_channels != 3 or output_channels != 3 or scale != expected_scale:
        raise SpandrelProtocolError(f"Spandrel model must describe RGB {expected_scale}x super-resolution")
    requirements = _mapping(document["size_requirements"], "size_requirements")
    if set(requirements) != {"minimum", "multiple_of", "square"} or not isinstance(requirements["square"], bool):
        raise SpandrelProtocolError("Spandrel runner returned invalid size requirements")
    device = _string(document["device"], "device")
    precision = _string(document["precision"], "precision")
    if device != "mps":
        raise SpandrelProtocolError("Spandrel runner must use MPS without CPU fallback")
    if precision not in SUPPORTED_PRECISIONS:
        raise SpandrelProtocolError(f"Spandrel runner reported unsupported precision {precision!r}; expected one of {', '.join(SUPPORTED_PRECISIONS)}")
    return SpandrelInspection(
        protocol_version=protocol,
        runner_version=_string(document["runner_version"], "runner_version"),
        model_identity=identity,
        architecture=_string(document["architecture"], "architecture"),
        purpose=purpose,
        input_channels=input_channels,
        output_channels=output_channels,
        scale=scale,
        minimum_size=_integer(requirements["minimum"], "size_requirements.minimum", minimum=0),
        multiple_of=_integer(requirements["multiple_of"], "size_requirements.multiple_of"),
        square=requirements["square"],
        maximum_input_pixels=_integer(document["maximum_input_pixels"], "maximum_input_pixels"),
        device=device,
        precision=precision,
    )


def dimensions_satisfy(inspection: SpandrelInspection, width: int, height: int) -> bool:
    """Apply the runner-declared direct-inference size gates exactly."""

    if width <= 0 or height <= 0 or width * height > inspection.maximum_input_pixels:
        return False
    if width < inspection.minimum_size or height < inspection.minimum_size:
        return False
    if width % inspection.multiple_of or height % inspection.multiple_of:
        return False
    return not inspection.square or width == height


def spandrel_failure_summary(stderr_tail: str) -> str | None:
    """Return the runner's last stable error record as `code: message`, if any."""

    for line in reversed(stderr_tail.splitlines()):
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict) and record.get("event") == "error" and isinstance(record.get("code"), str) and isinstance(record.get("message"), str):
            return f"{record['code']}: {record['message']}"
    return None
