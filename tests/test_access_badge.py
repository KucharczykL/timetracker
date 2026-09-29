"""The Access badge: fill, glyph, number, and the lines it shows."""

import re
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from common.components import AccessBadge
from common.components.domain import AccessLine, access_lines
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


def _lines(held=(), ended=()) -> list[str]:
    return [
        line.words
        for line in access_lines(AccessSummary(tuple(held), tuple(ended)), PRESENTATION)
    ]


def _badge(held=(), ended=()) -> str:
    return str(
        AccessBadge(
            AccessSummary(tuple(held), tuple(ended)), PRESENTATION, id="access-1"
        )
    )


def _glyphs(html: str) -> list[str]:
    return [
        glyph
        for glyph, marker in (
            ("cloud", 'viewBox="1.5 1.5 21 21"'),
            ("physical", 'viewBox="0 0 512 512"'),
            ("dashed-ring", "stroke-dasharray"),
        )
        if marker in html
    ]


# ── The lines ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("held", "ended", "lines"),
    [
        ([_held()], [], ["Owned"]),
        ([_held(format="physical")], [], ["Physical"]),
        ([_held(format="unknown")], [], ["Owned, format unknown"]),
        ([_held(format="physical"), _held()], [], ["Physical", "Owned"]),
        (
            [_held(), _held("rented", "physical"), _held()],
            [],
            ["2 × owned", "Rented physical"],
        ),
        (
            [
                _held(format="physical"),
                _held(format="physical"),
                _held(),
                _held(),
                _held("borrowed", "unknown"),
            ],
            [],
            ["2 × physical", "2 × owned", "Borrowed, format unknown"],
        ),
        ([_held(), _held("subscription")], [], ["Owned", "Subscription"]),
        ([_held("subscription")] * 4, [], ["4 × subscription"]),
        ([_held("borrowed")], [], ["Borrowed"]),
        ([_held("borrowed", "physical")], [], ["Borrowed physical"]),
        ([_held("pirated", "unknown")], [], ["Pirated, format unknown"]),
        ([_held("trial"), _held("demo")], [], ["Trial", "Demo"]),
        (
            [],
            [_ended(format="physical", ended="2024-03")],
            ["Physical, sold March 2024"],
        ),
        ([], [_ended(format="physical", way="lost", ended=None)], ["Physical, lost"]),
        (
            [],
            [_ended("borrowed", way="returned", ended="2024-03")],
            ["Borrowed until March 2024"],
        ),
        (
            [],
            [_ended("subscription", way="expired", ended="2025-06")],
            ["Subscription until June 2025"],
        ),
        ([], [_ended("borrowed", way="returned", ended=None)], ["Borrowed until ?"]),
        (
            [],
            [_ended("trial", way="revoked", ended="2025-05")],
            ["Trial until May 2025"],
        ),
        ([], [_ended(way="refunded", ended="2025-05")], ["Refunded May 2025"]),
        (
            [_held(format="physical")],
            [_ended(ended="2023")],
            ["Physical", "Sold 2023"],
        ),
        (
            [],
            [
                _ended(format="physical", ended="2024-06"),
                _ended("borrowed", way="returned", ended="2020"),
            ],
            ["Physical, sold June 2024", "Borrowed until 2020"],
        ),
    ],
    ids=[
        "owned-digital",
        "owned-physical",
        "owned-unknown",
        "physical-and-digital",
        "two-owned-and-rented",
        "five-copies",
        "owned-and-subscription",
        "four-subscriptions",
        "borrowed",
        "borrowed-physical",
        "pirated-unknown",
        "trial-and-demo",
        "sold",
        "lost-on-unknown-day",
        "returned",
        "subscription-expired",
        "returned-on-unknown-day",
        "trial-revoked",
        "refunded",
        "held-beside-sold",
        "two-ended",
    ],
)
def test_each_situation_reads_as_approved(held, ended, lines):
    assert _lines(held, ended) == lines


def test_ended_lines_follow_held_ones_and_say_so():
    summary = AccessSummary((_held(),), (_ended(),))

    assert access_lines(summary, PRESENTATION) == [
        AccessLine("Owned", ended=False),
        AccessLine("Sold 2023", ended=True),
    ]


# ── The badge ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("held", "ended", "filled", "glyphs"),
    [
        ([_held()], [], True, ["cloud"]),
        (
            [_held(format="physical"), _held("borrowed")],
            [],
            True,
            ["cloud", "physical"],
        ),
        ([_held("borrowed")], [], False, ["cloud"]),
        ([_held(format="unknown")], [], True, ["dashed-ring"]),
        ([_held("trial", "unknown"), _held("subscription")], [], False, ["cloud"]),
        ([], [_ended(format="physical")], False, ["physical"]),
        ([_held(format="physical")], [_ended()], True, ["physical"]),
    ],
    ids=[
        "owned",
        "owned-and-borrowed",
        "borrowed",
        "unknown-alone",
        "unknown-beside-known",
        "former",
        "ended-beside-held",
    ],
)
def test_fill_and_glyphs(held, ended, filled, glyphs):
    html = _badge(held, ended)

    assert ("solid-brand" in html) is filled
    assert _glyphs(html) == glyphs


def test_the_panel_mutes_ended_lines():
    html = _badge([_held()], [_ended()])
    panel = html.split('role="tooltip"', 1)[1]

    assert "<li>Owned</li>" in panel
    assert '<li class="text-body">Sold 2023</li>' in panel


def test_the_number_counts_held_copies_above_one():
    assert '<span aria-hidden="true">3</span>' in _badge([_held()] * 3)
    single = _badge([_held()], [_ended()])
    assert not re.search(r'<span aria-hidden="true">\d', single)
    assert "None" not in single


def test_the_badge_is_the_popovers_button_named_by_its_lines():
    html = _badge([_held(), _held()], [_ended(format="physical")])

    button = re.search(r"<button[^>]*>", html)
    assert button is not None
    assert "data-pop-over-trigger" in button.group(0)
    assert "aria-describedby" not in button.group(0)
    assert '<span class="sr-only">2 × owned; Physical, sold 2023</span>' in html
    assert "title=" not in html


def test_every_glyph_is_hidden_and_untitled():
    html = _badge([_held(format="physical"), _held()])

    svgs = re.findall(r"<svg[^>]*>", html)
    assert len(svgs) == 2
    assert all('aria-hidden="true"' in svg for svg in svgs)
    assert "<title>" not in html
