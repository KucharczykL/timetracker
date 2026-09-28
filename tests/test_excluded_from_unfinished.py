"""A game left out of unfinished lists: found, listed, stated, shown."""

import json

import pytest
from django.urls import reverse
from tracked_games import create_tracked_game

from common.criteria import BoolCriterion, Modifier
from games.filters import GameFilter
from games.list_columns import state_shown_columns
from games.views.list_columns import LIST_COLUMNS

pytestmark = pytest.mark.django_db


@pytest.fixture
def logged_in(client, owned_user):
    client.force_login(owned_user)
    return client


@pytest.fixture
def games(owned_library):
    flagged = create_tracked_game(
        owned_library, "Endless Farm", excluded_from_unfinished=True
    )
    plain = create_tracked_game(owned_library, "Short Story")
    return flagged, plain


def _listed(logged_in, **query) -> str:
    return logged_in.get(reverse("games:list_games"), query).content.decode()


def test_the_filter_states_the_flag_as_a_bool():
    assert GameFilter.where(excluded_from_unfinished=True) == GameFilter(
        excluded_from_unfinished=BoolCriterion(value=True, modifier=Modifier.EQUALS)
    )


def test_the_filter_survives_json():
    stated = GameFilter.where(excluded_from_unfinished=False)

    assert GameFilter.from_json(stated.to_json()) == stated


def test_a_list_finds_the_excluded_game(logged_in, games):
    body = _listed(
        logged_in,
        filter=json.dumps(
            {"excluded_from_unfinished": {"value": True, "modifier": "EQUALS"}}
        ),
    )

    assert "Endless Farm" in body
    assert "Short Story" not in body


def test_a_list_finds_the_included_game(logged_in, games):
    body = _listed(
        logged_in,
        filter=json.dumps(
            {"excluded_from_unfinished": {"value": False, "modifier": "EQUALS"}}
        ),
    )

    assert "Short Story" in body
    assert "Endless Farm" not in body


def test_a_shown_column_names_the_excluded_game(logged_in, owned_user, games):
    columns = LIST_COLUMNS["games"].columns
    state_shown_columns(
        owned_user, "games", [column.key for column in columns], columns
    )

    body = _listed(logged_in)

    assert "Unfinished lists" in body
    assert body.count(">Excluded<") == 1


def test_the_column_sorts_without_warning(logged_in, games):
    answer = logged_in.get(reverse("games:list_games"), {"sort": "unfinished_lists"})

    assert answer.status_code == 200
    assert "Unknown sort" not in answer.content.decode()


def _status_row(body: str) -> str:
    """From the Status label to the next row's label."""
    return body.split(">Status<", 1)[1].split('class="uppercase"', 1)[0]


def test_detail_names_the_exclusion(logged_in, games):
    flagged, plain = games

    assert "Excluded from unfinished lists" in _status_row(
        logged_in.get(flagged.get_absolute_url()).content.decode()
    )
    assert "Excluded from unfinished lists" not in _status_row(
        logged_in.get(plain.get_absolute_url()).content.decode()
    )
