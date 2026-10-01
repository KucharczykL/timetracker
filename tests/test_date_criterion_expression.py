"""`to_q_on(expression)` answers what `to_q(column)` answers."""

import json
from datetime import date

import pytest
from django.db.models import F

from common.criteria import DateCriterion, FilterError, Modifier
from games.filters import parse_game_filter, parse_session_filter
from games.models import LegacyPurchase

pytestmark = pytest.mark.django_db

DAYS = (date(2026, 3, 4), date(2026, 3, 5), date(2026, 3, 6))


def make_purchase(library, name):
    return LegacyPurchase.objects.create(
        library=library,
        name=name,
        date_purchased=date(2020, 1, 1),
        price_currency="CZK",
    )


@pytest.fixture
def three_days(owned_library):
    for day in DAYS:
        purchase = make_purchase(owned_library, name=day.isoformat())
        LegacyPurchase.objects.filter(pk=purchase.pk).update(date_refunded=day)
    #: Never refunded: the NULL row.
    make_purchase(owned_library, name="kept")


def _criterion(modifier: Modifier) -> DateCriterion:
    return DateCriterion(value="2026-03-05", value2="2026-03-06", modifier=modifier)


@pytest.mark.parametrize(
    "modifier", [*Modifier.for_dates(), Modifier.WITHIN], ids=lambda m: m.value
)
def test_both_forms_match_the_same_rows(three_days, modifier):
    criterion = _criterion(modifier)

    by_column = set(LegacyPurchase.objects.filter(criterion.to_q("date_refunded")))
    by_expression = set(
        LegacyPurchase.objects.filter(criterion.to_q_on(F("date_refunded")))
    )

    assert by_expression == by_column
    assert by_column


@pytest.mark.parametrize("modifier", [Modifier.BETWEEN, Modifier.NOT_BETWEEN])
def test_both_forms_refuse_a_missing_bound(modifier):
    criterion = DateCriterion(value="2026-03-05", modifier=modifier)

    with pytest.raises(FilterError):
        criterion.to_q("date_refunded")
    with pytest.raises(FilterError):
        criterion.to_q_on(F("date_refunded"))


@pytest.mark.parametrize(
    "modifier",
    [Modifier.EQUALS, Modifier.NOT_EQUALS, Modifier.GREATER_THAN, Modifier.BETWEEN],
    ids=lambda modifier: modifier.value,
)
def test_no_date_is_refused_not_compared_to_null(modifier):
    """A keyword lookup read None as IS NULL; an expression must not."""
    criterion = DateCriterion(value=None, value2="2026-03-06", modifier=modifier)

    with pytest.raises(FilterError, match="IS_NULL"):
        criterion.to_q_on(F("date_refunded"))


@pytest.mark.parametrize(
    ("parse", "field"),
    [(parse_game_filter, "created_at"), (parse_session_filter, "started")],
)
def test_a_null_value_on_a_day_facet_is_refused_at_parse(parse, field):
    blob = json.dumps({field: {"modifier": "EQUALS", "value": None}})

    with pytest.raises(FilterError):
        parse(blob)
