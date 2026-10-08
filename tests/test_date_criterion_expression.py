"""`to_q_on(expression)` answers what `to_q(column)` answers."""

import json
from datetime import date

import pytest
from django.db.models import F
from entries import record_entry
from graphs import default_graph
from purchases import record_purchase, refund_purchase

from common.criteria import DateCriterion, FilterError, Modifier
from games.filters import parse_game_filter, parse_session_filter
from games.models import Game, Purchase
from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.django_db

DAYS = (date(2026, 3, 4), date(2026, 3, 5), date(2026, 3, 6))


@pytest.fixture
def three_days(owned_library):
    graph = default_graph(Game(name="Tunic", library=owned_library), owned_library)
    entry = record_entry(owned_library, graph.release)
    for day in DAYS:
        #: An upgrade's refund ends no copy.
        purchase = record_purchase(entry, kind="upgrade", name=day.isoformat())
        refund_purchase(purchase, TemporalValue.from_day(day))
    #: Never refunded: the NULL row.
    record_purchase(entry, kind="upgrade", name="kept")


def _criterion(modifier: Modifier) -> DateCriterion:
    return DateCriterion(value="2026-03-05", value2="2026-03-06", modifier=modifier)


@pytest.mark.parametrize(
    "modifier", [*Modifier.for_dates(), Modifier.WITHIN], ids=lambda m: m.value
)
def test_both_forms_match_the_same_rows(three_days, modifier):
    criterion = _criterion(modifier)

    by_column = set(Purchase.objects.filter(criterion.to_q("refunded_lower")))
    by_expression = set(Purchase.objects.filter(criterion.to_q_on(F("refunded_lower"))))

    assert by_expression == by_column
    assert by_column


@pytest.mark.parametrize("modifier", [Modifier.BETWEEN, Modifier.NOT_BETWEEN])
def test_both_forms_refuse_a_missing_bound(modifier):
    criterion = DateCriterion(value="2026-03-05", modifier=modifier)

    with pytest.raises(FilterError):
        criterion.to_q("refunded_lower")
    with pytest.raises(FilterError):
        criterion.to_q_on(F("refunded_lower"))


@pytest.mark.parametrize(
    "modifier",
    [Modifier.EQUALS, Modifier.NOT_EQUALS, Modifier.GREATER_THAN, Modifier.BETWEEN],
    ids=lambda modifier: modifier.value,
)
def test_no_date_is_refused_not_compared_to_null(modifier):
    """A keyword lookup read None as IS NULL; an expression must not."""
    criterion = DateCriterion(value=None, value2="2026-03-06", modifier=modifier)

    with pytest.raises(FilterError, match="IS_NULL"):
        criterion.to_q_on(F("refunded_lower"))


@pytest.mark.parametrize(
    ("parse", "field"),
    [(parse_game_filter, "created_at"), (parse_session_filter, "started")],
)
def test_a_null_value_on_a_day_facet_is_refused_at_parse(parse, field):
    blob = json.dumps({field: {"modifier": "EQUALS", "value": None}})

    with pytest.raises(FilterError):
        parse(blob)
