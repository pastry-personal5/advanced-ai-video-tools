"""Build a deterministic execution plan or return actionable blocking issues."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal, ROUND_CEILING
from fractions import Fraction
from pathlib import Path

from ai_video_tools.core.models import (
    ConcatStrategy,
    IssueCode,
    IssueSeverity,
    JobPlan,
    JobRequest,
    MediaProbe,
    PreflightIssue,
    PreflightReport,
    Rational,
    Toolchain,
    VideoStream,
)
from ai_video_tools.storage.naming import OutputCollisionError, OutputPathRegistry
from ai_video_tools.storage.paths import job_cache_directory
from ai_video_tools.system.platform import PlatformInfo, platform_error
from ai_video_tools.system.tools import ToolDiscovery, ToolDiscoveryError
from ai_video_tools.upscaling.realesrgan import select_ai_scale
from ai_video_tools.video.compatibility import analyze_clip_compatibility, effective_frame_rate
from ai_video_tools.video.policy import has_ambiguous_color_tags, has_unsupported_sdr_tags, is_hdr_or_wide_gamut
from ai_video_tools.video.probe import FFprobeClient, MediaProber, ProbeError

Clock = Callable[[], datetime]
PlatformProvider = Callable[[], PlatformInfo]
ProberFactory = Callable[[Toolchain], MediaProber]
FreeSpaceProvider = Callable[[Path], int]


def _local_now() -> datetime:
    return datetime.now().astimezone()


def _free_bytes(path: Path) -> int:
    candidate = path
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return shutil.disk_usage(candidate).free


def _default_prober(toolchain: Toolchain) -> MediaProber:
    return FFprobeClient(toolchain.ffprobe.path)


def aspect_width(video: VideoStream, target_height: int) -> int:
    """Resolve display width exactly and round to the nearest even integer."""

    raw_width = Fraction(
        target_height * video.width * video.sample_aspect_ratio.numerator,
        video.height * video.sample_aspect_ratio.denominator,
    )
    half_width = raw_width / 2
    rounded_half = (2 * half_width.numerator + half_width.denominator) // (2 * half_width.denominator)
    return max(2, 2 * rounded_half)


def _issue(
    severity: IssueSeverity,
    code: IssueCode,
    message: str,
    path: Path | None = None,
) -> PreflightIssue:
    return PreflightIssue(severity=severity, code=code, message=message, path=path)


class PreflightService:
    """Validate host, tools, destinations, and probed media before processing."""

    def __init__(
        self,
        *,
        registry: OutputPathRegistry | None = None,
        tool_discovery: ToolDiscovery | None = None,
        platform_provider: PlatformProvider = PlatformInfo.current,
        prober_factory: ProberFactory = _default_prober,
        clock: Clock = _local_now,
        workspace_root_provider: Callable[[], Path] = job_cache_directory,
        free_space_provider: FreeSpaceProvider = _free_bytes,
    ) -> None:
        self._registry = registry or OutputPathRegistry()
        self._tool_discovery = tool_discovery or ToolDiscovery()
        self._platform_provider = platform_provider
        self._prober_factory = prober_factory
        self._clock = clock
        self._workspace_root_provider = workspace_root_provider
        self._free_space_provider = free_space_provider

    @property
    def registry(self) -> OutputPathRegistry:
        """Expose reservation ownership to the eventual job runner."""

        return self._registry

    def run(self, request: JobRequest) -> PreflightReport:
        """Return a frozen plan only when every safety gate passes."""

        # This method deliberately reads as the ordered preflight workflow.
        # Splitting its small orchestration branches would obscure phase ownership.
        # pylint: disable=too-many-branches,too-many-statements

        created_at = self._clock()
        issues: list[PreflightIssue] = []
        probes: list[MediaProbe] = []
        reserved_output: Path | None = None

        host_error = platform_error(self._platform_provider())
        if host_error:
            issues.append(
                _issue(
                    IssueSeverity.ERROR,
                    IssueCode.UNSUPPORTED_PLATFORM,
                    host_error,
                )
            )
        self._validate_request(request, issues)
        output_path = self._reserve_output(request, created_at, issues)
        if output_path is not None:
            reserved_output = output_path

        toolchain: Toolchain | None = None
        try:
            toolchain = self._tool_discovery.discover(request.tools)
        except ToolDiscoveryError as error:
            error_text = str(error)
            if "model directory" in error_text:
                code = IssueCode.MISSING_MODEL
            elif "failed" in error_text or "could not launch" in error_text or "could not run" in error_text:
                code = IssueCode.TOOL_FAILED
            else:
                code = IssueCode.MISSING_TOOL
            issues.append(_issue(IssueSeverity.ERROR, code, str(error)))

        inputs_valid = not any(issue.code is IssueCode.INVALID_INPUT for issue in issues)
        if toolchain is not None and inputs_valid:
            prober = self._prober_factory(toolchain)
            for path in request.inputs:
                try:
                    probes.append(prober.probe(path))
                except ProbeError as error:
                    issues.append(
                        _issue(
                            IssueSeverity.ERROR,
                            IssueCode.INVALID_MEDIA,
                            str(error),
                            path,
                        )
                    )

        output_rate: Rational | None = None
        output_width: int | None = None
        ai_scale: int | None = None
        output_audio_layout: str | None = None
        normalization_reasons: tuple[str, ...] = ()
        peak_bytes = 0
        required_bytes = 0
        if len(probes) == len(request.inputs) and probes:
            output_rate = self._validate_media(probes, request, issues)
            output_audio_layout = self._resolve_audio_layout(probes, issues)
            first_video = probes[0].primary_video
            if first_video is not None and output_rate is not None and request.target_height > 0:
                output_width = aspect_width(first_video, request.target_height)
                ai_scale = select_ai_scale(first_video.height, request.target_height)
                if ai_scale == 4 and first_video.height * ai_scale < request.target_height:
                    issues.append(
                        _issue(
                            IssueSeverity.WARNING,
                            IssueCode.UPSCALE_LIMIT,
                            "A 4x AI pass cannot reach the target height; final FFmpeg scaling will add conventional enlargement.",
                            probes[0].path,
                        )
                    )
                normalization_reasons = self._normalization_reasons(probes, output_rate, output_audio_layout)
                for reason in normalization_reasons:
                    issues.append(
                        _issue(
                            IssueSeverity.WARNING,
                            IssueCode.NORMALIZATION_REQUIRED,
                            reason,
                        )
                    )
                peak_bytes = self._estimate_peak_bytes(probes, first_video, output_rate, ai_scale)
                required_bytes = (peak_bytes * 6 + 4) // 5
                try:
                    free_bytes = self._free_space_provider(self._workspace_root_provider())
                except OSError as error:
                    issues.append(
                        _issue(
                            IssueSeverity.ERROR,
                            IssueCode.INSUFFICIENT_DISK,
                            f"Could not inspect workspace free space: {error}",
                        )
                    )
                else:
                    if free_bytes < required_bytes:
                        issues.append(
                            _issue(
                                IssueSeverity.ERROR,
                                IssueCode.INSUFFICIENT_DISK,
                                "The workspace needs " f"{required_bytes:,} free bytes (including the 20% " f"margin), but only {free_bytes:,} are available.",
                            )
                        )

        has_errors = any(issue.severity is IssueSeverity.ERROR for issue in issues)
        plan: JobPlan | None = None
        if not has_errors and output_path is not None and output_rate is not None and output_width is not None:
            plan = JobPlan(
                created_at=created_at,
                output_path=output_path,
                generated_output_name=request.explicit_output_path is None,
                probes=tuple(probes),
                output_frame_rate=output_rate,
                output_width=output_width,
                output_height=request.target_height,
                ai_scale=ai_scale,
                concat_strategy=(ConcatStrategy.NORMALIZE if normalization_reasons else ConcatStrategy.STREAM_COPY),
                output_audio_layout=output_audio_layout,
                normalization_reasons=normalization_reasons,
                estimated_peak_bytes=peak_bytes,
                required_free_bytes=required_bytes,
                assume_bt709=request.assume_bt709,
                acknowledge_dropped_streams=request.acknowledge_dropped_streams,
                model_name=request.model_name,
                overwrite_mode=request.overwrite_mode,
            )
        elif reserved_output is not None:
            self._registry.release(reserved_output)
        return PreflightReport(issues=tuple(issues), plan=plan, toolchain=toolchain)

    @staticmethod
    def _validate_request(request: JobRequest, issues: list[PreflightIssue]) -> None:
        if not request.inputs:
            issues.append(
                _issue(
                    IssueSeverity.ERROR,
                    IssueCode.INVALID_INPUT,
                    "At least one input clip is required.",
                )
            )
        for path in request.inputs:
            if not path.is_file() or not os.access(path, os.R_OK):
                issues.append(
                    _issue(
                        IssueSeverity.ERROR,
                        IssueCode.INVALID_INPUT,
                        "Input is not a readable file.",
                        path,
                    )
                )
        if request.target_height <= 0 or request.target_height % 2:
            issues.append(
                _issue(
                    IssueSeverity.ERROR,
                    IssueCode.INVALID_OUTPUT,
                    "Target height must be a positive even integer.",
                )
            )
        if request.model_name != "realesrgan-x4plus":
            issues.append(
                _issue(
                    IssueSeverity.ERROR,
                    IssueCode.INVALID_OUTPUT,
                    "Version 1 supports only the realesrgan-x4plus real-image model.",
                )
            )
        destination_parent = request.explicit_output_path.parent if request.explicit_output_path is not None else request.output_directory
        if not destination_parent.is_dir() or not os.access(destination_parent, os.W_OK):
            issues.append(
                _issue(
                    IssueSeverity.ERROR,
                    IssueCode.INVALID_OUTPUT,
                    "Output directory does not exist or is not writable.",
                    destination_parent,
                )
            )
        if request.explicit_output_path is not None and request.explicit_output_path.suffix.lower() != ".mp4":
            issues.append(
                _issue(
                    IssueSeverity.ERROR,
                    IssueCode.INVALID_OUTPUT,
                    "The explicit output filename must use the .mp4 extension.",
                    request.explicit_output_path,
                )
            )
        if request.explicit_output_path is not None:
            destination = request.explicit_output_path.resolve(strict=False)
            if any(path.resolve(strict=False) == destination for path in request.inputs):
                issues.append(
                    _issue(
                        IssueSeverity.ERROR,
                        IssueCode.INVALID_OUTPUT,
                        "The output destination cannot be one of the input clips.",
                        request.explicit_output_path,
                    )
                )

    def _reserve_output(
        self,
        request: JobRequest,
        created_at: datetime,
        issues: list[PreflightIssue],
    ) -> Path | None:
        if any(issue.code is IssueCode.INVALID_OUTPUT for issue in issues):
            return None
        try:
            if request.explicit_output_path is not None:
                return self._registry.reserve_explicit(request.explicit_output_path, request.overwrite_mode)
            return self._registry.reserve_generated(request.output_directory, created_at)
        except OutputCollisionError as error:
            issues.append(
                _issue(
                    IssueSeverity.ERROR,
                    IssueCode.INVALID_OUTPUT,
                    str(error),
                    request.explicit_output_path,
                )
            )
            return None

    @staticmethod
    def _validate_media(
        probes: list[MediaProbe],
        request: JobRequest,
        issues: list[PreflightIssue],
    ) -> Rational | None:
        # Keeping all per-input rejection gates together makes the media policy
        # auditable against the architecture document.
        # pylint: disable=too-many-branches
        for probe in probes:
            video = probe.primary_video
            if video is None:
                issues.append(
                    _issue(
                        IssueSeverity.ERROR,
                        IssueCode.INVALID_MEDIA,
                        "Input has no video stream.",
                        probe.path,
                    )
                )
                continue
            if video.rotation:
                issues.append(
                    _issue(
                        IssueSeverity.ERROR,
                        IssueCode.UNSUPPORTED_ROTATION,
                        f"Input declares {video.rotation} degrees of rotation; " "version 1 does not rotate video.",
                        probe.path,
                    )
                )
            detected_hdr = is_hdr_or_wide_gamut(video)
            if detected_hdr:
                issues.append(
                    _issue(
                        IssueSeverity.ERROR,
                        IssueCode.UNSUPPORTED_HDR,
                        "HDR or wide-gamut video is unsupported; version 1 accepts SDR BT.709 only.",
                        probe.path,
                    )
                )
            unsupported_tags = has_unsupported_sdr_tags(video)
            if unsupported_tags and not detected_hdr:
                issues.append(
                    _issue(
                        IssueSeverity.ERROR,
                        IssueCode.UNSUPPORTED_HDR,
                        "Input color tags are not supported by the SDR BT.709 version 1 pipeline.",
                        probe.path,
                    )
                )
            elif has_ambiguous_color_tags(video):
                severity = IssueSeverity.WARNING if request.assume_bt709 else IssueSeverity.ERROR
                action = "Input will be interpreted as SDR BT.709 by acknowledgement." if request.assume_bt709 else "Acknowledge --assume-bt709 to continue."
                issues.append(
                    _issue(
                        severity,
                        IssueCode.AMBIGUOUS_COLOR,
                        f"Input has missing or ambiguous color tags. {action}",
                        probe.path,
                    )
                )
            dropped = []
            if len(probe.video_streams) > 1:
                dropped.append(f"{len(probe.video_streams) - 1} extra video stream(s)")
            if len(probe.audio_streams) > 1:
                dropped.append(f"{len(probe.audio_streams) - 1} extra audio stream(s)")
            if probe.other_streams:
                summary = ", ".join(f"{stream.kind}:{stream.index}" for stream in probe.other_streams)
                dropped.append(f"unsupported streams [{summary}]")
            if probe.chapter_count:
                dropped.append(f"{probe.chapter_count} chapter(s)")
            if dropped:
                severity = IssueSeverity.WARNING if request.acknowledge_dropped_streams else IssueSeverity.ERROR
                action = "They will be dropped by acknowledgement." if request.acknowledge_dropped_streams else "Acknowledge dropped streams to continue."
                issues.append(
                    _issue(
                        severity,
                        IssueCode.STREAM_ACKNOWLEDGEMENT,
                        f"Input contains {', '.join(dropped)}. {action}",
                        probe.path,
                    )
                )
            if probe.duration is None or probe.duration <= 0:
                issues.append(
                    _issue(
                        IssueSeverity.ERROR,
                        IssueCode.INVALID_MEDIA,
                        "Input duration is missing or non-positive.",
                        probe.path,
                    )
                )
        first_video = probes[0].primary_video
        if first_video is None:
            return None
        rate, _ = effective_frame_rate(first_video)
        if rate is None:
            issues.append(
                _issue(
                    IssueSeverity.ERROR,
                    IssueCode.INVALID_MEDIA,
                    "The first clip has no valid rational frame rate.",
                    probes[0].path,
                )
            )
        return rate

    @staticmethod
    def _resolve_audio_layout(probes: list[MediaProbe], issues: list[PreflightIssue]) -> str | None:
        audios = [probe.primary_audio for probe in probes if probe.primary_audio is not None]
        if not audios:
            return None
        declared = next((audio.channel_layout for audio in audios if audio.channel_layout), None)
        if declared:
            return declared
        channel_count = next((audio.channels for audio in audios if audio.channels is not None), None)
        inferred = {1: "mono", 2: "stereo"}.get(channel_count)
        if inferred:
            return inferred
        issues.append(
            _issue(
                IssueSeverity.ERROR,
                IssueCode.INVALID_MEDIA,
                "Audio exists but no supported channel layout can be selected.",
            )
        )
        return None

    @staticmethod
    def _normalization_reasons(probes: list[MediaProbe], output_rate: Rational, output_audio_layout: str | None) -> tuple[str, ...]:
        report = analyze_clip_compatibility(probes, output_rate, output_audio_layout)
        return tuple(finding.message for finding in report.findings)

    @staticmethod
    def _estimate_peak_bytes(
        probes: list[MediaProbe],
        video: VideoStream,
        output_rate: Rational,
        ai_scale: int | None,
    ) -> int:
        duration = sum((probe.duration or Decimal(0) for probe in probes), Decimal(0))
        frames_decimal = duration * Decimal(output_rate.numerator) / Decimal(output_rate.denominator)
        frame_count = int(frames_decimal.to_integral_value(rounding=ROUND_CEILING))
        source_frame = video.width * video.height * 3
        extracted_and_normalized = frame_count * source_frame * 2
        upscaled = frame_count * source_frame * ai_scale * ai_scale if ai_scale else 0
        source_files = sum(probe.path.stat().st_size for probe in probes if probe.path.exists())
        final_working_allowance = frame_count * source_frame // 10
        return source_files + extracted_and_normalized + upscaled + final_working_allowance
