"""Shared explicit SDR color-profile policy used by preflight and builders."""

from ai_video_tools.core.models import ColorMatrix, ColorProfile, VideoStream

HDR_TRANSFERS = {"smpte2084", "arib-std-b67", "smpte428"}
WIDE_PRIMARIES = {"bt2020", "smpte431", "smpte432", "jedec-p22"}
WIDE_SPACES = {"bt2020nc", "bt2020c", "ictcp"}
SUPPORTED_SDR_COLOR_MATRICES = frozenset(matrix.value for matrix in ColorMatrix)
SUPPORTED_SDR_TRANSFERS = frozenset({"bt709", "smpte170m"})
SUPPORTED_SDR_PRIMARIES = frozenset({"bt709", "smpte170m"})


def is_hdr_or_wide_gamut(video: VideoStream) -> bool:
    """Whether explicit metadata identifies unsupported HDR or wide gamut."""

    return video.has_hdr_metadata or video.color_transfer in HDR_TRANSFERS or video.color_primaries in WIDE_PRIMARIES or video.color_space in WIDE_SPACES


def has_unsupported_sdr_tags(video: VideoStream) -> bool:
    """Whether a present color tag falls outside the accepted SDR input profile."""

    return (video.color_space is not None and video.color_space not in SUPPORTED_SDR_COLOR_MATRICES) or (video.color_transfer is not None and video.color_transfer not in SUPPORTED_SDR_TRANSFERS) or (video.color_primaries is not None and video.color_primaries not in SUPPORTED_SDR_PRIMARIES) or video.color_range not in (None, "tv", "limited", "pc", "jpeg")


def has_ambiguous_color_tags(video: VideoStream) -> bool:
    """Whether required matrix or range metadata is missing."""

    return video.color_space is None or video.color_range is None


def color_profile(video: VideoStream) -> ColorProfile:
    """Return the supported profile without inventing optional metadata."""

    if has_ambiguous_color_tags(video):
        raise ValueError("color matrix and range must be explicit")
    if is_hdr_or_wide_gamut(video) or has_unsupported_sdr_tags(video):
        raise ValueError("unsupported SDR color profile")
    if video.color_space is None:
        raise AssertionError("color validation lost the required matrix")
    return ColorProfile(ColorMatrix(video.color_space), video.color_transfer, video.color_primaries)


def color_profiles_compatible(actual: ColorProfile, expected: ColorProfile) -> bool:
    """Treat missing optional tags as unknown while rejecting explicit conflicts."""

    transfer_conflicts = actual.transfer is not None and expected.transfer is not None and actual.transfer != expected.transfer
    primaries_conflict = actual.primaries is not None and expected.primaries is not None and actual.primaries != expected.primaries
    return actual.matrix is expected.matrix and not transfer_conflicts and not primaries_conflict


def color_profiles_mutually_compatible(profiles: tuple[ColorProfile, ...] | list[ColorProfile]) -> bool:
    """Whether all declared values agree while absent optional tags act as unknown."""

    matrices = {profile.matrix for profile in profiles}
    transfers = {profile.transfer for profile in profiles if profile.transfer is not None}
    primaries = {profile.primaries for profile in profiles if profile.primaries is not None}
    return len(matrices) <= 1 and len(transfers) <= 1 and len(primaries) <= 1


def has_color_profile(video: VideoStream, expected: ColorProfile) -> bool:
    """Whether a stream has no explicit conflict with the frozen profile."""

    try:
        return color_profiles_compatible(color_profile(video), expected)
    except ValueError:
        return False
