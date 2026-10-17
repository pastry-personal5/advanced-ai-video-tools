"""Behavioral tests for deterministic, dependency-injected preflight."""

import re
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from advanced_ai_video_tools.core.models import (
    AudioStream,
    ColorMatrix,
    ColorProfile,
    ConcatStrategy,
    FileIdentity,
    IssueCode,
    IssueSeverity,
    JobRequest,
    MediaProbe,
    NativeScale,
    OtherStream,
    OverwriteMode,
    PipelineStage,
    ProgressEvent,
    ProcessingPipeline,
    Rational,
    ToolInfo,
    Toolchain,
    SpandrelInspection,
    UpscaleBackend,
    VideoStream,
)
from advanced_ai_video_tools.services.preflight import PreflightService, aspect_width
from advanced_ai_video_tools.storage.naming import automatic_output_basename
from advanced_ai_video_tools.system.platform import PlatformInfo
from advanced_ai_video_tools.system.tools import ModelCompatibilityError, ToolDiscoveryError
from advanced_ai_video_tools.video.probe import MediaProber
from tests.static_discovery import Completion, StaticToolDiscovery


class FakeProber(MediaProber):
    """Look up media facts by input path."""

    def __init__(self, probes: dict[Path, MediaProbe]) -> None:
        self.probes = probes

    def probe(self, path: Path) -> MediaProbe:
        """Return the prepared probe result."""

        return self.probes[path]


def _video(**changes: object) -> VideoStream:
    values: dict[str, object] = {
        "index": 0,
        "codec_name": "h264",
        "width": 1920,
        "height": 1080,
        "pixel_format": "yuv420p",
        "sample_aspect_ratio": Rational(1, 1),
        "real_frame_rate": Rational(30000, 1001),
        "average_frame_rate": Rational(30000, 1001),
        "time_base": Rational(1, 30000),
        "duration": Decimal("1"),
        "color_space": "bt709",
        "color_transfer": "bt709",
        "color_primaries": "bt709",
        "color_range": "tv",
        "rotation": 0,
        "has_hdr_metadata": False,
    }
    values.update(changes)
    return VideoStream(**values)  # type: ignore[arg-type]


def _probe(path: Path, **changes: object) -> MediaProbe:
    values: dict[str, object] = {
        "path": path,
        "duration": Decimal("1"),
        "video_streams": (_video(),),
        "audio_streams": (),
        "other_streams": (),
        "chapter_count": 0,
    }
    values.update(changes)
    return MediaProbe(**values)  # type: ignore[arg-type]


def _service(
    tmp_path: Path,
    probes: dict[Path, MediaProbe],
    *,
    free_bytes: int = 10**15,
) -> PreflightService:
    executable = ToolInfo(tmp_path / "tool", "version 1")
    toolchain = Toolchain(executable, executable, executable, tmp_path / "models")
    prober = FakeProber(probes)
    return PreflightService(
        tool_discovery=StaticToolDiscovery(toolchain),
        platform_provider=lambda: PlatformInfo("Darwin", "arm64", "26.5.2"),
        prober_factory=lambda _tools: prober,
        clock=lambda: datetime(
            2026,
            8,
            21,
            14,
            30,
            52,
            123456,
            tzinfo=timezone(timedelta(hours=9)),
        ),
        workspace_root_provider=lambda: tmp_path,
        free_space_provider=lambda _path: free_bytes,
    )


def _service_with_toolchain(tmp_path: Path, probes: dict[Path, MediaProbe], toolchain: Toolchain, discovery: StaticToolDiscovery | None = None) -> PreflightService:
    prober = FakeProber(probes)
    return PreflightService(
        tool_discovery=discovery or StaticToolDiscovery(toolchain),
        platform_provider=lambda: PlatformInfo("Darwin", "arm64", "26.5.2"),
        prober_factory=lambda _tools: prober,
        clock=lambda: datetime(2026, 8, 21, 14, 30, 52, tzinfo=timezone.utc),
        workspace_root_provider=lambda: tmp_path,
        free_space_provider=lambda _path: 10**15,
    )


def _input(tmp_path: Path, name: str = "clip.mp4") -> Path:
    path = tmp_path / name
    path.write_bytes(b"small fixture stand-in")
    return path


def test_ready_plan_freezes_name_dimensions_rate_and_scale(tmp_path: Path) -> None:
    """A valid SDR clip produces all core execution decisions."""

    source = _input(tmp_path)
    service = _service(tmp_path, {source: _probe(source)})

    report = service.execute_preflight(JobRequest((source,), tmp_path))

    assert report.ready
    assert report.plan is not None
    assert re.fullmatch(r"ai-video-20260821-143052-[0-9a-f]{32}\.mp4", report.plan.output_path.name)
    assert (report.plan.output_width, report.plan.output_height) == (3840, 2160)
    assert report.plan.output_frame_rate == Rational(30000, 1001)
    assert report.plan.ai_scale == 2
    assert report.plan.model_name == "realesrgan-x4plus"
    assert report.plan.overwrite_mode is OverwriteMode.REPLACE
    assert report.plan.output_color_profile == ColorProfile(ColorMatrix.BT709, "bt709", "bt709")
    assert report.plan.concat_strategy is ConcatStrategy.STREAM_COPY
    assert report.plan.required_free_bytes >= report.plan.estimated_peak_bytes
    service.registry.release(report.plan.output_path)


def test_preflight_preserves_queue_frozen_creation_identity(tmp_path: Path) -> None:
    """A delayed queued job keeps its submission timestamp and UUIDv7 basename."""

    source = _input(tmp_path)
    service = _service(tmp_path, {source: _probe(source)})
    created = datetime(2026, 7, 4, 9, 8, 7, 654321, tzinfo=timezone.utc)
    basename = automatic_output_basename(created)

    report = service.execute_preflight(JobRequest((source,), tmp_path, created_at=created, generated_output_basename=basename))

    assert report.ready
    assert report.plan is not None
    assert report.plan.created_at == created
    assert report.plan.output_path.name == basename
    service.registry.release(report.plan.output_path)


def test_frozen_generated_destination_that_appears_before_start_is_rejected(tmp_path: Path) -> None:
    """An external collision cannot make a delayed generated job overwrite a file."""

    source = _input(tmp_path)
    service = _service(tmp_path, {source: _probe(source)})
    created = datetime(2026, 7, 4, 9, 8, 7, 654321, tzinfo=timezone.utc)
    basename = automatic_output_basename(created)
    (tmp_path / basename).touch()

    report = service.execute_preflight(JobRequest((source,), tmp_path, created_at=created, generated_output_basename=basename))

    assert not report.ready
    assert report.plan is None
    assert any(issue.code is IssueCode.INVALID_OUTPUT and "no longer available" in issue.message for issue in report.issues)


def test_preflight_reports_measured_validation_and_probe_progress(tmp_path: Path) -> None:
    """Frontends can render validation and per-input probe progress."""

    first = _input(tmp_path, "first.mp4")
    second = _input(tmp_path, "second.mp4")
    service = _service(tmp_path, {first: _probe(first), second: _probe(second)})
    events: list[ProgressEvent] = []

    report = service.execute_preflight(JobRequest((first, second), tmp_path), progress=events.append)

    assert report.ready and report.plan is not None
    assert [(event.stage, event.completed, event.total) for event in events] == [
        (PipelineStage.VALIDATE, 0, 1),
        (PipelineStage.VALIDATE, 1, 1),
        (PipelineStage.PROBE, 0, 2),
        (PipelineStage.PROBE, 1, 2),
        (PipelineStage.PROBE, 2, 2),
    ]
    service.registry.release(report.plan.output_path)


def test_aspect_width_uses_sample_aspect_ratio_and_even_rounding() -> None:
    """Display aspect, not coded aspect alone, determines final width."""

    video = _video(width=720, height=576, sample_aspect_ratio=Rational(16, 15))
    assert aspect_width(video, 2160) == 2880


def test_nonpositive_target_height_is_a_validation_issue_not_an_exception(tmp_path: Path) -> None:
    """Strict scale policy remains behind the user-facing request validator."""

    source = _input(tmp_path)
    report = _service(tmp_path, {source: _probe(source)}).execute_preflight(JobRequest((source,), tmp_path, target_height=0))

    assert not report.ready
    assert any(issue.code is IssueCode.INVALID_OUTPUT and "Target height" in issue.message for issue in report.issues)


@pytest.mark.parametrize(
    ("video", "code"),
    [
        (_video(color_transfer="smpte2084"), IssueCode.UNSUPPORTED_HDR),
        (_video(rotation=90), IssueCode.UNSUPPORTED_ROTATION),
    ],
)
def test_hdr_and_rotation_are_hard_failures(tmp_path: Path, video: VideoStream, code: IssueCode) -> None:
    """Unsupported image interpretation is rejected, never normalized silently."""

    source = _input(tmp_path)
    report = _service(tmp_path, {source: _probe(source, video_streams=(video,))}).execute_preflight(JobRequest((source,), tmp_path))

    assert not report.ready
    assert code in {issue.code for issue in report.issues}


def test_missing_transfer_and_primaries_default_to_srgb_transfer_and_bt709_primaries(tmp_path: Path) -> None:
    """Absent transfer and primaries are tagged iec61966-2-1 and bt709."""

    source = _input(tmp_path)
    media = _probe(source, video_streams=(_video(color_transfer=None, color_primaries=None),))
    service = _service(tmp_path, {source: media})

    report = service.execute_preflight(JobRequest((source,), tmp_path))

    assert report.ready and report.plan is not None
    assert report.plan.output_color_profile == ColorProfile(ColorMatrix.BT709, "iec61966-2-1", "bt709")
    assert report.plan.concat_strategy is ConcatStrategy.NORMALIZE
    service.registry.release(report.plan.output_path)


@pytest.mark.parametrize("missing_field", ["color_space", "color_range"])
def test_missing_matrix_or_range_defaults_to_bt709_limited(tmp_path: Path, missing_field: str) -> None:
    """Untagged matrix and range fall back to the BT.709 matrix and limited range."""

    source = _input(tmp_path)
    media = _probe(source, video_streams=(_video(color_transfer=None, color_primaries=None, **{missing_field: None}),))
    report = _service(tmp_path, {source: media}).execute_preflight(JobRequest((source,), tmp_path))

    assert report.ready
    assert report.plan is not None
    expected = ColorMatrix.BT709
    assert report.plan.output_color_profile == ColorProfile(expected, "iec61966-2-1", "bt709")


def test_first_clip_smpte170m_matrix_is_preserved_as_output_profile(tmp_path: Path) -> None:
    """An explicit SMPTE 170M first clip freezes SMPTE 170M output."""

    source = _input(tmp_path)
    smpte170m = _probe(source, video_streams=(_video(color_space="smpte170m"),))
    service = _service(tmp_path, {source: smpte170m})

    report = service.execute_preflight(JobRequest((source,), tmp_path))

    assert report.ready and report.plan is not None
    assert report.plan.output_color_profile == ColorProfile(ColorMatrix.SMPTE170M, "bt709", "bt709")
    assert report.plan.concat_strategy is ConcatStrategy.STREAM_COPY
    service.registry.release(report.plan.output_path)


def test_color_profile_different_from_first_clip_is_rejected(tmp_path: Path) -> None:
    """Mixed BT.709 and SMPTE 170M jobs never enter conversion."""

    first = _input(tmp_path, "first.mov")
    second = _input(tmp_path, "second.mov")
    probes = {first: _probe(first, video_streams=(_video(color_space="smpte170m"),)), second: _probe(second)}

    report = _service(tmp_path, probes).execute_preflight(JobRequest((first, second), tmp_path))

    assert not report.ready
    issue = next(issue for issue in report.issues if issue.code is IssueCode.UNSUPPORTED_COLOR)
    assert "explicitly conflicts with another clip" in issue.message


def test_mixed_missing_and_declared_tags_require_explicit_opt_in(tmp_path: Path) -> None:
    """Strict preflight never produces a plan normalization will reject."""

    first = _input(tmp_path, "first.mov")
    missing = _input(tmp_path, "missing.mov")
    conflicting = _input(tmp_path, "conflicting.mov")
    conflicting_again = _input(tmp_path, "conflicting-again.mov")
    accepted_probes = {first: _probe(first), missing: _probe(missing, video_streams=(_video(color_transfer=None),))}
    accepted_service = _service(tmp_path, accepted_probes)

    strict = accepted_service.execute_preflight(JobRequest((first, missing), tmp_path))
    accepted = accepted_service.execute_preflight(JobRequest((first, missing), tmp_path, allow_mixed_color_tags=True))
    rejected_probes = {
        first: _probe(first, video_streams=(_video(color_transfer=None),)),
        conflicting: _probe(conflicting),
        conflicting_again: _probe(conflicting_again, video_streams=(_video(color_transfer="smpte170m"),)),
    }
    rejected = _service(tmp_path, rejected_probes).execute_preflight(JobRequest((first, conflicting, conflicting_again), tmp_path))

    assert not strict.ready
    assert any(issue.code is IssueCode.UNSUPPORTED_COLOR for issue in strict.issues)
    assert accepted.ready and accepted.plan is not None
    assert accepted.plan.output_color_profile == ColorProfile(ColorMatrix.BT709, "bt709", "bt709")
    assert accepted.plan.concat_strategy is ConcatStrategy.NORMALIZE
    accepted_service.registry.release(accepted.plan.output_path)
    assert not rejected.ready
    assert any(issue.code is IssueCode.UNSUPPORTED_COLOR and "explicitly conflicts" in issue.message for issue in rejected.issues)


def test_other_explicit_sdr_matrices_remain_unsupported(tmp_path: Path) -> None:
    """The design expansion is limited to SMPTE 170M rather than arbitrary matrices."""

    source = _input(tmp_path)
    report = _service(tmp_path, {source: _probe(source, video_streams=(_video(color_space="fcc"),))}).execute_preflight(JobRequest((source,), tmp_path))

    assert not report.ready
    assert any(issue.code is IssueCode.UNSUPPORTED_COLOR for issue in report.issues)


def test_secondary_streams_require_acknowledgement(tmp_path: Path) -> None:
    """Unsupported streams are inventoried before an intentional drop."""

    source = _input(tmp_path)
    audio = AudioStream(1, "aac", 48000, 2, "stereo", Decimal("1"))
    media = _probe(
        source,
        audio_streams=(audio, audio),
        other_streams=(OtherStream(3, "subtitle", "mov_text"),),
        chapter_count=1,
    )
    service = _service(tmp_path, {source: media})

    rejected = service.execute_preflight(JobRequest((source,), tmp_path))
    accepted = service.execute_preflight(JobRequest((source,), tmp_path, acknowledge_dropped_streams=True))
    rejected_issue = next(item for item in rejected.issues if item.code is IssueCode.STREAM_ACKNOWLEDGEMENT)
    assert rejected_issue.acknowledgement_key is not None
    bound = service.execute_preflight(JobRequest((source,), tmp_path, acknowledge_dropped_streams=True, acknowledged_stream_keys=(rejected_issue.acknowledgement_key,)))

    assert not rejected.ready
    assert accepted.ready
    assert bound.ready
    issue = next(item for item in accepted.issues if item.code is IssueCode.STREAM_ACKNOWLEDGEMENT)
    assert "extra audio" in issue.message
    assert "subtitle:3" in issue.message
    assert accepted.plan is not None
    assert accepted.plan.output_audio_layout == "stereo"
    service.registry.release(accepted.plan.output_path)
    assert bound.plan is not None
    service.registry.release(bound.plan.output_path)

    changed_media = _probe(source, audio_streams=(audio, audio), other_streams=(OtherStream(3, "subtitle", "mov_text"),), chapter_count=2)
    changed = _service(tmp_path, {source: changed_media}).execute_preflight(JobRequest((source,), tmp_path, acknowledge_dropped_streams=True, acknowledged_stream_keys=(rejected_issue.acknowledgement_key,)))
    assert not changed.ready
    changed_issue = next(item for item in changed.issues if item.code is IssueCode.STREAM_ACKNOWLEDGEMENT)
    assert changed_issue.severity is IssueSeverity.ERROR
    assert "inventory changed" in changed_issue.message


def test_vfr_uses_exact_average_rate_and_forces_normalization(tmp_path: Path) -> None:
    """VFR timing chooses avg_frame_rate exactly and visibly normalizes."""

    source = _input(tmp_path)
    video = _video(
        real_frame_rate=Rational(30, 1),
        average_frame_rate=Rational(30000, 1001),
    )
    service = _service(tmp_path, {source: _probe(source, video_streams=(video,))})

    report = service.execute_preflight(JobRequest((source,), tmp_path))

    assert report.ready
    assert report.plan is not None
    assert report.plan.output_frame_rate == Rational(30000, 1001)
    assert any("frame timing" in reason for reason in report.plan.normalization_reasons)
    assert report.plan.concat_strategy is ConcatStrategy.NORMALIZE
    service.registry.release(report.plan.output_path)


def test_quantized_sixteen_fps_is_recognized_as_cfr(tmp_path: Path) -> None:
    """Alternating source ticks preserve the nominal 16/1 rate."""

    source = _input(tmp_path)
    video = _video(real_frame_rate=Rational(16, 1), average_frame_rate=Rational(48600, 3037), time_base=Rational(1, 600))
    service = _service(tmp_path, {source: _probe(source, video_streams=(video,))})

    report = service.execute_preflight(JobRequest((source,), tmp_path))

    assert report.ready and report.plan is not None
    assert report.plan.output_frame_rate == Rational(16, 1)
    assert report.plan.concat_strategy is ConcatStrategy.STREAM_COPY
    assert not any("frame timing" in reason for reason in report.plan.normalization_reasons)
    service.registry.release(report.plan.output_path)


def test_disk_estimate_requires_twenty_percent_margin(tmp_path: Path) -> None:
    """Insufficient cache volume capacity blocks work before extraction."""

    source = _input(tmp_path)
    report = _service(tmp_path, {source: _probe(source)}, free_bytes=1).execute_preflight(JobRequest((source,), tmp_path))

    assert not report.ready
    assert IssueCode.INSUFFICIENT_DISK in {issue.code for issue in report.issues}


def test_explicit_output_cannot_alias_an_input(tmp_path: Path) -> None:
    """Overwrite mode never permits destruction of a source clip."""

    source = _input(tmp_path)
    report = _service(tmp_path, {source: _probe(source)}).execute_preflight(JobRequest((source,), tmp_path, explicit_output_path=source))

    assert not report.ready
    assert IssueCode.INVALID_OUTPUT in {issue.code for issue in report.issues}


def test_concat_only_ignores_height_freezes_mov_suffix_and_skips_ai(tmp_path: Path) -> None:
    """Concat preserves coded dimensions and the first input container suffix."""

    source = _input(tmp_path, "clip.mov")
    probe = _probe(source, format_names=("mov", "mp4"))
    executable = ToolInfo(tmp_path / "tool", "version")
    service = _service_with_toolchain(tmp_path, {source: probe}, Toolchain(executable, executable, None, None))

    report = service.execute_preflight(JobRequest((source,), tmp_path, target_height=1, pipeline=ProcessingPipeline.CONCAT))

    assert report.ready
    assert report.plan is not None
    assert report.plan.output_path.suffix == ".mov"
    assert (report.plan.output_width, report.plan.output_height) == (1920, 1080)
    assert report.plan.upscale_passes == ()
    service.registry.release(report.plan.output_path)


def test_native_spandrel_and_two_pass_plans_freeze_exact_dimensions(tmp_path: Path) -> None:
    """Native and composed plans bind every model pass and coded dimension."""

    source = _input(tmp_path)
    model_2x = _input(tmp_path, "DAT_x2.safetensors")
    model_3x = _input(tmp_path, "DAT_x3.safetensors")
    runner = ToolInfo(tmp_path / "spandrel-runner", "runner")
    executable = ToolInfo(tmp_path / "tool", "version")

    def inspection(path: Path, scale: int) -> SpandrelInspection:
        stat = path.stat()
        identity = FileIdentity(path.resolve(), stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, "a" * 64)
        return SpandrelInspection(1, "0.4.0", identity, "DAT", "SR", 3, 3, scale, 1, 1, False, 20_000_000, "mps", "float32")

    tools = Toolchain(executable, executable, executable, tmp_path / "models", runner, (inspection(model_2x, 2), inspection(model_3x, 3)))
    service = _service_with_toolchain(tmp_path, {source: _probe(source)}, tools)

    native = service.execute_preflight(JobRequest((source,), tmp_path, target_height=1, pipeline=ProcessingPipeline.NATIVE, native_scale=NativeScale.TWO))
    assert native.ready and native.plan is not None
    assert (native.plan.output_width, native.plan.output_height) == (3840, 2160)
    assert [(item.backend, item.scale, item.input_width, item.output_width) for item in native.plan.upscale_passes] == [(UpscaleBackend.SPANDREL, 2, 1920, 3840)]
    assert native.plan.ai_scale == 2
    service.registry.release(native.plan.output_path)

    two_pass = service.execute_preflight(JobRequest((source,), tmp_path, target_height=2160, pipeline=ProcessingPipeline.TWO_X_THREE_X_RESIZE))
    assert two_pass.ready and two_pass.plan is not None
    assert [(item.scale, item.input_width, item.output_width) for item in two_pass.plan.upscale_passes] == [(2, 1920, 3840), (3, 3840, 11520)]
    assert two_pass.plan.ai_scale == 6
    service.registry.release(two_pass.plan.output_path)


def test_explicit_resize_rejects_height_above_native_result(tmp_path: Path) -> None:
    """Explicit resize pipelines never enlarge beyond their AI pass ceiling."""

    source = _input(tmp_path)
    report = _service(tmp_path, {source: _probe(source)}).execute_preflight(JobRequest((source,), tmp_path, target_height=6482, pipeline=ProcessingPipeline.TWO_X_THREE_X_RESIZE))
    assert not report.ready
    assert any(issue.code is IssueCode.UPSCALE_LIMIT for issue in report.issues)


def _inspection(path: Path, scale: int) -> SpandrelInspection:
    stat = path.stat()
    identity = FileIdentity(path.resolve(), stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, "a" * 64)
    return SpandrelInspection(1, "0.4.0", identity, "DAT", "SR", 3, 3, scale, 1, 1, False, 20_000_000, "mps", "float32")


def _full_toolchain(tmp_path: Path) -> Toolchain:
    executable = ToolInfo(tmp_path / "tool", "version")
    model_2x = _input(tmp_path, "DAT_x2.safetensors")
    model_3x = _input(tmp_path, "DAT_x3.safetensors")
    return Toolchain(executable, executable, executable, tmp_path / "models", ToolInfo(tmp_path / "spandrel-runner", "runner"), (_inspection(model_2x, 2), _inspection(model_3x, 3)))


@pytest.mark.parametrize(
    ("request_changes", "height", "expected"),
    [
        ({"pipeline": ProcessingPipeline.AUTO}, 1080, [Completion(True, ())]),
        ({"pipeline": ProcessingPipeline.AUTO}, 2160, [Completion(True, ())]),
        ({"pipeline": ProcessingPipeline.CONCAT}, 2160, []),
        ({"pipeline": ProcessingPipeline.FOUR_X_RESIZE}, 1080, []),
        ({"pipeline": ProcessingPipeline.FOUR_X_RESIZE}, 2160, [Completion(True, ())]),
        ({"pipeline": ProcessingPipeline.TWO_X_THREE_X_RESIZE}, 1080, []),
        ({"pipeline": ProcessingPipeline.TWO_X_THREE_X_RESIZE}, 2160, [Completion(False, (2, 3))]),
        ({"pipeline": ProcessingPipeline.NATIVE, "native_scale": NativeScale.FOUR}, 1, [Completion(True, ())]),
        ({"pipeline": ProcessingPipeline.NATIVE, "native_scale": NativeScale.THREE}, 1, [Completion(False, (3,))]),
    ],
)
def test_preflight_requests_only_the_ai_tools_the_resolved_path_executes(tmp_path: Path, request_changes: dict[str, object], height: int, expected: list[Completion]) -> None:
    """Auto proves Real-ESRGAN as before; every other path resolves what it will run."""

    source = _input(tmp_path)
    discovery = StaticToolDiscovery(_full_toolchain(tmp_path))
    service = _service_with_toolchain(tmp_path, {source: _probe(source, format_names=("mov", "mp4"))}, discovery.toolchain, discovery)

    report = service.execute_preflight(JobRequest((source,), tmp_path, target_height=height, **request_changes))  # type: ignore[arg-type]

    assert report.ready, report.issues
    assert discovery.completions == expected
    assert discovery.media_requests == 1
    assert report.plan is not None
    service.registry.release(report.plan.output_path)


def test_changed_spandrel_inspection_is_rejected_at_dequeue(tmp_path: Path) -> None:
    """A model replaced after review fails authoritative preflight, never silently runs."""

    source = _input(tmp_path)
    tools = _full_toolchain(tmp_path)
    reviewed = replace(tools.spandrel_inspections[0], runner_version="0.3.9")
    request = JobRequest((source,), tmp_path, pipeline=ProcessingPipeline.NATIVE, native_scale=NativeScale.TWO, spandrel_inspections=(reviewed,))
    report = _service_with_toolchain(tmp_path, {source: _probe(source)}, tools).execute_preflight(request)

    assert not report.ready
    assert IssueCode.MODEL_CHANGED in {issue.code for issue in report.issues}


def test_native_scale_with_an_odd_result_height_is_rejected_before_any_ai_work(tmp_path: Path) -> None:
    """yuv420p cannot encode an odd native height, so the plan fails up front."""

    source = _input(tmp_path)
    probe = _probe(source, video_streams=(_video(width=1920, height=1081),))
    tools = _full_toolchain(tmp_path)
    request = JobRequest((source,), tmp_path, pipeline=ProcessingPipeline.NATIVE, native_scale=NativeScale.THREE)

    report = _service_with_toolchain(tmp_path, {source: probe}, tools).execute_preflight(request)

    assert not report.ready
    odd = [issue for issue in report.issues if issue.code is IssueCode.INCOMPATIBLE_PIPELINE]
    assert odd and "3243" in odd[0].message and "odd" in odd[0].message


def test_concat_with_a_first_clip_that_is_not_mp4_or_mov_is_an_issue_not_a_crash(tmp_path: Path) -> None:
    """An unsupported container cannot reach generated-name reservation."""

    source = _input(tmp_path, "clip.mkv")
    report = _service(tmp_path, {source: _probe(source, format_names=("matroska", "webm"))}).execute_preflight(JobRequest((source,), tmp_path, pipeline=ProcessingPipeline.CONCAT))

    assert not report.ready
    assert IssueCode.INCOMPATIBLE_PIPELINE in {issue.code for issue in report.issues}


class _FailingCompletion(StaticToolDiscovery):
    """Raise one scripted discovery failure while completing pass tools."""

    def __init__(self, toolchain: Toolchain, error: ToolDiscoveryError) -> None:
        super().__init__(toolchain)
        self.error = error

    def complete_for_passes(self, *_args: object, **_kwargs: object) -> Toolchain:
        """Fail like a real model inspection."""

        raise self.error


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (ModelCompatibilityError("Spandrel 2x model inspection failed: incompatible_model: not an RGB model"), IssueCode.INCOMPATIBLE_MODEL),
        (ToolDiscoveryError("Spandrel 2x model is not a readable file: /missing.safetensors"), IssueCode.MISSING_MODEL),
        (ToolDiscoveryError("spandrel-runner was not found. Install it or configure its executable path."), IssueCode.MISSING_TOOL),
        (ToolDiscoveryError("Spandrel 2x model inspection could not run: timed out"), IssueCode.TOOL_FAILED),
    ],
)
def test_model_and_runner_failures_get_their_own_issue_codes(tmp_path: Path, error: ToolDiscoveryError, code: IssueCode) -> None:
    """Descriptor failures are not mislabelled as a missing file."""

    source = _input(tmp_path)
    discovery = _FailingCompletion(_full_toolchain(tmp_path), error)
    request = JobRequest((source,), tmp_path, pipeline=ProcessingPipeline.NATIVE, native_scale=NativeScale.TWO)

    report = _service_with_toolchain(tmp_path, {source: _probe(source)}, discovery.toolchain, discovery).execute_preflight(request)

    assert not report.ready
    assert code in {issue.code for issue in report.issues}


@pytest.mark.parametrize(
    "case",
    [
        ("clip.mp4", ("mov", "mp4"), {"codec_name": "prores"}, None, "prores video cannot be stream-copied into the selected .mp4"),
        ("clip.mov", ("mov", "mp4"), {"codec_name": "vp9"}, None, "vp9 video cannot be stream-copied into the selected .mov"),
        ("clip.mp4", ("mov", "mp4"), {}, {"codec_name": "pcm_s16le"}, "pcm_s16le audio cannot be stream-copied into the selected .mp4"),
        ("clip.mov", ("matroska", "webm"), {}, None, "QuickTime/ISO base media"),
    ],
)
def test_concat_only_rejects_codecs_and_containers_the_output_cannot_stream_copy(tmp_path: Path, case: tuple[str, tuple[str, ...], dict[str, object], dict[str, object] | None, str]) -> None:
    """The muxer allowlist is applied per clip before any FFmpeg process starts."""

    name, formats, video, audio, fragment = case
    source = _input(tmp_path, name)
    streams: dict[str, object] = {"video_streams": (_video(**video),), "format_names": formats}
    if audio is not None:
        streams["audio_streams"] = (AudioStream(1, audio["codec_name"], 48000, 2, "stereo", Decimal("1"), Decimal("0")),)  # type: ignore[arg-type]
    report = _service(tmp_path, {source: _probe(source, **streams)}).execute_preflight(JobRequest((source,), tmp_path, pipeline=ProcessingPipeline.CONCAT))

    assert not report.ready
    assert any(issue.code is IssueCode.INCOMPATIBLE_PIPELINE and fragment in issue.message for issue in report.issues)


def test_concat_only_turns_every_normalization_reason_into_a_blocking_error(tmp_path: Path) -> None:
    """Timing or frame-rate differences are reported verbatim, never silently normalized."""

    first, second = _input(tmp_path, "a.mp4"), _input(tmp_path, "b.mp4")
    slower = _video(real_frame_rate=Rational(24, 1), average_frame_rate=Rational(24, 1), time_base=Rational(1, 24000))
    probes = {first: _probe(first, format_names=("mov", "mp4")), second: _probe(second, format_names=("mov", "mp4"), video_streams=(slower,))}
    report = _service(tmp_path, probes).execute_preflight(JobRequest((first, second), tmp_path, pipeline=ProcessingPipeline.CONCAT))

    blocking = [issue for issue in report.issues if issue.code is IssueCode.NORMALIZATION_REQUIRED]
    assert not report.ready and blocking and all(issue.severity is IssueSeverity.ERROR for issue in blocking)


@pytest.mark.parametrize(
    ("changes", "fragment"),
    [
        ({"maximum_input_pixels": 1920 * 1080 - 1}, "-pixel limit"),
        ({"multiple_of": 7}, "size requirements"),
        ({"minimum_size": 4000}, "size requirements"),
        ({"square": True}, "size requirements"),
    ],
)
def test_spandrel_pass_inputs_must_satisfy_the_runner_published_size_gates(tmp_path: Path, changes: dict[str, object], fragment: str) -> None:
    """Direct inference is never padded, cropped, or tiled to fit; preflight refuses the pass."""

    source = _input(tmp_path)
    tools = _full_toolchain(tmp_path)
    limited = replace(tools.spandrel_inspections[0], **changes)
    tools = replace(tools, spandrel_inspections=(limited, tools.spandrel_inspections[1]))
    request = JobRequest((source,), tmp_path, pipeline=ProcessingPipeline.NATIVE, native_scale=NativeScale.TWO)

    report = _service_with_toolchain(tmp_path, {source: _probe(source)}, tools).execute_preflight(request)

    assert not report.ready
    assert any(issue.code is IssueCode.INCOMPATIBLE_MODEL and fragment in issue.message for issue in report.issues)


def _two_filesystem_service(tmp_path: Path, probes: dict[Path, MediaProbe], destination: Path, destination_free: int) -> PreflightService:
    """Treat everything under `destination` as a separate filesystem with its own free space."""

    def free(path: Path) -> int:
        return destination_free if destination in (path, *path.parents) else 10**15

    return PreflightService(
        tool_discovery=StaticToolDiscovery(Toolchain(ToolInfo(tmp_path / "tool", "v"), ToolInfo(tmp_path / "tool", "v"), ToolInfo(tmp_path / "tool", "v"), tmp_path / "models")),
        platform_provider=lambda: PlatformInfo("Darwin", "arm64", "26.5.2"),
        prober_factory=lambda _tools: FakeProber(probes),
        clock=lambda: datetime(2026, 8, 21, 14, 30, 52, tzinfo=timezone.utc),
        workspace_root_provider=lambda: tmp_path,
        free_space_provider=free,
        device_provider=lambda path: 2 if destination in (path, *path.parents) else 1,
    )


def test_a_separate_destination_filesystem_needs_room_for_the_final_partial_not_the_whole_workspace(tmp_path: Path) -> None:
    """Only the final output is written on the destination, so it is not charged the workspace peak."""

    source = _input(tmp_path)
    destination = tmp_path / "external"
    destination.mkdir()
    probe = _probe(source, duration=Decimal("60"))
    request = JobRequest((source,), destination, target_height=2160)
    baseline = _service(tmp_path, {source: probe}).execute_preflight(request)
    assert baseline.plan is not None
    tmp_service = _service(tmp_path, {source: probe})
    tmp_service.registry.release(baseline.plan.output_path)
    workspace_requirement = baseline.plan.required_free_bytes

    roomy = _two_filesystem_service(tmp_path, {source: probe}, destination, destination_free=workspace_requirement // 4)
    accepted = roomy.execute_preflight(request)
    assert accepted.ready, accepted.issues
    assert accepted.plan is not None
    roomy.registry.release(accepted.plan.output_path)

    cramped = _two_filesystem_service(tmp_path, {source: probe}, destination, destination_free=1024)
    rejected = cramped.execute_preflight(request)
    assert not rejected.ready
    assert any(issue.code is IssueCode.INSUFFICIENT_DISK and "destination" in issue.message for issue in rejected.issues)


def test_disk_estimate_sizes_the_final_partial_from_resolved_output_dimensions(tmp_path: Path) -> None:
    """A larger final encode must not be priced as though it retained the source resolution."""

    source = _input(tmp_path)
    video = _video(width=640, height=360, duration=Decimal("2"))
    probe = _probe(source, duration=Decimal("2"), video_streams=(video,))

    _workspace_bytes, final_bytes = PreflightService._estimate_bytes(  # pylint: disable=protected-access
        [probe],
        video,
        Rational(10, 1),
        (),
        ProcessingPipeline.AUTO,
        output_width=3840,
        output_height=2160,
    )

    assert final_bytes == 20 * 3840 * 2160 * 3 // 10
