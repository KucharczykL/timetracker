"""Tests for filter_url() — the reverse()-style helper that builds a URL to a
filtered list view from a filter object (issue #56)."""

from urllib.parse import parse_qs, urlparse

from django.urls import reverse

from common.criteria import IntCriterion, Modifier, filter_to_json
from games.filters import (
    GameFilter,
    PurchaseFilter,
    SessionFilter,
    filter_url,
    parse_game_filter,
)


def test_filter_url_path_inferred_from_filter_type():
    assert urlparse(filter_url(GameFilter())).path == reverse("games:list_games")
    assert urlparse(filter_url(SessionFilter())).path == reverse("games:list_sessions")
    assert urlparse(filter_url(PurchaseFilter())).path == reverse(
        "games:list_purchases"
    )


def test_filter_url_encodes_filter_json_that_round_trips():
    game_filter = GameFilter(
        year_released=IntCriterion(value=2010, modifier=Modifier.GREATER_THAN)
    )
    url = filter_url(game_filter)
    query = parse_qs(urlparse(url).query)
    assert query["filter"][0] == filter_to_json(game_filter)
    assert parse_game_filter(query["filter"][0]).to_q() == game_filter.to_q()


def test_filter_url_merges_extra_params():
    query = parse_qs(urlparse(filter_url(GameFilter(), sort="name")).query)
    assert query["sort"][0] == "name"
