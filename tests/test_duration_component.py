"""Duration(): the visible rendering, its alternates, and its spoken form."""

from datetime import timedelta

import pytest

from common.components import Duration
from common.components.core import assert_unique_element_ids
from common.duration_presentation import (
    DurationPresentation,
    duration_format_profile,
)

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


def test_linked_duration_hides_its_glyph_on_pointer_devices():
    """The info glyph exists for devices that cannot hover, matching
    TruncatedText's reveal button. On a pointer device the panel opens by
    hovering the total itself, so the glyph would be noise."""
    html = str(
        Duration(
            timedelta(seconds=HOUR),
            _presentation(),
            id_scope="navbar-today",
            link="/tracker/session/list",
        )
    )

    assert "hidden [@media(hover:none)]:inline-flex" in html
    assert 'href="/tracker/session/list"' in html
    assert 'aria-label="Other duration formats"' in html
