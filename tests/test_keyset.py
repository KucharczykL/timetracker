"""Reading a queryset one indexed page at a time, without a server-side cursor.

Two of these matter more than the rest. A tie that straddles a page boundary is
what a wrong comparison breaks, and it breaks by skipping a row. The SQL form is
what the `OR` spelling breaks, and it breaks by being slow while every row is
still correct -- so a rows-only test passes on the wrong query.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from django.contrib.auth.models import User
from django.db import connection
from django.test.utils import CaptureQueriesContext

from common.keyset import keyset_pages
from games.models import Game, Platform, Session

ZONEINFO = ZoneInfo(settings.TIME_ZONE)
BASE = datetime(2025, 1, 1, 12, 0, tzinfo=ZONEINFO)


@pytest.fixture
def library(db):
    user = User.objects.create_user(username="keyset", password="p")
    return user.library


@pytest.fixture
def game(library):
    platform = Platform.objects.create(library=library, name="PC", icon="pc")
    return Game.objects.create(library=library, name="A", platform=platform)


def _sessions(game, offsets: list[int]) -> list[Session]:
    return [
        Session.objects.create(game=game, timestamp_start=BASE + timedelta(hours=hours))
        for hours in offsets
    ]


def test_one_field_ascending_reads_every_row_in_order(game):
    _sessions(game, [0, 1, 2, 3, 4])
    rows = list(
        keyset_pages(Session.objects.all(), key=("timestamp_start",), page_size=2)
    )
    assert [row.timestamp_start for row in rows] == sorted(
        row.timestamp_start for row in Session.objects.all()
    )


def test_two_fields_descending_read_from_the_newest(game):
    _sessions(game, [0, 1, 2])
    rows = list(
        keyset_pages(
            Session.objects.all(),
            key=("timestamp_start", "id"),
            descending=True,
            page_size=2,
        )
    )
    assert [row.timestamp_start for row in rows] == sorted(
        (row.timestamp_start for row in Session.objects.all()), reverse=True
    )


def test_a_tie_straddling_a_page_boundary_yields_every_row_once(game):
    """Three sessions share one start time, and the page holds two of them."""
    _sessions(game, [0, 1, 1, 1, 2])
    rows = list(
        keyset_pages(
            Session.objects.all(),
            key=("timestamp_start", "id"),
            descending=True,
            page_size=2,
        )
    )
    identifiers = [row.id for row in rows]
    assert len(identifiers) == 5
    assert len(set(identifiers)) == 5


def test_a_result_ending_on_a_page_boundary_stops(game):
    _sessions(game, [0, 1, 2, 3])
    rows = list(
        keyset_pages(Session.objects.all(), key=("timestamp_start", "id"), page_size=2)
    )
    assert len(rows) == 4


def test_one_row_and_no_rows(game):
    assert list(keyset_pages(Session.objects.all(), key=("id",), page_size=2)) == []
    only = _sessions(game, [0])[0]
    assert [row.id for row in keyset_pages(Session.objects.all(), key=("id",))] == [
        only.id
    ]


def test_a_composite_key_emits_a_row_value_comparison(game):
    """PostgreSQL reads a row value as an index range condition. It cannot read
    an OR that way, so the OR spelling is quadratic and this assertion is the
    only thing that catches it."""
    _sessions(game, [0, 1, 2])
    with CaptureQueriesContext(connection) as captured:
        list(
            keyset_pages(
                Session.objects.all(),
                key=("timestamp_start", "id"),
                descending=True,
                page_size=1,
            )
        )
    second = captured.captured_queries[1]["sql"]
    assert '("games_session"."timestamp_start", "games_session"."id") <' in second
    assert " OR " not in second


def test_a_single_field_key_emits_a_plain_comparison(game):
    _sessions(game, [0, 1])
    with CaptureQueriesContext(connection) as captured:
        list(keyset_pages(Session.objects.all(), key=("id",), page_size=1))
    assert '"games_session"."id" >' in captured.captured_queries[1]["sql"]


def test_an_empty_key_is_refused(game):
    with pytest.raises(ValueError, match="at least one key field"):
        list(keyset_pages(Session.objects.all(), key=()))


def test_a_page_smaller_than_one_row_is_refused(game):
    with pytest.raises(ValueError, match="at least one row"):
        list(keyset_pages(Session.objects.all(), key=("id",), page_size=0))
