"""Excluded games: found, listed, shown."""

import json
from typing import NamedTuple

import pytest
from django.urls import reverse
from tracked_games import create_tracked_game

from common.criteria import BoolCriterion, Modifier
from games.filters import GameFilter
from games.list_columns import state_shown_columns
from games.views.list_columns import LIST_COLUMNS

pytestmark = pytest.mark.django_db


class Flag(NamedTuple):
    fact: str
    column: str
    sort: str
    shown: str


FLAGS = [
    pytest.param(
        Flag(
            "excluded_from_unfinished",
            "Unfinished lists",
            "unfinished_lists",
            "unfinished lists",
        ),
        id="unfinished",
    ),
    pytest.param(
        Flag(
            "excluded_from_dropped",
            "Dropped figures",
            "dropped_figures",
            "dropped figures",
        ),
        id="dropped",
    ),
]


@pytest.fixture
def logged_in(client, owned_user):
    client.force_login(owned_user)
    return client


@pytest.fixture(params=FLAGS)
def flag(request) -> Flag:
    return request.param


@pytest.fixture
def games(owned_library, flag):
    flagged = create_tracked_game(owned_library, "Endless Farm", **{flag.fact: True})
    plain = create_tracked_game(owned_library, "Short Story")
    return flagged, plain


def _listed(logged_in, **query) -> str:
    return logged_in.get(reverse("games:list_games"), query).content.decode()


def test_the_filter_states_the_flag_as_a_bool(flag):
    assert GameFilter.where(**{flag.fact: True}) == GameFilter(
        **{flag.fact: BoolCriterion(value=True, modifier=Modifier.EQUALS)}
    )


def test_the_filter_survives_json(flag):
    stated = GameFilter.where(**{flag.fact: False})

    assert GameFilter.from_json(stated.to_json()) == stated


def test_a_list_finds_the_excluded_game(logged_in, games, flag):
    body = _listed(
        logged_in,
        filter=json.dumps({flag.fact: {"value": True, "modifier": "EQUALS"}}),
    )

    assert "Endless Farm" in body
    assert "Short Story" not in body


def test_a_list_finds_the_included_game(logged_in, games, flag):
    body = _listed(
        logged_in,
        filter=json.dumps({flag.fact: {"value": False, "modifier": "EQUALS"}}),
    )

    assert "Short Story" in body
    assert "Endless Farm" not in body


def test_a_shown_column_names_the_excluded_game(logged_in, owned_user, games, flag):
    columns = LIST_COLUMNS["games"].columns
    state_shown_columns(
        owned_user, "games", [column.key for column in columns], columns
    )

    body = _listed(logged_in)

    assert flag.column in body
    assert body.count(">Excluded<") == 1


def test_the_column_is_hidden_by_default(logged_in, games):
    assert ">Excluded<" not in _listed(logged_in)


def test_the_column_sorts_without_warning(logged_in, games, flag):
    answer = logged_in.get(reverse("games:list_games"), {"sort": flag.sort})

    assert answer.status_code == 200
    assert "Unknown sort" not in answer.content.decode()


def _row(body: str, label: str) -> str:
    """The label to the next label."""
    return body.split(f">{label}<", 1)[1].split('class="uppercase"', 1)[0]


def test_detail_names_the_exclusion_under_visibility(logged_in, games, flag):
    flagged, plain = games

    flagged_body = logged_in.get(flagged.get_absolute_url()).content.decode()
    assert f"Left out of {flag.shown}" in _row(flagged_body, "Visibility")
    assert "Left out" not in _row(flagged_body, "Status")
    assert ">Visibility<" not in (
        logged_in.get(plain.get_absolute_url()).content.decode()
    )


def test_detail_names_both_exclusions_in_one_row(logged_in, owned_library):
    both = create_tracked_game(
        owned_library,
        "Endless Farm",
        excluded_from_unfinished=True,
        excluded_from_dropped=True,
    )

    body = logged_in.get(both.get_absolute_url()).content.decode()

    assert "Left out of unfinished lists, dropped figures" in _row(body, "Visibility")
