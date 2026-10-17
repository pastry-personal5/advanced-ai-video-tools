"""Tests for the concat-only terminal stream-copy branch."""

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from collections.abc import Sequence

from advanced_ai_video_tools.core.models import ColorMatrix, ColorProfile, ConcatStrategy, JobPlan, MediaProbe, ProcessingPipeline, Rational, ToolInfo, Toolchain, VideoStream
from advanced_ai_video_tools.services.concat_only import DirectConcatExecutor
from advanced_ai_video_tools.storage.workspaces import WorkspaceManager
from advanced_ai_video_tools.system.processes import CancellationToken, ProcessResult


def _video() -> VideoStream:
    return VideoStream(0, "h264", 64, 36, "yuv420p", Rational(1, 1), Rational(10, 1), Rational(10, 1), Rational(1, 1000), Decimal("1"), "bt709", "bt709", "bt709", "tv", 0, False)


def test_concat_only_publishes_mov_without_decode_filter_or_encoder(tmp_path: Path) -> None:
    """The terminal MOV branch publishes only a verified stream copy."""

    source = tmp_path / "source.mov"
    source.write_bytes(b"source")
    probe = MediaProbe(source, Decimal("1"), (_video(),), (), (), format_names=("mov", "mp4"))
    output = tmp_path / "output.mov"
    job = JobPlan(
        datetime(2026, 8, 21, tzinfo=timezone.utc),
        output,
        False,
        (probe,),
        Rational(10, 1),
        64,
        36,
        None,
        ConcatStrategy.STREAM_COPY,
        None,
        (),
        100,
        120,
        ColorProfile(ColorMatrix.BT709, "bt709", "bt709"),
        pipeline=ProcessingPipeline.CONCAT,
    )
    tool = ToolInfo(tmp_path / "ffmpeg", "fake")
    tools = Toolchain(tool, tool, None, None)
    manager = WorkspaceManager(tmp_path / "jobs")
    workspace = manager.create()

    class Runner:
        """Capture the command and create the expected fake output."""

        command: tuple[str, ...] = ()

        def run(self, command: Sequence[str], _cancellation: CancellationToken, _timeout_seconds: float) -> ProcessResult:
            """Record one invocation and emulate a successful FFmpeg process."""

            self.command = tuple(command)
            Path(self.command[-1]).write_bytes(b"stream-copy")
            return ProcessResult(self.command, 0, "", "")

    class Verifier:
        """Return a compatible probe for the generated partial output."""

        def verify(self, path: Path, _job: JobPlan, strategy: ConcatStrategy) -> MediaProbe:
            """Confirm the direct-copy strategy and redirect the source probe."""

            assert strategy is ConcatStrategy.STREAM_COPY
            return replace(probe, path=path)

    runner = Runner()
    result = DirectConcatExecutor(manager, runner, Verifier()).execute(job, tools, workspace=workspace)  # type: ignore[arg-type]

    assert result.output_path == output
    assert output.read_bytes() == b"stream-copy"
    assert "-c" in runner.command and runner.command[runner.command.index("-c") + 1] == "copy"
    assert "-vf" not in runner.command and "libx264" not in runner.command
    assert runner.command[runner.command.index("-f", runner.command.index("-c")) + 1] == "mov"
    assert not workspace.path.exists()
