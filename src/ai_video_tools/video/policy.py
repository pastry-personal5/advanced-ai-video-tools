"""Shared SDR BT.709 policy predicates used by preflight and builders."""

from ai_video_tools.core.models import VideoStream

HDR_TRANSFERS = {"smpte2084", "arib-std-b67", "smpte428"}
WIDE_PRIMARIES = {"bt2020", "smpte431", "smpte432", "jedec-p22"}
WIDE_SPACES = {"bt2020nc", "bt2020c", "ictcp"}


def is_hdr_or_wide_gamut(video: VideoStream) -> bool:
    """Whether explicit metadata identifies unsupported HDR or wide gamut."""

    return video.has_hdr_metadata or video.color_transfer in HDR_TRANSFERS or video.color_primaries in WIDE_PRIMARIES or video.color_space in WIDE_SPACES


def has_unsupported_sdr_tags(video: VideoStream) -> bool:
    """Whether a present color tag falls outside the accepted BT.709 profile."""

    return video.color_space not in (None, "bt709") or video.color_transfer not in (None, "bt709") or video.color_primaries not in (None, "bt709") or video.color_range not in (None, "tv", "limited", "pc", "jpeg")


def has_ambiguous_color_tags(video: VideoStream) -> bool:
    """Whether interpretation requires explicit user acknowledgement."""

    return None in (video.color_space, video.color_transfer, video.color_primaries, video.color_range)
