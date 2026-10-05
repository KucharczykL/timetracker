"""What the Finished cell prints."""

import re
from datetime import date

import pytest
from completed_runs import bought_game
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.untracked_games

#: Measured, not guessed. Constant across row counts.
#: One of them reads the column choice, once.
PURCHASE_LIST_QUERIES = 18


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
    """The text of the Finished cell of one row.

    Read by header, not by a counted position. The columns are the choice of
    the reader, thus a literal index can name a different column.
    """
    response = client.get(reverse("games:list_purchases"))
    assert response.status_code == 200
    body = response.content.decode()
    row = re.search(rf'id="purchase-row-{purchase.pk}".*?</tr>', body, re.DOTALL)
    assert row, "row not rendered"
    return cell_text(row.group(0), _column_index(body, "Finished"))


def _column_index(body: str, label: str) -> int:
    """Where that column renders, counted over the header row the page wrote."""
    [head] = re.findall(r"<thead.*?</thead>", body, re.DOTALL)
    #: The panel is in the last header cell and names each column.
    head = re.sub(r"<form .*?</form>", "", head, flags=re.DOTALL)
    labels = [
        re.sub(r"<[^>]+>", "", cell).strip()
        for cell in re.findall(r"<th.*?</th>", head, re.DOTALL)
    ]
    assert label in labels, f"the list renders no {label} column: {labels}"
    return labels.index(label)


@pytest.mark.django_db(transaction=True)
def test_no_completion_prints_a_dash(logged_client, owned_user, owned_library):
    purchase = bought_game(owned_user, owned_library, "Playing", False).purchase

    assert finished_cell(logged_client, purchase) == "-"


@pytest.mark.django_db(transaction=True)
def test_a_dayless_completion_prints_unknown(logged_client, owned_user, owned_library):
    purchase = bought_game(owned_user, owned_library, "Dayless", None).purchase

    assert finished_cell(logged_client, purchase) == "Unknown"


@pytest.mark.django_db(transaction=True)
def test_a_dated_completion_prints_its_day(logged_client, owned_user, owned_library):
    purchase = bought_game(
        owned_user, owned_library, "Dated", TemporalValue.from_day(date(2024, 7, 1))
    ).purchase

    assert finished_cell(logged_client, purchase) == "2024-07-01"


@pytest.mark.django_db(transaction=True)
def test_a_decade_prints_its_words(logged_client, owned_user, owned_library):
    purchase = bought_game(
        owned_user, owned_library, "Coarse", TemporalValue.parse("202X")
    ).purchase

    assert finished_cell(logged_client, purchase) == "2020s"


@pytest.mark.django_db(transaction=True)
def test_an_open_start_range_prints_its_words(logged_client, owned_user, owned_library):
    purchase = bought_game(
        owned_user, owned_library, "Open", TemporalValue.parse("../2020-05-01")
    ).purchase

    assert finished_cell(logged_client, purchase) == "until 2020-05-01"


def seed_rows(user, library, count):
    """`count` purchases, each naming one completed game."""
    for index in range(count):
        bought_game(
            user, library, f"Game {index}", TemporalValue.from_day(date(2024, 7, 1))
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

    #: The navbar's playtime read joins the run too; it is not this read.
    reads = [
        query
        for query in captured.captured_queries
        if "games_playthrough" in query["sql"]
        and "games_playersession" not in query["sql"]
    ]

    assert len(reads) == 1
