"""Duration(): the visible rendering, its alternates, and its spoken form."""

from datetime import timedelta

import pytest

from common.components import Duration, DurationText, PlaytimeSplit
from common.components.core import assert_unique_element_ids
from common.duration_presentation import (
    DurationPresentation,
    duration_format_profile,
)
from games.reads.sums import PlaytimeBreakdown

MINUTE = 60
HOUR = 60 * MINUTE


def _presentation(profile_id: str = "decimal_hours") -> DurationPresentation:
    return DurationPresentation(
        profile=duration_format_profile(profile_id), locale="en-us"
    )


def _render(seconds: int, *, id_scope: str = "session-1-duration", **kwargs) -> str:
    return str(
        Duration(
            timedelta(seconds=seconds),
            _presentation(),
            id_scope=id_scope,
            **kwargs,
        )
    )


def test_visible_value_is_hidden_from_assistive_technology():
    html = _render(HOUR + 12 * MINUTE)

    assert 'aria-hidden="true"' in html
    assert "1.2 h" in html


def test_spoken_text_is_rendered_sr_only():
    html = _render(HOUR + 12 * MINUTE)

    assert 'class="sr-only"' in html
    assert "1 hour 12 minutes" in html


def test_manual_mark_follows_the_value_and_is_spoken():
    html = _render(HOUR + 12 * MINUTE, manual=True)

    assert "1.2 h*" in html
    assert "1 hour 12 minutes, manual" in html


def test_alternates_render_as_label_value_rows():
    html = _render(HOUR + 12 * MINUTE)

    assert "Hours and minutes" in html
    assert "1 h 12 m" in html
    assert "Whole hours" in html
    assert "1 hour" in html


def test_describedby_is_absent():
    """The sr-only text already carries the value; describing the trigger with
    the panel would read the same number three times per row."""
    assert "aria-describedby" not in _render(HOUR + 12 * MINUTE)


def test_two_equal_durations_get_distinct_ids():
    """Popover derives an id by hashing its content, so equal durations on one
    page would collide without a caller-supplied scope."""
    from common.components import Fragment

    document = Fragment(
        Duration(timedelta(0), _presentation(), id_scope="game-1-playtime"),
        Duration(timedelta(0), _presentation(), id_scope="game-2-playtime"),
    )

    assert_unique_element_ids(str(document))


def test_id_scope_is_required():
    with pytest.raises(TypeError):
        Duration(timedelta(0), _presentation())  # type: ignore[call-arg]


def test_linked_duration_shows_its_glyph_on_every_device():
    """The reveal glyph is how a popover announces itself. A pointer device can
    hover the value to open the panel, but nothing tells it the panel exists —
    so the glyph stays visible there too."""
    html = str(
        Duration(
            timedelta(seconds=HOUR),
            _presentation(),
            id_scope="navbar-today",
            link="/tracker/session/list",
        )
    )

    assert "[@media(hover:none)]" not in html
    assert "data-pop-over-reveal" in html
    assert 'href="/tracker/session/list"' in html
    assert 'aria-label="Other duration formats"' in html


def _split(tracked: int, historical: int, **kwargs) -> str:
    return str(
        PlaytimeSplit(
            PlaytimeBreakdown(
                tracked=timedelta(seconds=tracked),
                historical=timedelta(seconds=historical),
            ),
            _presentation(),
            **kwargs,
        )
    )


def test_zero_historical_renders_exactly_a_duration():
    """A library with no record sees no change at all."""
    assert _split(2 * HOUR, 0, id_scope="stats-total-hours") == _render(
        2 * HOUR, id_scope="stats-total-hours"
    )


def test_zero_historical_without_a_popover_renders_exactly_the_text():
    assert _split(2 * HOUR, 0, popover=False) == str(
        DurationText(timedelta(seconds=2 * HOUR), _presentation())
    )


def test_the_split_states_both_halves():
    html = _split(3 * HOUR, 2 * HOUR, id_scope="stats-total-hours")

    assert "5.0 h" in html
    assert '>3.0 h</span><span class="sr-only">3 hours</span> tracked' in html
    assert '>2.0 h</span><span class="sr-only">2 hours</span> historical' in html


def test_each_half_carries_its_spoken_form():
    html = _split(3 * HOUR, 2 * HOUR, id_scope="stats-total-hours")

    assert ">3 hours</span> tracked" in html
    assert ">2 hours</span> historical" in html
    #: A reader announces a bare separator as "middle dot".
    assert '<span aria-hidden="true"> · </span>' in html


def test_a_popover_requires_an_id_scope():
    with pytest.raises(ValueError, match="id_scope"):
        _split(3 * HOUR, 2 * HOUR)


def test_no_popover_refuses_an_id_scope():
    with pytest.raises(ValueError, match="id_scope"):
        _split(3 * HOUR, 2 * HOUR, popover=False, id_scope="stats-total-hours")


def test_a_link_without_a_popover_is_refused():
    with pytest.raises(ValueError, match="link"):
        _split(3 * HOUR, 2 * HOUR, popover=False, link="/tracker/session/list")


def test_the_split_forwards_its_link():
    html = _split(
        3 * HOUR, 2 * HOUR, id_scope="stats-month-6", link="/tracker/game/list"
    )

    assert 'href="/tracker/game/list"' in html
    assert '>2.0 h</span><span class="sr-only">2 hours</span> historical' in html
