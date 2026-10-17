"""Build a deterministic execution plan or return actionable blocking issues."""

from __future__ import annotations

import math
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
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
    NativeScale,
    PipelineStage,
    PreflightIssue,
    PreflightReport,
    Rational,
    ProcessingPipeline,
    Toolchain,
    UpscaleBackend,
    UpscalePassPlan,
    VideoStream,
)
from advanced_ai_video_tools.services.progress import ProgressCallback, ProgressEmitter
from advanced_ai_video_tools.storage.naming import OutputCollisionError, OutputPathRegistry, automatic_output_basename_matches
from advanced_ai_video_tools.storage.paths import job_cache_directory
from advanced_ai_video_tools.system.platform import PlatformInfo, platform_error
from advanced_ai_video_tools.system.tools import ModelCompatibilityError, ToolDiscovery, ToolDiscoveryError
from advanced_ai_video_tools.system.spandrel import dimensions_satisfy
from advanced_ai_video_tools.upscaling.realesrgan import select_ai_scale
from advanced_ai_video_tools.video.compatibility import analyze_clip_compatibility, effective_frame_rate
from advanced_ai_video_tools.video.policy import color_profile, color_profiles_compatible, has_unsupported_sdr_tags, is_hdr_or_wide_gamut, resolve_input_color_profile
from advanced_ai_video_tools.video.probe import FFprobeClient, MediaProber, ProbeError

Clock = Callable[[], datetime]
PlatformProvider = Callable[[], PlatformInfo]
ProberFactory = Callable[[Toolchain], MediaProber]
FreeSpaceProvider = Callable[[Path], int]
DeviceProvider = Callable[[Path], int]


@dataclass(frozen=True)
class _PassSpec:
    """Backend and exact coded dimensions before dependency resolution."""

    backend: UpscaleBackend
    scale: int
    input_width: int
    input_height: int

    @property
    def output_width(self) -> int:
        """Return the exact coded width produced by this pass."""

        return self.input_width * self.scale

    @property
    def output_height(self) -> int:
        """Return the exact coded height produced by this pass."""

        return self.input_height * self.scale


_CONCAT_SUFFIXES = frozenset({".mp4", ".mov"})


def _output_suffix(request: JobRequest) -> str:
    """Return the only suffix a job may publish: the first clip's for concat only, otherwise MP4."""

    if request.pipeline is ProcessingPipeline.CONCAT and request.inputs and request.inputs[0].suffix.lower() in _CONCAT_SUFFIXES:
        return request.inputs[0].suffix.lower()
    return ".mp4"


def _local_now() -> datetime:
    return datetime.now().astimezone()


def _free_bytes(path: Path) -> int:
    candidate = path
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return shutil.disk_usage(candidate).free


def _device_of(path: Path) -> int:
    """Return the filesystem device of the nearest existing ancestor."""

    candidate = path
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate.stat().st_dev


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
        device_provider: DeviceProvider = _device_of,
    ) -> None:
        self._registry = registry or OutputPathRegistry()
        self._tool_discovery = tool_discovery or ToolDiscovery()
        self._platform_provider = platform_provider
        self._prober_factory = prober_factory
        self._clock = clock
        self._workspace_root_provider = workspace_root_provider
        self._free_space_provider = free_space_provider
        self._device_provider = device_provider

    @property
    def registry(self) -> OutputPathRegistry:
        """Expose reservation ownership to the eventual job runner."""

        return self._registry

    def execute_preflight(self, request: JobRequest, progress: ProgressCallback | None = None) -> PreflightReport:
        """Return a frozen plan only when every safety gate passes."""

        # This method deliberately reads as the ordered preflight workflow.
        # Splitting its small orchestration branches would obscure phase ownership.
        # pylint: disable=too-many-branches,too-many-statements,too-many-nested-blocks

        created_at = request.created_at or self._clock()
        issues: list[PreflightIssue] = []
        probes: list[MediaProbe] = []
        reserved_output: Path | None = None

        ProgressEmitter.emit(progress, PipelineStage.VALIDATE, 0, 1, "Validating the job request and external tools")

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
            toolchain = self._tool_discovery.discover_media(request.tools)
            if request.pipeline is ProcessingPipeline.AUTO:
                # Auto keeps its v2 contract: Real-ESRGAN is proven before probing, even when the plan later skips AI.
                toolchain = self._tool_discovery.complete_for_passes(request.tools, toolchain, require_realesrgan=True)
        except ToolDiscoveryError as error:
            toolchain = None
            issues.append(self._tool_issue(error))

        ProgressEmitter.emit(progress, PipelineStage.VALIDATE, 1, 1, "Completed job request and external-tool validation")

        inputs_valid = not any(issue.code is IssueCode.INVALID_INPUT for issue in issues)
        if toolchain is not None and inputs_valid:
            prober = self._prober_factory(toolchain)
            probe_total = len(request.inputs)
            ProgressEmitter.emit(progress, PipelineStage.PROBE, 0, probe_total, f"Probing {probe_total} input clip{'s' if probe_total != 1 else ''}")
            for input_index, input_path in enumerate(request.inputs, start=1):
                try:
                    probes.append(prober.probe(input_path))
                except ProbeError as error:
                    issues.append(
                        _issue(
                            IssueSeverity.ERROR,
                            IssueCode.INVALID_MEDIA,
                            str(error),
                            input_path,
                        )
                    )
                ProgressEmitter.emit(progress, PipelineStage.PROBE, input_index, probe_total, f"Probed input clip {input_index} of {probe_total}")
        else:
            ProgressEmitter.emit(progress, PipelineStage.PROBE, 0, 0, "Media probing skipped because validation did not resolve runnable inputs and tools")

        output_rate: Rational | None = None
        output_width: int | None = None
        output_height: int | None = None
        ai_scale: int | None = None
        pass_specs: tuple[_PassSpec, ...] = ()
        passes: tuple[UpscalePassPlan, ...] = ()
        output_audio_layout: str | None = None
        output_color_profile: ColorProfile | None = None
        normalization_reasons: tuple[str, ...] = ()
        peak_bytes = 0
        required_bytes = 0
        if len(probes) == len(request.inputs) and probes:
            output_rate = self._validate_media(probes, request, issues)
            output_audio_layout = self._resolve_audio_layout(probes, issues)
            first_video = probes[0].primary_video
            if first_video is not None and output_rate is not None:
                try:
                    videos = tuple(probe.primary_video for probe in probes)
                    if any(video is None for video in videos):
                        raise ValueError("input has no video stream")
                    output_color_profile = resolve_input_color_profile(
                        [video for video in videos if video is not None],
                        allow_mixed_color_tags=request.allow_mixed_color_tags,
                    )
                except ValueError:
                    output_color_profile = None
                normalization_reasons = self._normalization_reasons(probes, output_rate, output_audio_layout)
                height_is_valid = request.pipeline in {ProcessingPipeline.CONCAT, ProcessingPipeline.NATIVE} or (request.target_height > 0 and request.target_height % 2 == 0)
                if height_is_valid:
                    output_width, output_height, pass_specs = self._resolve_pipeline(request, probes, first_video, issues)
                    ai_scale = math.prod(spec.scale for spec in pass_specs) if pass_specs else None
                reason_severity = IssueSeverity.ERROR if request.pipeline is ProcessingPipeline.CONCAT else IssueSeverity.WARNING
                for reason in normalization_reasons:
                    issues.append(_issue(reason_severity, IssueCode.NORMALIZATION_REQUIRED, reason))
                if toolchain is not None and output_width is not None and output_height is not None:
                    toolchain = self._resolve_pass_tools(request, toolchain, pass_specs, issues)
                    passes = self._freeze_passes(pass_specs, toolchain, issues)
                workspace_bytes, final_bytes = self._estimate_bytes(probes, first_video, output_rate, pass_specs, request.pipeline)
                peak_bytes = workspace_bytes + final_bytes
                required_bytes = (peak_bytes * 6 + 4) // 5
                self._validate_free_space(output_path, workspace_bytes, final_bytes, issues)

        has_errors = any(issue.severity is IssueSeverity.ERROR for issue in issues)
        plan: JobPlan | None = None
        plan_values_ready = all(
            value is not None
            for value in (
                output_path,
                output_rate,
                output_width,
                output_height,
                output_color_profile,
                toolchain,
            )
        )
        if not has_errors and plan_values_ready:
            assert output_path is not None
            assert output_rate is not None
            assert output_width is not None
            assert output_height is not None
            assert output_color_profile is not None
            assert toolchain is not None
            plan = JobPlan(
                created_at=created_at,
                output_path=output_path,
                generated_output_name=request.explicit_output_path is None,
                probes=tuple(probes),
                output_frame_rate=output_rate,
                output_width=output_width,
                output_height=output_height,
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
                allow_mixed_color_tags=request.allow_mixed_color_tags,
                pipeline=request.pipeline,
                native_scale=request.native_scale,
                upscale_passes=passes,
            )
        elif reserved_output is not None:
            self._registry.release(reserved_output)
        return PreflightReport(issues=tuple(issues), plan=plan, toolchain=toolchain)

    def _resolve_pass_tools(self, request: JobRequest, toolchain: Toolchain, specs: tuple[_PassSpec, ...], issues: list[PreflightIssue]) -> Toolchain:
        """Resolve only the AI prerequisites the planned passes execute."""

        if not specs or request.pipeline is ProcessingPipeline.AUTO:
            return toolchain
        scales = tuple(spec.scale for spec in specs if spec.backend is UpscaleBackend.SPANDREL)
        try:
            resolved = self._tool_discovery.complete_for_passes(request.tools, toolchain, require_realesrgan=any(spec.backend is UpscaleBackend.REALESRGAN for spec in specs), spandrel_scales=scales)
        except ToolDiscoveryError as error:
            issues.append(self._tool_issue(error))
            return toolchain
        recorded = {inspection.scale: inspection for inspection in request.spandrel_inspections}
        current = {inspection.scale: inspection for inspection in resolved.spandrel_inspections}
        for scale in scales:
            if recorded and recorded.get(scale) != current.get(scale):
                issues.append(_issue(IssueSeverity.ERROR, IssueCode.MODEL_CHANGED, f"The selected Spandrel {scale}x model changed after it was reviewed."))
        return resolved

    @staticmethod
    def _tool_issue(error: ToolDiscoveryError) -> PreflightIssue:
        error_text = str(error)
        if isinstance(error, ModelCompatibilityError):
            code = IssueCode.INCOMPATIBLE_MODEL
        elif "failed" in error_text or "could not launch" in error_text or "could not run" in error_text:
            code = IssueCode.TOOL_FAILED
        elif "model" in error_text.casefold():
            code = IssueCode.MISSING_MODEL
        else:
            code = IssueCode.MISSING_TOOL
        return _issue(IssueSeverity.ERROR, code, error_text)

    def _resolve_pipeline(
        self,
        request: JobRequest,
        probes: list[MediaProbe],
        video: VideoStream,
        issues: list[PreflightIssue],
    ) -> tuple[int | None, int | None, tuple[_PassSpec, ...]]:
        """Resolve final display dimensions and every exact coded AI pass."""

        # Each return is one user-visible pipeline policy outcome.
        # pylint: disable=too-many-return-statements

        pipeline = request.pipeline
        if pipeline is ProcessingPipeline.CONCAT:
            self._validate_concat_inputs(probes, request, issues)
            return video.width, video.height, ()
        if pipeline is ProcessingPipeline.NATIVE:
            if request.native_scale is None:
                return None, None, ()
            scale = int(request.native_scale)
            height = video.height * scale
            if height % 2:
                issues.append(_issue(IssueSeverity.ERROR, IssueCode.INCOMPATIBLE_PIPELINE, f"A native {scale}x pass on a {video.height}-pixel-tall source gives an odd {height}-pixel height that yuv420p cannot encode. Choose a resize pipeline or another scale.", probes[0].path))
                return None, None, ()
            backend = UpscaleBackend.REALESRGAN if scale == 4 else UpscaleBackend.SPANDREL
            return aspect_width(video, height), height, (_PassSpec(backend, scale, video.width, video.height),)

        output_width = aspect_width(video, request.target_height)
        if pipeline is ProcessingPipeline.AUTO:
            selected_scale = select_ai_scale(video.height, request.target_height)
            if selected_scale == 4 and video.height * selected_scale < request.target_height:
                issues.append(_issue(IssueSeverity.WARNING, IssueCode.UPSCALE_LIMIT, "A 4x AI pass cannot reach the target height; final FFmpeg scaling will add conventional enlargement.", probes[0].path))
            specs = (_PassSpec(UpscaleBackend.REALESRGAN, selected_scale, video.width, video.height),) if selected_scale is not None else ()
            return output_width, request.target_height, specs
        if video.height >= request.target_height:
            return output_width, request.target_height, ()
        if pipeline is ProcessingPipeline.FOUR_X_RESIZE:
            if request.target_height > video.height * 4:
                issues.append(_issue(IssueSeverity.ERROR, IssueCode.UPSCALE_LIMIT, f"Desired height {request.target_height} exceeds this pipeline's native 4x result ({video.height * 4}).", probes[0].path))
                return output_width, request.target_height, ()
            return output_width, request.target_height, (_PassSpec(UpscaleBackend.REALESRGAN, 4, video.width, video.height),)
        if request.target_height > video.height * 6:
            issues.append(_issue(IssueSeverity.ERROR, IssueCode.UPSCALE_LIMIT, f"Desired height {request.target_height} exceeds this pipeline's native 6x result ({video.height * 6}).", probes[0].path))
            return output_width, request.target_height, ()
        first = _PassSpec(UpscaleBackend.SPANDREL, 2, video.width, video.height)
        second = _PassSpec(UpscaleBackend.SPANDREL, 3, first.output_width, first.output_height)
        return output_width, request.target_height, (first, second)

    @staticmethod
    def _validate_concat_inputs(probes: list[MediaProbe], request: JobRequest, issues: list[PreflightIssue]) -> None:
        """Apply the direct-copy container and codec allowlists before launch."""

        quicktime_family = frozenset({"mov", "mp4", "m4a", "3gp", "3g2", "mj2"})
        for probe in probes:
            if probe.path.suffix.lower() in _CONCAT_SUFFIXES and not quicktime_family.intersection(probe.format_names):
                issues.append(_issue(IssueSeverity.ERROR, IssueCode.INCOMPATIBLE_PIPELINE, "Concat only accepts .mp4 or .mov inputs probed as QuickTime/ISO base media.", probe.path))
        suffix = _output_suffix(request)
        video_codecs = {".mp4": frozenset({"h264", "hevc", "mpeg4", "av1"}), ".mov": frozenset({"h264", "hevc", "mpeg4", "prores", "mjpeg", "dnxhd"})}.get(suffix, frozenset())
        audio_codecs = {".mp4": frozenset({"aac", "alac", "mp3", "ac3", "eac3"}), ".mov": frozenset({"aac", "alac", "mp3", "ac3", "eac3", "pcm_s16le", "pcm_s24le", "pcm_s32le"})}.get(suffix, frozenset())
        for probe in probes:
            video = probe.primary_video
            audio = probe.primary_audio
            if video is not None and video.codec_name not in video_codecs:
                issues.append(_issue(IssueSeverity.ERROR, IssueCode.INCOMPATIBLE_PIPELINE, f"{video.codec_name} video cannot be stream-copied into the selected {suffix} output.", probe.path))
            if audio is not None and audio.codec_name not in audio_codecs:
                issues.append(_issue(IssueSeverity.ERROR, IssueCode.INCOMPATIBLE_PIPELINE, f"{audio.codec_name} audio cannot be stream-copied into the selected {suffix} output.", probe.path))
        if request.explicit_output_path is not None and request.explicit_output_path.suffix.lower() != suffix:
            issues.append(_issue(IssueSeverity.ERROR, IssueCode.INVALID_OUTPUT, f"Concat-only output must use the first clip's {suffix} suffix.", request.explicit_output_path))

    @staticmethod
    def _freeze_passes(specs: tuple[_PassSpec, ...], toolchain: Toolchain, issues: list[PreflightIssue]) -> tuple[UpscalePassPlan, ...]:
        """Bind resolved executables, models, descriptors, and dimensions."""

        frozen: list[UpscalePassPlan] = []
        inspections = {inspection.scale: inspection for inspection in toolchain.spandrel_inspections}
        for index, spec in enumerate(specs, start=1):
            if spec.backend is UpscaleBackend.REALESRGAN:
                if toolchain.realesrgan is None or toolchain.model_directory is None:
                    issues.append(_issue(IssueSeverity.ERROR, IssueCode.MISSING_TOOL, "Real-ESRGAN prerequisites were not resolved for the planned pass."))
                    continue
                frozen.append(UpscalePassPlan(index, spec.backend, spec.scale, spec.input_width, spec.input_height, spec.output_width, spec.output_height, toolchain.realesrgan.path, toolchain.model_directory))
                continue
            inspection = inspections.get(spec.scale)
            if toolchain.spandrel_runner is None or inspection is None:
                issues.append(_issue(IssueSeverity.ERROR, IssueCode.MISSING_MODEL, f"Spandrel {spec.scale}x prerequisites were not resolved for pass {index}."))
                continue
            if not dimensions_satisfy(inspection, spec.input_width, spec.input_height):
                issues.append(_issue(IssueSeverity.ERROR, IssueCode.INCOMPATIBLE_MODEL, f"Pass {index} input {spec.input_width}x{spec.input_height} does not meet the {spec.scale}x model size requirements or {inspection.maximum_input_pixels:,}-pixel limit.", inspection.model_identity.path))
                continue
            frozen.append(
                UpscalePassPlan(
                    index,
                    spec.backend,
                    spec.scale,
                    spec.input_width,
                    spec.input_height,
                    spec.output_width,
                    spec.output_height,
                    toolchain.spandrel_runner.path,
                    inspection.model_identity.path,
                    inspection.model_identity,
                    inspection,
                )
            )
        return tuple(frozen)

    def _validate_free_space(self, output: Path | None, workspace_bytes: int, final_bytes: int, issues: list[PreflightIssue]) -> None:
        """Check the workspace and, when it is a different filesystem, the destination separately."""

        destination = output.parent if output is not None else None
        try:
            workspace_root = self._workspace_root_provider()
            separate = destination is not None and self._device_provider(workspace_root) != self._device_provider(destination)
        except OSError as error:
            issues.append(_issue(IssueSeverity.ERROR, IssueCode.INSUFFICIENT_DISK, f"Could not inspect destination free space: {error}", destination))
            return
        # Only the final partial is written beside the destination; everything else lives in the workspace.
        workspace_required = (workspace_bytes * 6 + 4) // 5 if separate else ((workspace_bytes + final_bytes) * 6 + 4) // 5
        checks = [("workspace", workspace_root, workspace_required)]
        if separate and destination is not None:
            checks.append(("destination", destination, (final_bytes * 6 + 4) // 5))
        for name, location, required in checks:
            try:
                available = self._free_space_provider(location)
            except OSError as error:
                issues.append(_issue(IssueSeverity.ERROR, IssueCode.INSUFFICIENT_DISK, f"Could not inspect {name} free space: {error}", location))
                continue
            if available < required:
                issues.append(_issue(IssueSeverity.ERROR, IssueCode.INSUFFICIENT_DISK, f"The {name} needs {required:,} free bytes (including the 20% margin), but only {available:,} are available.", location))

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
        if request.pipeline in {ProcessingPipeline.AUTO, ProcessingPipeline.FOUR_X_RESIZE, ProcessingPipeline.TWO_X_THREE_X_RESIZE} and (request.target_height <= 0 or request.target_height % 2):
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
            elif request.created_at is None or not automatic_output_basename_matches(request.generated_output_basename, request.created_at, _output_suffix(request)):
                issues.append(_issue(IssueSeverity.ERROR, IssueCode.INVALID_OUTPUT, "Frozen generated output basename does not match the job creation identity."))
        if request.model_name != "realesrgan-x4plus":
            issues.append(
                _issue(
                    IssueSeverity.ERROR,
                    IssueCode.INVALID_OUTPUT,
                    "Version 1 supports only the realesrgan-x4plus real-image model.",
                )
            )
        if not isinstance(request.pipeline, ProcessingPipeline):
            issues.append(_issue(IssueSeverity.ERROR, IssueCode.INVALID_OUTPUT, "Processing pipeline is invalid."))
        if request.pipeline is ProcessingPipeline.NATIVE:
            if request.native_scale not in {NativeScale.TWO, NativeScale.THREE, NativeScale.FOUR}:
                issues.append(_issue(IssueSeverity.ERROR, IssueCode.INVALID_OUTPUT, "Native upscale requires a 2x, 3x, or 4x scale."))
        elif request.native_scale is not None:
            issues.append(_issue(IssueSeverity.ERROR, IssueCode.INVALID_OUTPUT, "Native scale is valid only for the native pipeline."))
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
        if request.pipeline is ProcessingPipeline.CONCAT:
            for path in request.inputs:
                if path.suffix.lower() not in _CONCAT_SUFFIXES:
                    issues.append(_issue(IssueSeverity.ERROR, IssueCode.INCOMPATIBLE_PIPELINE, "Concat only accepts .mp4 or .mov inputs.", path))
        allowed_suffix = _output_suffix(request)
        if request.explicit_output_path is not None and request.explicit_output_path.suffix.lower() != allowed_suffix:
            issues.append(
                _issue(
                    IssueSeverity.ERROR,
                    IssueCode.INVALID_OUTPUT,
                    f"The explicit output filename must use the {allowed_suffix} extension.",
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
            return self._registry.reserve_generated(request.output_directory, created_at, _output_suffix(request))
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
            if comparison_profile is not None and not detected_hdr and not unsupported_tags:
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
        valid_videos = [probe.primary_video for probe in probes if probe.primary_video is not None]
        if len(valid_videos) == len(probes):
            try:
                resolve_input_color_profile(valid_videos, allow_mixed_color_tags=request.allow_mixed_color_tags)
            except ValueError as error:
                issues.append(
                    _issue(
                        IssueSeverity.ERROR,
                        IssueCode.UNSUPPORTED_COLOR,
                        f"Input color tags cannot form one frozen SDR profile: {error}. Enable mixed color tags only when untagged clips are known to match the declared SDR profile.",
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
    def _estimate_bytes(
        probes: list[MediaProbe],
        video: VideoStream,
        output_rate: Rational,
        passes: tuple[_PassSpec, ...],
        pipeline: ProcessingPipeline,
    ) -> tuple[int, int]:
        """Return conservative (workspace, final-partial) byte estimates before the 20% margin."""

        source_files = sum(probe.path.stat().st_size for probe in probes if probe.path.exists())
        if pipeline is ProcessingPipeline.CONCAT:
            # A stream copy writes only its partial beside the destination plus a tiny manifest.
            return 1024 * 1024, source_files
        duration = sum((probe.duration or Decimal(0) for probe in probes), Decimal(0))
        frames_decimal = duration * Decimal(output_rate.numerator) / Decimal(output_rate.denominator)
        frame_count = int(frames_decimal.to_integral_value(rounding=ROUND_CEILING))
        source_frame = video.width * video.height * 3
        extracted_and_normalized = frame_count * source_frame * 2
        upscaled = frame_count * sum(spec.output_width * spec.output_height * 3 for spec in passes)
        final_partial = frame_count * source_frame // 10
        return source_files + extracted_and_normalized + upscaled, final_partial
