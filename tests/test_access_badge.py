"""The Access badge: fill, glyph, number, and the sentence it says."""

import re
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from common.components import AccessBadge
from common.components.domain import access_sentence
from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DateTimePresentation,
)
from games.models import LibraryEntry
from games.reads.entries import AccessSummary, EndedCopy, copy_end
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


def _ended_copy(entry: LibraryEntry) -> EndedCopy:
    end = copy_end(entry)
    assert end is not None
    return EndedCopy(entry, end)


def _summary(held, ended) -> AccessSummary:
    return AccessSummary(tuple(held), tuple(_ended_copy(entry) for entry in ended))


def _sentence(held=(), ended=()) -> str:
    return access_sentence(_summary(held, ended), PRESENTATION)


def _badge(held=(), ended=()) -> str:
    return str(AccessBadge(_summary(held, ended), PRESENTATION, id="access-1"))


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


# ── The sentence ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("held", "ended", "sentence"),
    [
        ([_held(format="physical")], [], "You have a physical version"),
        ([_held()], [], "You have a digital version"),
        ([_held("pirated", "unknown")], [], "You have an unknown version"),
        (
            [_held(format="physical"), _held("borrowed")],
            [],
            "You have both the digital and physical version",
        ),
        ([_held(), _held()], [], "You have 2 versions"),
        (
            [_held(format="physical"), _held(), _held(format="unknown")],
            [],
            "You have 3 versions",
        ),
        (
            [],
            [_ended(format="physical", ended="2024-03")],
            "You had a physical version, sold March 2024",
        ),
        (
            [],
            [_ended(format="physical", way="lost", ended=None)],
            "You had a physical version, lost",
        ),
        (
            [],
            [_ended("borrowed", way="returned", ended="2024-03")],
            "You had a digital version until March 2024",
        ),
        (
            [],
            [_ended("borrowed", way="returned", ended=None)],
            "You had a digital version",
        ),
        (
            [],
            [_ended("trial", way="revoked", ended="2025-05")],
            "You had a digital version until May 2025",
        ),
        (
            [],
            [_ended(way="unstated", ended="2025-05")],
            "You had a digital version until May 2025",
        ),
        ([], [_ended(), _ended("borrowed", way="returned")], "You had 2 versions"),
        ([_held()], [_ended()], "You have 1 version, and had 1"),
        (
            [_held(), _held(format="physical")],
            [_ended(), _ended(), _ended()],
            "You have 2 versions, and had 3",
        ),
    ],
    ids=[
        "one-physical",
        "one-digital",
        "one-unknown",
        "physical-and-digital",
        "two-alike",
        "three-mixed",
        "one-sold",
        "one-lost-on-unknown-day",
        "one-returned",
        "one-returned-on-unknown-day",
        "one-trial-revoked",
        "one-gone-for-no-stated-reason",
        "two-ended",
        "one-and-one",
        "many-and-many",
    ],
)
def test_each_situation_reads_as_one_sentence(held, ended, sentence):
    assert _sentence(held, ended) == sentence


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


def test_the_panel_says_the_sentence_alone():
    html = _badge([_held()], [_ended()])
    panel = html.split('role="tooltip"', 1)[1]

    assert "You have 1 version, and had 1" in panel
    assert "<li" not in panel


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
    assert '<span class="sr-only">You have 2 versions, and had 1</span>' in html
    assert "title=" not in html


def test_every_glyph_is_hidden_and_untitled():
    html = _badge([_held(format="physical"), _held()])

    svgs = re.findall(r"<svg[^>]*>", html)
    assert len(svgs) == 2
    assert all('aria-hidden="true"' in svg for svg in svgs)
    assert "<title>" not in html
