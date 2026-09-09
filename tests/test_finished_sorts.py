"""Both finished sorts read the runs."""

import json
from datetime import date

import pytest
from completed_runs import add_game, make_purchase
from django.urls import reverse
from purchase_rows import row_order

from common.criteria import Modifier, StringCriterion
from games.filters import GameFilter, PurchaseFilter
from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.untracked_games


@pytest.fixture
def logged_client(client, owned_user):
    client.force_login(owned_user)
    return client


@pytest.fixture
def three_purchases(owned_user, owned_library):
    """Late, early and one with no completion."""
    late = make_purchase(owned_library, name="Late")
    add_game(
        owned_user, owned_library, late, "L", TemporalValue.from_day(date(2024, 7, 1))
    )
    early = make_purchase(owned_library, name="Early")
    add_game(
        owned_user, owned_library, early, "E", TemporalValue.from_day(date(2020, 3, 4))
    )
    none = make_purchase(owned_library, name="None")
    add_game(owned_user, owned_library, none, "N", False)
    return late, early, none


@pytest.mark.django_db(transaction=True)
def test_purchases_descending_put_nulls_last(logged_client, three_purchases):
    late, early, none = three_purchases

    body = logged_client.get(
        reverse("games:list_purchases"), {"sort": "-finished"}
    ).content.decode()

    assert row_order(body, three_purchases) == [late.pk, early.pk, none.pk]


@pytest.mark.django_db(transaction=True)
def test_purchases_ascending_put_nulls_last(logged_client, three_purchases):
    late, early, none = three_purchases

    body = logged_client.get(
        reverse("games:list_purchases"), {"sort": "finished"}
    ).content.decode()

    assert row_order(body, three_purchases) == [early.pk, late.pk, none.pk]


@pytest.mark.django_db(transaction=True)
def test_a_dayless_completion_sorts_with_the_undated(
    logged_client, owned_user, owned_library
):
    """The cell says Unknown; no day sorts."""
    dated = make_purchase(owned_library, name="Dated")
    add_game(
        owned_user, owned_library, dated, "D", TemporalValue.from_day(date(2020, 3, 4))
    )
    dayless = make_purchase(owned_library, name="Dayless")
    add_game(owned_user, owned_library, dayless, "U", None)

    body = logged_client.get(
        reverse("games:list_purchases"), {"sort": "-finished"}
    ).content.decode()

    assert row_order(body, (dated, dayless)) == [dated.pk, dayless.pk]


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("sort", ["finished", "-finished"])
def test_the_game_list_sorts_by_finished(
    logged_client, owned_user, owned_library, sort
):
    """No column renders it; the URL does."""
    purchase = make_purchase(owned_library)
    add_game(
        owned_user,
        owned_library,
        purchase,
        "G",
        TemporalValue.from_day(date(2024, 7, 1)),
    )

    response = logged_client.get(reverse("games:list_games"), {"sort": sort})

    assert response.status_code == 200


@pytest.mark.django_db(transaction=True)
def test_a_filter_does_not_narrow_the_reported_completion(
    logged_client, owned_user, owned_library
):
    """The whole purchase reports, not the match."""
    purchase = make_purchase(owned_library)
    add_game(
        owned_user,
        owned_library,
        purchase,
        "Early",
        TemporalValue.from_day(date(2020, 3, 4)),
    )
    add_game(
        owned_user,
        owned_library,
        purchase,
        "Late",
        TemporalValue.from_day(date(2024, 7, 1)),
    )

    body = logged_client.get(
        reverse("games:list_purchases"),
        {
            "filter": json.dumps(
                PurchaseFilter(
                    game_filter=GameFilter(
                        name=StringCriterion(modifier=Modifier.EQUALS, value="Early")
                    )
                ).to_json()
            ),
            "sort": "-finished",
        },
    ).content.decode()

    #: Filter named 2020, bundle reports 2024.
    assert "2024-07-01" in body


@pytest.mark.django_db(transaction=True)
def test_a_saved_sort_of_finished_still_runs(logged_client, three_purchases):
    """A preset can carry a columnless key."""
    late = three_purchases[0]

    response = logged_client.get(
        reverse("games:list_purchases"), {"sort": "-finished,name"}
    )

    assert response.status_code == 200
    assert row_order(response.content.decode(), three_purchases)[0] == late.pk
