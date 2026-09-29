"""The Access badge: fill, glyph, number, and the words it speaks."""

import re
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from common.components import AccessBadge
from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DateTimePresentation,
)
from games.models import LibraryEntry
from games.reads.entries import AccessSummary
from timetracker.temporal import TemporalValue

PRESENTATION = DateTimePresentation(
    DEFAULT_DATE_TIME_FORMAT_PROFILE, "en-us", ZoneInfo("UTC")
)


def _held(access: str = "owned", format: str = "digital") -> LibraryEntry:
    return LibraryEntry(access=access, format=format)


def _ended(
    access: str = "owned",
    format: str = "digital",
    way: str = "sold",
    ended: str | None = "2023",
) -> LibraryEntry:
    return LibraryEntry(
        access=access,
        format=format,
        access_end_recorded_at=datetime(2024, 1, 1, tzinfo=UTC),
        access_ended=None if ended is None else TemporalValue.parse(ended),
        access_end_way=way,
        access_end_note="",
    )


def _badge(*held: LibraryEntry, former: LibraryEntry | None = None) -> str:
    return str(AccessBadge(AccessSummary(held, former), PRESENTATION, id="access-1"))


def _panel(html: str) -> list[str]:
    """The popover's lines."""
    panel = html.split('role="tooltip"', 1)[1]
    return re.findall(r"<li>([^<]*)</li>", panel)


def _spoken(html: str) -> str:
    spoken = re.search(r'<span class="sr-only">([^<]*)</span>', html)
    assert spoken is not None
    return spoken.group(1)


def _glyphs(html: str) -> list[str]:
    return [
        glyph
        for glyph, marker in (
            ("cloud", 'viewBox="1.5 1.5 21 21"'),
            ("physical", 'viewBox="0 0 512 512"'),
            ("unspecified", 'viewBox="0 0 50 50"'),
        )
        if marker in html
    ]


@pytest.mark.parametrize(
    ("held", "filled", "glyphs", "lines"),
    [
        ((_held(),), True, ["cloud"], ["Owned · Digital"]),
        ((_held(format="physical"),), True, ["physical"], ["Owned · Physical"]),
        ((_held(format="unknown"),), True, ["unspecified"], ["Owned · Unknown"]),
        (
            (_held(format="physical"), _held("borrowed")),
            True,
            ["cloud", "physical"],
            ["Owned · Physical", "Borrowed · Digital"],
        ),
        ((_held("borrowed"),), False, ["cloud"], ["Borrowed · Digital"]),
        (
            (_held("subscription"), _held("trial", "unknown")),
            False,
            ["cloud"],
            ["Subscription · Digital", "Trial · Unknown"],
        ),
        (
            (_held(), _held("rented", "physical"), _held()),
            True,
            ["cloud", "physical"],
            ["2 × Owned · Digital", "Rented · Physical"],
        ),
    ],
    ids=[
        "owned-digital",
        "owned-physical",
        "owned-unknown",
        "owned-and-borrowed",
        "borrowed",
        "unknown-beside-known",
        "alike-copies-group",
    ],
)
def test_each_held_variant(held, filled, glyphs, lines):
    html = _badge(*held)

    assert ("solid-brand" in html) is filled
    assert _glyphs(html) == glyphs
    assert _panel(html) == lines
    assert _spoken(html) == ", ".join(lines)
    assert "title=" not in html


def test_the_number_counts_held_copies_above_one():
    assert '<span aria-hidden="true">3</span>' in _badge(_held(), _held(), _held())
    single = _badge(_held())
    assert '<span aria-hidden="true">1</span>' not in single
    assert "None" not in single


def test_a_former_copy_is_outlined_with_its_way_and_day():
    html = _badge(former=_ended(format="physical"))

    assert "solid-brand" not in html
    assert _glyphs(html) == ["physical"]
    assert _panel(html) == ["Not owned", "Formerly owned · physical, sold 2023"]
    assert not re.search(r'<span aria-hidden="true">\d', html)


def test_a_former_copy_on_an_unknown_day_names_its_way_alone():
    html = _badge(former=_ended(way="returned", ended=None))

    assert _panel(html) == ["Not owned", "Formerly owned · digital, returned"]


def test_every_glyph_is_hidden_and_untitled():
    html = _badge(_held(format="physical"), _held())

    svgs = re.findall(r"<svg[^>]*>", html)
    assert len(svgs) == 2
    assert all('aria-hidden="true"' in svg for svg in svgs)
    assert "<title>" not in html


def test_the_badge_is_the_popovers_button_named_by_its_words():
    html = _badge(_held(), _held())

    button = re.search(r"<button[^>]*>", html).group(0)
    assert "data-pop-over-trigger" in button
    assert "aria-describedby" not in button
    assert _spoken(html) == "2 × Owned · Digital"
