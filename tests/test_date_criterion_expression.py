"""`to_q_on(expression)` answers what `to_q(column)` answers."""

from datetime import date

import pytest
from completed_runs import make_purchase
from django.db.models import F

from common.criteria import DateCriterion, FilterError, Modifier
from games.models import Purchase

pytestmark = pytest.mark.django_db

DAYS = (date(2026, 3, 4), date(2026, 3, 5), date(2026, 3, 6))


@pytest.fixture
def three_days(owned_library):
    for day in DAYS:
        purchase = make_purchase(owned_library, name=day.isoformat())
        Purchase.objects.filter(pk=purchase.pk).update(date_refunded=day)
    #: Never refunded: the NULL row.
    make_purchase(owned_library, name="kept")


def _criterion(modifier: Modifier) -> DateCriterion:
    return DateCriterion(value="2026-03-05", value2="2026-03-06", modifier=modifier)


@pytest.mark.parametrize(
    "modifier", [*Modifier.for_dates(), Modifier.WITHIN], ids=lambda m: m.value
)
def test_both_forms_match_the_same_rows(three_days, modifier):
    criterion = _criterion(modifier)

    by_column = set(Purchase.objects.filter(criterion.to_q("date_refunded")))
    by_expression = set(Purchase.objects.filter(criterion.to_q_on(F("date_refunded"))))

    assert by_expression == by_column
    assert by_column


@pytest.mark.parametrize("modifier", [Modifier.BETWEEN, Modifier.NOT_BETWEEN])
def test_both_forms_refuse_a_missing_bound(modifier):
    criterion = DateCriterion(value="2026-03-05", modifier=modifier)

    with pytest.raises(FilterError):
        criterion.to_q("date_refunded")
    with pytest.raises(FilterError):
        criterion.to_q_on(F("date_refunded"))
