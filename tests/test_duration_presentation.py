"""Every duration profile's exact rendering, including the carry boundaries.

The table mirrors the rendering rules in
docs/superpowers/specs/2026-07-29-issue-486-duration-format-design.md — it is
the specification, so a change here is a design change, not a test fix.
"""

from datetime import timedelta

import pytest

from common.duration_presentation import (
    DurationPresentation,
    duration_format_profile,
    format_decimal_hours,
)

MINUTE = 60
HOUR = 60 * MINUTE
DAY = 24 * HOUR

# (seconds, decimal_hours, hours_minutes, whole_hours, adaptive)
RENDERINGS = [
    (0, "0.0 h", "0 h", "0 hours", "0 h"),
    (45, "0.0 h", "1 m", "0 hours", "1 m"),
    (29 * MINUTE, "0.5 h", "29 m", "0 hours", "29 m"),
    (45 * MINUTE, "0.8 h", "45 m", "1 hour", "45 m"),
    (HOUR + 12 * MINUTE, "1.2 h", "1 h 12 m", "1 hour", "1 h 12 m"),
    (3 * HOUR + 5 * MINUTE, "3.1 h", "3 h 05 m", "3 hours", "3 h 05 m"),
    (3 * HOUR + 30 * MINUTE, "3.5 h", "3 h 30 m", "4 hours", "3 h 30 m"),
    (23 * HOUR + 59 * MINUTE + 45, "24.0 h", "24 h 00 m", "24 hours", "1 d 00 h"),
    (26 * HOUR, "26.0 h", "26 h 00 m", "26 hours", "1 d 02 h"),
    (83 * HOUR + 12 * MINUTE, "83.2 h", "83 h 12 m", "83 hours", "3 d 11 h"),
    (200 * HOUR, "200.0 h", "200 h 00 m", "200 hours", "1 w 1 d"),
    (1234 * HOUR, "1234.0 h", "1234 h 00 m", "1234 hours", "7 w 2 d"),
    (9000 * HOUR, "9000.0 h", "9000 h 00 m", "9000 hours", "1 y 2 w"),
]

PROFILE_IDS = ("decimal_hours", "hours_minutes", "whole_hours", "adaptive")


def _presentation(profile_id: str) -> DurationPresentation:
    return DurationPresentation(
        profile=duration_format_profile(profile_id), locale="en-us"
    )


@pytest.mark.parametrize("row", RENDERINGS, ids=[str(row[0]) for row in RENDERINGS])
@pytest.mark.parametrize("index,profile_id", list(enumerate(PROFILE_IDS, start=1)))
def test_renders_the_specified_value(row, index, profile_id):
    seconds, *expected_per_profile = row

    rendered = _presentation(profile_id).format(timedelta(seconds=seconds))

    assert rendered == expected_per_profile[index - 1]


@pytest.mark.parametrize("profile_id", PROFILE_IDS)
def test_none_renders_as_zero(profile_id):
    presentation = _presentation(profile_id)

    assert presentation.format(None) == presentation.format(timedelta(0))


@pytest.mark.parametrize("profile_id", PROFILE_IDS)
def test_negative_clamps_to_zero(profile_id):
    """timestamp_end before timestamp_start is bad data, not a negative
    duration."""
    presentation = _presentation(profile_id)

    assert presentation.format(timedelta(seconds=-500)) == presentation.format(
        timedelta(0)
    )


@pytest.mark.parametrize(
    "seconds,expected",
    [
        # Rounding a component after the split would give "2 h 60 m".
        (HOUR + 59 * MINUTE + 45, "2 h 00 m"),
        (29 * MINUTE + 30, "30 m"),
    ],
)
def test_hours_minutes_rounds_the_total_once(seconds, expected):
    assert _presentation("hours_minutes").format(timedelta(seconds=seconds)) == expected


@pytest.mark.parametrize(
    "seconds,expected",
    [
        # Rounding carries into a higher unit, so the ladder re-picks rather
        # than rendering "6 d 24 h".
        (6 * DAY + 23 * HOUR + 40 * MINUTE, "1 w 0 d"),
        (HOUR + 59 * MINUTE + 45, "2 h 00 m"),
    ],
)
def test_adaptive_repicks_when_rounding_carries(seconds, expected):
    assert _presentation("adaptive").format(timedelta(seconds=seconds)) == expected


def test_unregistered_profile_id_raises():
    with pytest.raises(ValueError, match="two_hours"):
        duration_format_profile("two_hours")


def test_format_decimal_hours_is_preference_independent():
    """Session.__str__ and other request-less callers need one fixed
    rendering, not the viewer's profile."""
    assert format_decimal_hours(timedelta(seconds=HOUR + 12 * MINUTE)) == "1.2"
    assert format_decimal_hours(None) == "0.0"
