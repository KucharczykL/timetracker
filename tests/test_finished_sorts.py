"""Both finished sorts read the runs."""

import json
from datetime import date

import pytest
from completed_runs import add_run, bought_game
from django.urls import reverse
from purchase_rows import row_order

from common.criteria import Modifier, StringCriterion
from games.filters import GameFilter, LibraryEntryFilter, PurchaseFilter
from games.reads.playthrough_completions import completed_in_scope
from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.untracked_games


@pytest.fixture
def logged_client(client, owned_user):
    client.force_login(owned_user)
    return client


@pytest.fixture
def three_purchases(owned_user, owned_library):
    """Late, early and one with no completion."""
    late = bought_game(
        owned_user, owned_library, "L", TemporalValue.from_day(date(2024, 7, 1))
    ).purchase
    early = bought_game(
        owned_user, owned_library, "E", TemporalValue.from_day(date(2020, 3, 4))
    ).purchase
    none = bought_game(owned_user, owned_library, "N", False).purchase
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
    dated = bought_game(
        owned_user, owned_library, "D", TemporalValue.from_day(date(2020, 3, 4))
    ).purchase
    dayless = bought_game(owned_user, owned_library, "U", None).purchase

    body = logged_client.get(
        reverse("games:list_purchases"), {"sort": "-finished"}
    ).content.decode()

    assert row_order(body, (dated, dayless)) == [dated.pk, dayless.pk]


@pytest.mark.django_db(transaction=True)
def test_the_game_list_orders_by_its_own_completion(
    logged_client, owned_user, owned_library
):
    """No column renders it; the URL does."""
    bought_game(
        owned_user, owned_library, "Later", TemporalValue.from_day(date(2024, 7, 1))
    )
    bought_game(
        owned_user, owned_library, "Sooner", TemporalValue.from_day(date(2020, 3, 4))
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
    """The game reports, not the match.

    The filter matches both games by their 2020 runs;
    each row still reports its game's latest finish.
    """
    twice = bought_game(
        owned_user, owned_library, "Twice", TemporalValue.from_day(date(2020, 3, 4))
    )
    add_run(owned_user, twice.game, TemporalValue.from_day(date(2024, 7, 1)))
    once = bought_game(
        owned_user, owned_library, "Once", TemporalValue.from_day(date(2022, 5, 6))
    )
    add_run(owned_user, once.game, TemporalValue.from_day(date(2020, 6, 1)))

    body = logged_client.get(
        reverse("games:list_purchases"),
        {
            "filter": json.dumps(
                PurchaseFilter(
                    game_filter=GameFilter(playthrough_filter=completed_in_scope(2020))
                ).to_json()
            ),
            "sort": "-finished",
        },
    ).content.decode()

    assert "2024-07-01" in body
    assert row_order(body, (twice.purchase, once.purchase)) == [
        twice.purchase.pk,
        once.purchase.pk,
    ]


@pytest.mark.django_db(transaction=True)
def test_a_sort_of_finished_beside_another_key_runs(logged_client, three_purchases):
    """The key no column heads still sorts."""
    late = three_purchases[0]

    response = logged_client.get(
        reverse("games:list_purchases"), {"sort": "-finished,name"}
    )

    assert response.status_code == 200
    assert row_order(response.content.decode(), three_purchases)[0] == late.pk


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("path", ["game_filter", "search", "entry_filter"])
def test_every_join_path_prints_one_row(logged_client, owned_user, owned_library, path):
    """Each row prints once, whichever filter matched."""
    bought = bought_game(
        owned_user, owned_library, "Keep", TemporalValue.from_day(date(2020, 3, 4))
    )
    add_run(owned_user, bought.game, TemporalValue.from_day(date(2024, 7, 1)))
    keep = StringCriterion(modifier=Modifier.INCLUDES, value="Keep")
    filters = {
        "game_filter": PurchaseFilter(game_filter=GameFilter(name=keep)),
        "search": PurchaseFilter(search=keep),
        "entry_filter": PurchaseFilter(entry_filter=LibraryEntryFilter(search=keep)),
    }

    body = logged_client.get(
        reverse("games:list_purchases"),
        {"filter": json.dumps(filters[path].to_json()), "sort": "-finished"},
    ).content.decode()

    assert body.count(f'id="purchase-row-{bought.purchase.pk}"') == 1
