"""Tests for exact, typed domain values."""

import pytest

from advanced_ai_video_tools.core.models import Rational


def test_rational_normalizes_sign_and_common_divisor() -> None:
    """Equivalent rational inputs have one stable representation."""

    assert Rational(60000, -2002) == Rational(-30000, 1001)
    assert str(Rational.parse("30000/1001")) == "30000/1001"
    assert Rational.parse("4:3") == Rational(4, 3)


def test_rational_rejects_zero_denominator() -> None:
    """An invalid FFprobe fraction never enters a job plan."""

    with pytest.raises(ValueError, match="denominator"):
        Rational(1, 0)
