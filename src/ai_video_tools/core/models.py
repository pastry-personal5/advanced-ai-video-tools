"""Typed, frontend-independent models used by the processing pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from fractions import Fraction
from math import gcd
from pathlib import Path


class JobState(str, Enum):
    """Lifecycle states for a queued processing job."""

    QUEUED = "queued"
    VALIDATING = "validating"
    RUNNING = "running"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    FAILED = "failed"
    COMPLETED = "completed"


class PipelineStage(str, Enum):
    """Observable processing stages shared by the CLI and GUI."""

    VALIDATE = "validate"
    PROBE = "probe"
    CONCATENATE = "concatenate"
    NORMALIZE = "normalize"
    EXTRACT = "extract"
    UPSCALE = "upscale"
    ENCODE = "encode"
    VERIFY = "verify"
    PUBLISH = "publish"
    CLEANUP = "cleanup"


class OverwriteMode(str, Enum):
    """Publication behavior for an explicitly selected destination."""

    REPLACE = "replace"
    NO_OVERWRITE = "no_overwrite"


class ConcatStrategy(str, Enum):
    """Preflight-selected approach for producing one merged timeline."""

    STREAM_COPY = "stream_copy"
    NORMALIZE = "normalize"


class ColorMatrix(str, Enum):
    """Explicit SDR matrices supported without cross-matrix conversion."""

    BT709 = "bt709"
    SMPTE170M = "smpte170m"


class IssueSeverity(str, Enum):
    """Severity of a preflight finding."""

    WARNING = "warning"
    ERROR = "error"


class IssueCode(str, Enum):
    """Stable codes suitable for GUI and CLI error mapping."""

    UNSUPPORTED_PLATFORM = "unsupported_platform"
    MISSING_TOOL = "missing_tool"
    TOOL_FAILED = "tool_failed"
    MISSING_MODEL = "missing_model"
    INVALID_INPUT = "invalid_input"
    INVALID_OUTPUT = "invalid_output"
    INVALID_MEDIA = "invalid_media"
    UNSUPPORTED_HDR = "unsupported_hdr"
    UNSUPPORTED_COLOR = "unsupported_color"
    AMBIGUOUS_COLOR = "ambiguous_color"
    UNSUPPORTED_ROTATION = "unsupported_rotation"
    STREAM_ACKNOWLEDGEMENT = "stream_acknowledgement"
    NORMALIZATION_REQUIRED = "normalization_required"
    INSUFFICIENT_DISK = "insufficient_disk"
    UPSCALE_LIMIT = "upscale_limit"


@dataclass(frozen=True, order=True)
class Rational:
    """Normalized exact rational used for rates and sample aspect ratios."""

    numerator: int
    denominator: int

    def __post_init__(self) -> None:
        if self.denominator == 0:
            raise ValueError("rational denominator cannot be zero")
        numerator = self.numerator
        denominator = self.denominator
        if denominator < 0:
            numerator = -numerator
            denominator = -denominator
        divisor = gcd(numerator, denominator)
        object.__setattr__(self, "numerator", numerator // divisor)
        object.__setattr__(self, "denominator", denominator // divisor)

    @classmethod
    def parse(cls, value: str) -> Rational:
        """Parse an FFprobe rational using slash or colon notation."""

        separator = "/" if "/" in value else ":"
        parts = value.split(separator)
        if len(parts) != 2:
            raise ValueError(f"invalid rational: {value!r}")
        return cls(int(parts[0]), int(parts[1]))

    @property
    def positive(self) -> bool:
        """Whether this rational is greater than zero."""

        return self.numerator > 0

    def as_fraction(self) -> Fraction:
        """Return the standard-library exact representation."""

        return Fraction(self.numerator, self.denominator)

    def __str__(self) -> str:
        return f"{self.numerator}/{self.denominator}"


@dataclass(frozen=True)
class ColorProfile:
    """Matrix plus optional transfer and primary signaling from the first clip."""

    matrix: ColorMatrix
    transfer: str | None
    primaries: str | None


@dataclass(frozen=True)
class VideoStream:
    """Relevant FFprobe fields for one video stream."""

    index: int
    codec_name: str
    width: int
    height: int
    pixel_format: str | None
    sample_aspect_ratio: Rational
    real_frame_rate: Rational | None
    average_frame_rate: Rational | None
    time_base: Rational | None
    duration: Decimal | None
    color_space: str | None
    color_transfer: str | None
    color_primaries: str | None
    color_range: str | None
    rotation: int
    has_hdr_metadata: bool
    start_time: Decimal | None = None


@dataclass(frozen=True)
class AudioStream:
    """Relevant FFprobe fields for one audio stream."""

    index: int
    codec_name: str
    sample_rate: int | None
    channels: int | None
    channel_layout: str | None
    duration: Decimal | None
    time_base: Rational | None = None
    start_time: Decimal | None = None


@dataclass(frozen=True)
class OtherStream:
    """A stream v1 cannot preserve."""

    index: int
    kind: str
    codec_name: str


@dataclass(frozen=True)
class MediaProbe:
    """Typed media inventory returned by FFprobe."""

    path: Path
    duration: Decimal | None
    video_streams: tuple[VideoStream, ...]
    audio_streams: tuple[AudioStream, ...]
    other_streams: tuple[OtherStream, ...]
    chapter_count: int = 0
    start_time: Decimal | None = None

    @property
    def primary_video(self) -> VideoStream | None:
        """Return the lowest-index video stream, if present."""

        return min(self.video_streams, key=lambda stream: stream.index) if self.video_streams else None

    @property
    def primary_audio(self) -> AudioStream | None:
        """Return the lowest-index audio stream, if present."""

        return min(self.audio_streams, key=lambda stream: stream.index) if self.audio_streams else None


@dataclass(frozen=True)
class ToolInfo:
    """Resolved executable and its diagnostic version text."""

    path: Path
    version: str


@dataclass(frozen=True)
class Toolchain:
    """All external prerequisites frozen for one job."""

    ffmpeg: ToolInfo
    ffprobe: ToolInfo
    realesrgan: ToolInfo
    model_directory: Path


@dataclass(frozen=True)
class ToolOverrides:
    """Optional user-selected locations, resolved before PATH entries."""

    ffmpeg: Path | None = None
    ffprobe: Path | None = None
    realesrgan: Path | None = None
    model_directory: Path | None = None


@dataclass(frozen=True)
class JobRequest:
    """Immutable user intent shared by every frontend."""

    inputs: tuple[Path, ...]
    output_directory: Path
    explicit_output_path: Path | None = None
    target_height: int = 2160
    model_name: str = "realesrgan-x4plus"
    acknowledge_dropped_streams: bool = False
    overwrite_mode: OverwriteMode = OverwriteMode.REPLACE
    tools: ToolOverrides = field(default_factory=ToolOverrides)


@dataclass(frozen=True)
class PreflightIssue:
    """One actionable preflight result."""

    severity: IssueSeverity
    code: IssueCode
    message: str
    path: Path | None = None


@dataclass(frozen=True)
class JobPlan:
    """Frozen decisions required to execute a validated job."""

    created_at: datetime
    output_path: Path
    generated_output_name: bool
    probes: tuple[MediaProbe, ...]
    output_frame_rate: Rational
    output_width: int
    output_height: int
    ai_scale: int | None
    concat_strategy: ConcatStrategy
    output_audio_layout: str | None
    normalization_reasons: tuple[str, ...]
    estimated_peak_bytes: int
    required_free_bytes: int
    output_color_profile: ColorProfile
    acknowledge_dropped_streams: bool = False
    model_name: str = "realesrgan-x4plus"
    overwrite_mode: OverwriteMode = OverwriteMode.REPLACE


@dataclass(frozen=True)
class PreflightReport:
    """Full validation result, including warnings and an optional runnable plan."""

    issues: tuple[PreflightIssue, ...]
    plan: JobPlan | None
    toolchain: Toolchain | None

    @property
    def ready(self) -> bool:
        """Whether no blocking issue remains and a plan was produced."""

        return self.plan is not None and not any(issue.severity is IssueSeverity.ERROR for issue in self.issues)


@dataclass(frozen=True)
class ProgressEvent:
    """Measured stage progress shared by non-GUI and future GUI callers."""

    stage: PipelineStage
    completed: int
    total: int | None
    message: str

    def __post_init__(self) -> None:
        if self.completed < 0:
            raise ValueError("completed progress cannot be negative")
        if self.total is not None and (self.total < 0 or self.completed > self.total):
            raise ValueError("completed progress must be within the measured total")
