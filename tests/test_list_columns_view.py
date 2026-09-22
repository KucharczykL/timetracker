"""The one route a person states a column choice through."""

import pytest
from django.urls import reverse

from games.list_columns import hidden_columns, state_hidden_columns
from games.models import ListColumnChoice

pytestmark = pytest.mark.django_db


@pytest.fixture
def logged_in(client, owned_user):
    client.force_login(owned_user)
    return client


def _url(mode: str = "sessions") -> str:
    return reverse("games:state_list_columns", args=[mode])


def test_the_keys_a_person_did_not_post_are_the_ones_they_hid(logged_in, owned_user):
    logged_in.post(_url(), {"shown": ["date", "duration"]})

    assert hidden_columns(owned_user, "sessions") == frozenset(
        {"playthrough", "device", "created"}
    )


def test_posting_every_key_takes_the_row_away(logged_in, owned_user):
    state_hidden_columns(owned_user, "sessions", ["device"])

    logged_in.post(
        _url(),
        {"shown": ["playthrough", "date", "duration", "device", "created"]},
    )

    assert ListColumnChoice.objects.count() == 0


def test_a_column_that_refuses_to_hide_is_never_stored(logged_in, owned_user):
    """Its box is disabled, so it posts nothing; nothing hides it either."""
    logged_in.post(_url(), {"shown": ["date"]})

    assert "name" not in hidden_columns(owned_user, "sessions")


def test_a_reset_takes_the_row_away_whatever_it_carries(logged_in, owned_user):
    state_hidden_columns(owned_user, "sessions", ["device"])

    logged_in.post(_url(), {"reset": "1", "shown": ["date"]})

    assert ListColumnChoice.objects.count() == 0


def test_the_route_reads_no_get(logged_in):
    assert logged_in.get(_url()).status_code == 405


def test_a_mode_no_list_states_is_absent(logged_in):
    assert logged_in.post(_url("sittings"), {"shown": []}).status_code == 404


def test_it_returns_to_the_list_it_was_stated_from(logged_in):
    origin = reverse("games:list_sessions") + "?sort=date"

    answer = logged_in.post(f"{_url()}?origin={origin}", {"shown": ["date"]})

    assert answer.status_code == 302
    assert answer["Location"] == origin


def test_an_origin_no_read_only_route_names_falls_back(logged_in):
    answer = logged_in.post(
        f"{_url()}?origin=/tracker/session/1/remove", {"shown": ["date"]}
    )

    assert answer["Location"] == reverse("games:list_sessions")


@pytest.mark.parametrize(
    "mode",
    [
        "games",
        "sessions",
        "purchases",
        "playthroughs",
        "historical_playtime",
        "devices",
        "platforms",
    ],
)
def test_every_mode_states_a_route_and_a_list_to_return_to(logged_in, mode):
    answer = logged_in.post(_url(mode), {"shown": []})

    assert answer.status_code == 302
