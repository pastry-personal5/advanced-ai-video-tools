"""Tests for the deliberately narrow version 1 platform contract."""

from ai_video_tools.system.platform import PlatformInfo, parse_version, platform_error


def test_supported_platform_requires_minimum_macos_and_apple_silicon() -> None:
    """The stated minimum passes while older or Intel hosts fail."""

    assert platform_error(PlatformInfo("Darwin", "arm64", "26.5.2")) is None
    assert "26.5.2" in (platform_error(PlatformInfo("Darwin", "arm64", "26.5.1")) or "")
    assert "Apple Silicon" in (platform_error(PlatformInfo("Darwin", "x86_64", "27.0")) or "")


def test_version_parser_accepts_suffix_after_numeric_version() -> None:
    """Build suffixes do not change numeric comparison."""

    assert parse_version("26.5.2-beta") == (26, 5, 2)
