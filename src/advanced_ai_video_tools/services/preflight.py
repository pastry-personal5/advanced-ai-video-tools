"""Build a deterministic execution plan or return actionable blocking issues."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal, ROUND_CEILING
from fractions import Fraction
from hashlib import sha256
from pathlib import Path

from advanced_ai_video_tools.core.models import (
    ColorProfile,
    ConcatStrategy,
    IssueCode,
    IssueSeverity,
    JobPlan,
    JobRequest,
    MediaProbe,
    PipelineStage,
    PreflightIssue,
    PreflightReport,
    ProgressEvent,
    Rational,
    Toolchain,
    VideoStream,
)
from advanced_ai_video_tools.storage.naming import OutputCollisionError, OutputPathRegistry, automatic_output_basename_matches
from advanced_ai_video_tools.storage.paths import job_cache_directory
from advanced_ai_video_tools.system.platform import PlatformInfo, platform_error
from advanced_ai_video_tools.system.tools import ToolDiscovery, ToolDiscoveryError
from advanced_ai_video_tools.upscaling.realesrgan import select_ai_scale
from advanced_ai_video_tools.video.compatibility import analyze_clip_compatibility, effective_frame_rate
from advanced_ai_video_tools.video.policy import color_profile, color_profiles_compatible, has_ambiguous_color_tags, has_unsupported_sdr_tags, is_hdr_or_wide_gamut
from advanced_ai_video_tools.video.probe import FFprobeClient, MediaProber, ProbeError

Clock = Callable[[], datetime]
PlatformProvider = Callable[[], PlatformInfo]
ProberFactory = Callable[[Toolchain], MediaProber]
FreeSpaceProvider = Callable[[Path], int]
ProgressCallback = Callable[[ProgressEvent], None]


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
    acknowledgement_key: str | None = None,
) -> PreflightIssue:
    return PreflightIssue(severity=severity, code=code, message=message, path=path, acknowledgement_key=acknowledgement_key)


def _dropped_stream_inventory(probe: MediaProbe) -> tuple[str, ...]:
    """Describe every unsupported secondary item deterministically."""

    videos = sorted(probe.video_streams, key=lambda item: item.index)
    audios = sorted(probe.audio_streams, key=lambda item: item.index)
    items = [f"extra video stream {stream.index} ({stream.codec_name})" for stream in videos[1:]]
    items.extend(f"extra audio stream {stream.index} ({stream.codec_name})" for stream in audios[1:])
    items.extend(f"{stream.kind}:{stream.index} ({stream.codec_name})" for stream in sorted(probe.other_streams, key=lambda item: (item.kind, item.index)))
    if probe.chapter_count:
        items.append(f"{probe.chapter_count} chapter(s)")
    return tuple(items)


def _stream_acknowledgement_key(probe: MediaProbe, inventory: tuple[str, ...]) -> str:
    """Bind acknowledgement to one path and exact dropped-item inventory."""

    payload = "\0".join((str(probe.path.resolve(strict=False)), *inventory)).encode("utf-8")
    return sha256(payload).hexdigest()


def _comparison_color_profile(probes: list[MediaProbe]) -> ColorProfile | None:
    """Combine declared optional values solely to detect cross-clip conflicts."""

    valid_profiles: list[ColorProfile] = []
    for probe in probes:
        if probe.primary_video is not None:
            try:
                valid_profiles.append(color_profile(probe.primary_video))
            except ValueError:
                pass
    first_video = probes[0].primary_video
    try:
        first_profile = color_profile(first_video) if first_video is not None else None
    except ValueError:
        return None
    if first_profile is None:
        return None
    return ColorProfile(
        first_profile.matrix,
        next((profile.transfer for profile in valid_profiles if profile.transfer is not None), None),
        next((profile.primaries for profile in valid_profiles if profile.primaries is not None), None),
    )


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

    @staticmethod
    def _emit(callback: ProgressCallback | None, stage: PipelineStage, completed: int, total: int, message: str) -> None:
        if callback is not None:
            callback(ProgressEvent(stage, completed, total, message))

    def run(self, request: JobRequest, progress: ProgressCallback | None = None) -> PreflightReport:
        """Return a frozen plan only when every safety gate passes."""

        # This method deliberately reads as the ordered preflight workflow.
        # Splitting its small orchestration branches would obscure phase ownership.
        # pylint: disable=too-many-branches,too-many-statements

        created_at = request.created_at or self._clock()
        issues: list[PreflightIssue] = []
        probes: list[MediaProbe] = []
        reserved_output: Path | None = None

        self._emit(progress, PipelineStage.VALIDATE, 0, 1, "Validating the job request and external tools")

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
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            issues.append(_issue(IssueSeverity.ERROR, IssueCode.INVALID_OUTPUT, "Job creation time must be timezone-aware."))
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

        self._emit(progress, PipelineStage.VALIDATE, 1, 1, "Completed job request and external-tool validation")

        inputs_valid = not any(issue.code is IssueCode.INVALID_INPUT for issue in issues)
        if toolchain is not None and inputs_valid:
            prober = self._prober_factory(toolchain)
            probe_total = len(request.inputs)
            self._emit(progress, PipelineStage.PROBE, 0, probe_total, f"Probing {probe_total} input clip{'s' if probe_total != 1 else ''}")
            for index, path in enumerate(request.inputs, start=1):
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
                self._emit(progress, PipelineStage.PROBE, index, probe_total, f"Probed input clip {index} of {probe_total}")
        else:
            self._emit(progress, PipelineStage.PROBE, 0, 0, "Media probing skipped because validation did not resolve runnable inputs and tools")

        output_rate: Rational | None = None
        output_width: int | None = None
        ai_scale: int | None = None
        output_audio_layout: str | None = None
        output_color_profile: ColorProfile | None = None
        normalization_reasons: tuple[str, ...] = ()
        peak_bytes = 0
        required_bytes = 0
        if len(probes) == len(request.inputs) and probes:
            output_rate = self._validate_media(probes, request, issues)
            output_audio_layout = self._resolve_audio_layout(probes, issues)
            first_video = probes[0].primary_video
            if first_video is not None and output_rate is not None and request.target_height > 0:
                try:
                    output_color_profile = color_profile(first_video)
                except ValueError:
                    output_color_profile = None
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
        if not has_errors and output_path is not None and output_rate is not None and output_width is not None and output_color_profile is not None:
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
                output_color_profile=output_color_profile,
                acknowledge_dropped_streams=request.acknowledge_dropped_streams,
                model_name=request.model_name,
                overwrite_mode=request.overwrite_mode,
            )
        elif reserved_output is not None:
            self._registry.release(reserved_output)
        return PreflightReport(issues=tuple(issues), plan=plan, toolchain=toolchain)

    @staticmethod
    def _validate_request(request: JobRequest, issues: list[PreflightIssue]) -> None:
        # Keeping independent request safety gates together makes omissions visible.
        # pylint: disable=too-many-branches
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
        if request.created_at is not None and (request.created_at.tzinfo is None or request.created_at.utcoffset() is None):
            issues.append(_issue(IssueSeverity.ERROR, IssueCode.INVALID_OUTPUT, "Frozen job creation time must be timezone-aware."))
        if request.generated_output_basename is not None:
            if request.explicit_output_path is not None:
                issues.append(_issue(IssueSeverity.ERROR, IssueCode.INVALID_OUTPUT, "A job cannot have both an explicit output and a generated output basename."))
            elif request.created_at is None or not automatic_output_basename_matches(request.generated_output_basename, request.created_at):
                issues.append(_issue(IssueSeverity.ERROR, IssueCode.INVALID_OUTPUT, "Frozen generated output basename does not match the job creation identity."))
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
            if request.generated_output_basename is not None:
                return self._registry.reserve_frozen_generated(request.output_directory, request.generated_output_basename)
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
        first_video = probes[0].primary_video
        comparison_profile = _comparison_color_profile(probes)
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
                        "HDR or wide-gamut video is unsupported; version 1 accepts only explicit SDR BT.709 or SMPTE 170M profiles.",
                        probe.path,
                    )
                )
            unsupported_tags = has_unsupported_sdr_tags(video)
            if unsupported_tags and not detected_hdr:
                issues.append(
                    _issue(
                        IssueSeverity.ERROR,
                        IssueCode.UNSUPPORTED_COLOR,
                        "Input color tags are not supported by the version 1 SDR input policy.",
                        probe.path,
                    )
                )
            elif has_ambiguous_color_tags(video):
                issues.append(
                    _issue(
                        IssueSeverity.ERROR,
                        IssueCode.AMBIGUOUS_COLOR,
                        "Input color matrix and range must be explicit. Missing transfer characteristics and primaries are accepted without assuming values.",
                        probe.path,
                    )
                )
            if comparison_profile is not None and not detected_hdr and not unsupported_tags and not has_ambiguous_color_tags(video):
                current_profile = color_profile(video)
                if not color_profiles_compatible(current_profile, comparison_profile):
                    issues.append(
                        _issue(
                            IssueSeverity.ERROR,
                            IssueCode.UNSUPPORTED_COLOR,
                            "Input color profile explicitly conflicts with another clip. Mixed matrices or conflicting declared transfer/primary tags are rejected; version 1 performs no cross-profile conversion.",
                            probe.path,
                        )
                    )
            dropped = _dropped_stream_inventory(probe)
            if dropped:
                acknowledgement_key = _stream_acknowledgement_key(probe, dropped)
                bound_keys = frozenset(request.acknowledged_stream_keys)
                acknowledged = request.acknowledge_dropped_streams and (not bound_keys or acknowledgement_key in bound_keys)
                severity = IssueSeverity.WARNING if acknowledged else IssueSeverity.ERROR
                if acknowledged:
                    action = "They will be dropped by acknowledgement."
                elif request.acknowledge_dropped_streams and bound_keys:
                    action = "The dropped-stream inventory changed after acknowledgement; review it again."
                else:
                    action = "Acknowledge dropped streams to continue."
                issues.append(
                    _issue(
                        severity,
                        IssueCode.STREAM_ACKNOWLEDGEMENT,
                        f"Input contains unsupported secondary items [{', '.join(dropped)}]. {action}",
                        probe.path,
                        acknowledgement_key,
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
