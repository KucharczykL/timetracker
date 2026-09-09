"""What the Finished cell prints."""

import re
from datetime import date

import pytest
from completed_runs import add_game, make_purchase
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.untracked_games

#: Measured, not guessed. Constant across row counts.
PURCHASE_LIST_QUERIES = 16


@pytest.fixture
def logged_client(client, owned_user):
    client.force_login(owned_user)
    return client


def cell_text(html, index):
    """The text of one rendered cell.

    The name cell is a `<th>`, so both tags count.
    """
    cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", html, re.DOTALL)
    return re.sub(r"<[^>]+>", "", cells[index]).strip()


def finished_cell(client, purchase):
    """The Finished cell's text for one row."""
    response = client.get(reverse("games:list_purchases"))
    assert response.status_code == 200
    body = response.content.decode()
    row = re.search(rf'id="purchase-row-{purchase.pk}".*?</tr>', body, re.DOTALL)
    assert row, "row not rendered"
    #: Name, Type, Price, Infinite, Purchased, Finished, ...
    return cell_text(row.group(0), 5)


@pytest.mark.django_db(transaction=True)
def test_no_completion_prints_a_dash(logged_client, owned_user, owned_library):
    purchase = make_purchase(owned_library)
    add_game(owned_user, owned_library, purchase, "Playing", False)

    assert finished_cell(logged_client, purchase) == "-"


@pytest.mark.django_db(transaction=True)
def test_a_purchase_naming_no_game_prints_a_dash(logged_client, owned_library):
    """It names no run."""
    purchase = make_purchase(owned_library)

    assert finished_cell(logged_client, purchase) == "-"


@pytest.mark.django_db(transaction=True)
def test_a_dayless_completion_prints_unknown(logged_client, owned_user, owned_library):
    purchase = make_purchase(owned_library)
    add_game(owned_user, owned_library, purchase, "Dayless", None)

    assert finished_cell(logged_client, purchase) == "Unknown"


@pytest.mark.django_db(transaction=True)
def test_a_dated_completion_prints_its_day(logged_client, owned_user, owned_library):
    purchase = make_purchase(owned_library)
    add_game(
        owned_user,
        owned_library,
        purchase,
        "Dated",
        TemporalValue.from_day(date(2024, 7, 1)),
    )

    assert finished_cell(logged_client, purchase) == "2024-07-01"


@pytest.mark.django_db(transaction=True)
def test_a_decade_prints_its_words(logged_client, owned_user, owned_library):
    purchase = make_purchase(owned_library)
    add_game(owned_user, owned_library, purchase, "Coarse", TemporalValue.parse("202X"))

    assert finished_cell(logged_client, purchase) == "2020s"


@pytest.mark.django_db(transaction=True)
def test_an_open_start_range_prints_its_words(logged_client, owned_user, owned_library):
    purchase = make_purchase(owned_library)
    add_game(
        owned_user,
        owned_library,
        purchase,
        "Open",
        TemporalValue.parse("../2020-05-01"),
    )

    assert finished_cell(logged_client, purchase) == "until 2020-05-01"


@pytest.mark.django_db(transaction=True)
def test_the_refunded_row_keeps_its_cell(logged_client, owned_user, owned_library):
    """The refund swap reads the list's queryset."""
    purchase = make_purchase(owned_library)
    add_game(
        owned_user,
        owned_library,
        purchase,
        "Dated",
        TemporalValue.from_day(date(2024, 7, 1)),
    )

    response = logged_client.post(reverse("games:refund_purchase", args=[purchase.pk]))

    assert response.status_code == 200
    assert cell_text(response.content.decode(), 5) == "2024-07-01"


def seed_rows(user, library, count):
    """`count` purchases, each naming one completed game."""
    for index in range(count):
        purchase = make_purchase(library, name=f"Bundle {index}")
        add_game(
            user,
            library,
            purchase,
            f"Game {index}",
            TemporalValue.from_day(date(2024, 7, 1)),
        )


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("rows", [3, 10])
def test_the_list_costs_no_query_per_row(
    logged_client, owned_user, owned_library, django_assert_num_queries, rows
):
    """Ten purchases cost what three do."""
    seed_rows(owned_user, owned_library, rows)

    with django_assert_num_queries(PURCHASE_LIST_QUERIES):
        logged_client.get(reverse("games:list_purchases"))


@pytest.mark.django_db(transaction=True)
def test_the_completion_costs_no_query_per_row(
    logged_client, owned_user, owned_library
):
    """One query reads the projection."""
    seed_rows(owned_user, owned_library, 10)

    with CaptureQueriesContext(connection) as captured:
        logged_client.get(reverse("games:list_purchases"))

    reads = [
        query
        for query in captured.captured_queries
        if "games_playthrough" in query["sql"]
    ]

    assert len(reads) == 1
