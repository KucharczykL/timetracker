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
def test_the_game_list_orders_by_its_own_completion(
    logged_client, owned_user, owned_library
):
    """No column renders it; the URL orders by it.

    The game reads its own runs, not its purchase's. Were
    the path the purchase's, both games would report the
    bundle's latest finish and neither order would hold.
    """
    purchase = make_purchase(owned_library)
    add_game(
        owned_user,
        owned_library,
        purchase,
        "Later",
        TemporalValue.from_day(date(2024, 7, 1)),
    )
    add_game(
        owned_user,
        owned_library,
        purchase,
        "Sooner",
        TemporalValue.from_day(date(2020, 3, 4)),
    )

    descending = logged_client.get(
        reverse("games:list_games"), {"sort": "-finished"}
    ).content.decode()
    ascending = logged_client.get(
        reverse("games:list_games"), {"sort": "finished"}
    ).content.decode()

    assert descending.index("Later") < descending.index("Sooner")
    assert ascending.index("Sooner") < ascending.index("Later")


@pytest.mark.django_db(transaction=True)
def test_a_filter_does_not_narrow_the_reported_completion(
    logged_client, owned_user, owned_library
):
    """The whole purchase reports, not the match.

    The filter matches one game in each bundle, and the two
    matches rank the other way round from the two bundles.
    A reader the filter could narrow would print 2020 for
    the first bundle and order the rows the other way.
    """
    bundle = make_purchase(owned_library, name="Bundle")
    add_game(
        owned_user,
        owned_library,
        bundle,
        "Keep Early",
        TemporalValue.from_day(date(2020, 3, 4)),
    )
    add_game(
        owned_user,
        owned_library,
        bundle,
        "Drop Late",
        TemporalValue.from_day(date(2024, 7, 1)),
    )
    single = make_purchase(owned_library, name="Single")
    add_game(
        owned_user,
        owned_library,
        single,
        "Keep Middle",
        TemporalValue.from_day(date(2022, 5, 6)),
    )

    body = logged_client.get(
        reverse("games:list_purchases"),
        {
            "filter": json.dumps(
                PurchaseFilter(
                    game_filter=GameFilter(
                        name=StringCriterion(modifier=Modifier.INCLUDES, value="Keep")
                    )
                ).to_json()
            ),
            "sort": "-finished",
        },
    ).content.decode()

    #: Filter named 2020, bundle reports 2024.
    assert "2024-07-01" in body
    assert row_order(body, (bundle, single)) == [bundle.pk, single.pk]


@pytest.mark.django_db(transaction=True)
def test_a_sort_of_finished_beside_another_key_runs(logged_client, three_purchases):
    """The key no column heads still sorts."""
    late = three_purchases[0]

    response = logged_client.get(
        reverse("games:list_purchases"), {"sort": "-finished,name"}
    )

    assert response.status_code == 200
    assert row_order(response.content.decode(), three_purchases)[0] == late.pk
