"""Shared explicit SDR color-profile policy used by preflight and builders."""

from advanced_ai_video_tools.core.models import ColorMatrix, ColorProfile, VideoStream

HDR_TRANSFERS = {"smpte2084", "arib-std-b67", "smpte428"}
WIDE_PRIMARIES = {"bt2020", "smpte431", "smpte432", "jedec-p22"}
WIDE_SPACES = {"bt2020nc", "bt2020c", "ictcp"}
DEFAULT_COLOR_MATRIX = ColorMatrix.BT709
DEFAULT_COLOR_TRANSFER = "iec61966-2-1"
DEFAULT_COLOR_PRIMARIES = "bt709"
SUPPORTED_SDR_COLOR_MATRICES = frozenset(matrix.value for matrix in ColorMatrix)
SUPPORTED_SDR_TRANSFERS = frozenset({"bt709", "smpte170m", "iec61966-2-1"})
SUPPORTED_SDR_PRIMARIES = frozenset({"bt709", "smpte170m"})


def is_hdr_or_wide_gamut(video: VideoStream) -> bool:
    """Whether explicit metadata identifies unsupported HDR or wide gamut."""

    return video.has_hdr_metadata or video.color_transfer in HDR_TRANSFERS or video.color_primaries in WIDE_PRIMARIES or video.color_space in WIDE_SPACES


def has_unsupported_sdr_tags(video: VideoStream) -> bool:
    """Whether a present color tag falls outside the accepted SDR input profile."""

    return (video.color_space is not None and video.color_space not in SUPPORTED_SDR_COLOR_MATRICES) or (video.color_transfer is not None and video.color_transfer not in SUPPORTED_SDR_TRANSFERS) or (video.color_primaries is not None and video.color_primaries not in SUPPORTED_SDR_PRIMARIES) or video.color_range not in (None, "tv", "limited", "pc", "jpeg")


def effective_color_space(video: VideoStream) -> str:
    """Return the tagged matrix, or the BT.709 default for untagged video."""

    return video.color_space if video.color_space is not None else DEFAULT_COLOR_MATRIX.value


def effective_color_transfer(video: VideoStream) -> str:
    """Return the tagged transfer, or the sRGB (IEC 61966-2-1) default."""

    return video.color_transfer if video.color_transfer is not None else DEFAULT_COLOR_TRANSFER


def effective_color_primaries(video: VideoStream) -> str:
    """Return the tagged primaries, or the BT.709 default."""

    return video.color_primaries if video.color_primaries is not None else DEFAULT_COLOR_PRIMARIES


def color_profile(video: VideoStream) -> ColorProfile:
    """Return the supported profile; an absent matrix is bt709 and absent optional tags stay unknown."""

    if is_hdr_or_wide_gamut(video) or has_unsupported_sdr_tags(video):
        raise ValueError("unsupported SDR color profile")
    return ColorProfile(ColorMatrix(effective_color_space(video)), video.color_transfer, video.color_primaries)


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


def default_output_profile(profile: ColorProfile) -> ColorProfile:
    """Fill tags the first clip lacked with the bt709 / iec61966-2-1 / bt709 defaults."""

    return ColorProfile(
        profile.matrix,
        profile.transfer if profile.transfer is not None else DEFAULT_COLOR_TRANSFER,
        profile.primaries if profile.primaries is not None else DEFAULT_COLOR_PRIMARIES,
    )
