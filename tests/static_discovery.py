"""Deterministic tool discovery for tests that must not launch host executables."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from advanced_ai_video_tools.core.models import ToolOverrides, Toolchain
from advanced_ai_video_tools.system.tools import ToolDiscovery


@dataclass(frozen=True)
class Completion:
    """One recorded request for AI prerequisites."""

    require_realesrgan: bool
    spandrel_scales: tuple[int, ...]


class StaticToolDiscovery(ToolDiscovery):
    """Serve a prepared toolchain through the real discovery boundary."""

    def __init__(self, toolchain: Toolchain) -> None:
        super().__init__()
        self.toolchain = toolchain
        self.media_requests = 0
        self.completions: list[Completion] = []

    def discover(self, overrides: ToolOverrides) -> Toolchain:
        """Return the complete prepared toolchain."""

        del overrides
        return self.toolchain

    def discover_media(self, overrides: ToolOverrides) -> Toolchain:
        """Return only the media tools, as the real discovery does."""

        del overrides
        self.media_requests += 1
        return Toolchain(self.toolchain.ffmpeg, self.toolchain.ffprobe, None, None)

    def complete_for_passes(
        self,
        overrides: ToolOverrides,
        media: Toolchain,
        *,
        require_realesrgan: bool,
        spandrel_scales: Sequence[int] = (),
        validate_configured_runner: bool = False,
    ) -> Toolchain:
        """Return only the requested prerequisites and record the request."""

        del overrides, validate_configured_runner
        scales = tuple(dict.fromkeys(spandrel_scales))
        self.completions.append(Completion(require_realesrgan, scales))
        prepared = self.toolchain
        return Toolchain(
            media.ffmpeg,
            media.ffprobe,
            prepared.realesrgan if require_realesrgan else None,
            prepared.model_directory if require_realesrgan else None,
            prepared.spandrel_runner if scales else None,
            tuple(inspection for inspection in prepared.spandrel_inspections if inspection.scale in scales),
        )
