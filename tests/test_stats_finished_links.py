"""The links the statistics carry order by the runs."""

import json
from datetime import UTC, date, datetime

import pytest
from completed_runs import add_game, make_purchase
from django.urls import reverse
from purchase_rows import row_order

from games.views import stats_links
from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.untracked_games

#: Both builders scope on it: one bounds the purchase, the
#: other the year the game was released.
YEAR = 2024


@pytest.fixture
def logged_client(client, owned_user):
    client.force_login(owned_user)
    return client


def in_scope_purchase(user, library, name, day):
    """A purchase both builders reach, finished on `day`."""
    purchase = make_purchase(library, name=name)
    purchase.date_purchased = datetime(YEAR, 1, 1, tzinfo=UTC)
    purchase.save()
    game, _ = add_game(user, library, purchase, name, TemporalValue.from_day(day))
    game.year_released = YEAR
    game.save()
    return purchase


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "builder",
    [
        stats_links.purchases_finished_released,
        stats_links.purchases_bought_and_finished,
    ],
)
def test_the_link_orders_by_the_reported_completion(
    logged_client, owned_user, owned_library, builder
):
    """The stat's link prints each row once, later finish first."""
    late = in_scope_purchase(owned_user, owned_library, "Late", date(YEAR, 12, 1))
    early = in_scope_purchase(owned_user, owned_library, "Early", date(YEAR, 1, 5))

    response = logged_client.get(
        reverse("games:list_purchases"),
        {"filter": json.dumps(builder(YEAR).to_json()), "sort": "-finished"},
    )

    assert response.status_code == 200
    body = response.content.decode()
    #: The filter joins the games, so a row the join answers
    #: twice would print twice without the list's distinct().
    assert body.count(f'id="purchase-row-{late.pk}"') == 1
    assert row_order(body, (late, early)) == [late.pk, early.pk]


@pytest.mark.django_db(transaction=True)
def test_the_all_time_link_reaches_every_completion(
    logged_client, owned_user, owned_library
):
    """All-time reads the marker, so a dayless finish counts."""
    dated = in_scope_purchase(owned_user, owned_library, "Dated", date(YEAR, 12, 1))
    dayless = make_purchase(owned_library, name="Dayless")
    add_game(owned_user, owned_library, dayless, "Dayless", None)

    response = logged_client.get(
        reverse("games:list_purchases"),
        {
            "filter": json.dumps(stats_links.purchases_finished("alltime").to_json()),
            "sort": "-finished",
        },
    )

    assert response.status_code == 200
    #: The dated finish leads; the one nobody dated sorts last.
    assert row_order(response.content.decode(), (dated, dayless)) == [
        dated.pk,
        dayless.pk,
    ]
