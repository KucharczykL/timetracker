"""What the legacy lifecycle rows hold, before #684 converts them."""

import uuid
from datetime import date

import pytest

from games.models import Game, PlayEvent
from games.preflight.playthrough import (
    NO_COUNTS,
    LegacyOrderKey,
    OrderingVerdict,
    PreflightCounts,
    RowVerdict,
    classify_row,
    legacy_order_key,
    ordering_counts,
)

pytestmark = pytest.mark.django_db


def _row(started=None, ended=None, game=None):
    """A PlayEvent that is never saved: the classifiers read fields."""
    return PlayEvent(id=uuid.uuid7(), game=game, started=started, ended=ended)


def test_both_endpoints_convert_without_a_question():
    row = _row(started=date(2024, 1, 1), ended=date(2024, 1, 9))
    assert classify_row(row) is RowVerdict.CLEAN_BOTH


def test_one_day_is_not_a_reversal():
    #: days_to_finish already reads an equal pair as one day, and #681
    #: refuses only a completion earlier than its start.
    row = _row(started=date(2024, 1, 1), ended=date(2024, 1, 1))
    assert classify_row(row) is RowVerdict.CLEAN_BOTH


def test_a_start_with_no_completion():
    row = _row(started=date(2024, 1, 1))
    assert classify_row(row) is RowVerdict.CLEAN_START_ONLY


def test_a_completion_with_no_start():
    row = _row(ended=date(2024, 1, 9))
    assert classify_row(row) is RowVerdict.CLEAN_END_ONLY


def test_neither_endpoint_is_known():
    assert classify_row(_row()) is RowVerdict.NO_KNOWN_ENDPOINT


def test_a_completion_before_its_start_is_named():
    row = _row(started=date(2024, 1, 9), ended=date(2024, 1, 1))
    assert classify_row(row) is RowVerdict.REVERSED_ENDPOINTS


def test_a_known_start_sorts_before_an_unknown_one():
    known = _row(started=date(2024, 1, 1))
    unknown = _row()
    assert legacy_order_key(known) < legacy_order_key(unknown)


def test_an_unknown_completion_sorts_last_among_equal_starts():
    start = date(2024, 1, 1)
    dated = _row(started=start, ended=date(2024, 2, 1))
    open_ended = _row(started=start)
    assert legacy_order_key(dated) < legacy_order_key(open_ended)


def test_the_last_resort_is_the_primary_key():
    #: created_at is auto_now_add and loaddata rewrites it. The pk is a
    #: UUIDv7 the dump preserves, so it is the one stable insertion order.
    first = _row()
    second = _row()
    first.id, second.id = uuid.UUID(int=1), uuid.UUID(int=2)
    assert legacy_order_key(first) < legacy_order_key(second)


def test_the_key_names_its_parts():
    row = _row(started=date(2024, 1, 1))
    key = legacy_order_key(row)
    assert isinstance(key, LegacyOrderKey)
    assert key.start_unknown is False
    assert key.completion_unknown is True


def test_counts_sum_field_by_field():
    left = PreflightCounts(live_rows=2, clean_both=1)
    right = PreflightCounts(live_rows=3, tie_broken=1)
    total = left + right
    assert total.live_rows == 5
    assert total.clean_both == 1
    assert total.tie_broken == 1


def test_the_empty_counts_are_an_identity():
    counts = PreflightCounts(live_rows=4)
    assert NO_COUNTS + counts == counts


def test_counts_render_every_field():
    rendered = PreflightCounts(live_rows=1).as_dict()
    assert rendered["live_rows"] == 1
    assert rendered["tie_broken"] == 0


def test_distinct_dates_order_a_game_on_their_own():
    rows = [
        _row(started=date(2024, 1, 1)),
        _row(started=date(2024, 3, 1)),
    ]
    assert ordering_counts(rows) == OrderingVerdict(
        ordered_by_date=True, tie_broken=False, date_order_differs=False
    )


def test_two_rows_sharing_a_date_pair_fall_to_insertion_order():
    rows = [
        _row(started=date(2024, 1, 1), ended=date(2024, 2, 1)),
        _row(started=date(2024, 1, 1), ended=date(2024, 2, 1)),
    ]
    verdict = ordering_counts(rows)
    assert verdict.tie_broken is True
    assert verdict.ordered_by_date is False


def test_two_undated_rows_tie_as_well():
    verdict = ordering_counts([_row(), _row()])
    assert verdict.tie_broken is True


def test_a_single_row_ties_with_nothing():
    verdict = ordering_counts([_row()])
    assert verdict.tie_broken is False
    assert verdict.ordered_by_date is True


def test_a_date_order_against_the_insertion_order_is_reported():
    #: Written second, played first: the display number moves.
    first_written = _row(started=date(2024, 3, 1))
    second_written = _row(started=date(2024, 1, 1))
    first_written.id, second_written.id = uuid.UUID(int=1), uuid.UUID(int=2)
    verdict = ordering_counts([first_written, second_written])
    assert verdict.date_order_differs is True
    assert verdict.tie_broken is False
