"""Tests for the list-view sorting system (games/sorting.py)."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from django.contrib.messages import get_messages
from django.test import RequestFactory
from django.urls import reverse

from games.filters import FindFilter
from games.models import Game, Platform, Session
from games.sorting import (
    GAME_DEFAULT_SORT,
    GAME_SORTS,
    PURCHASE_DEFAULT_SORT,
    PURCHASE_SORTS,
    SESSION_DEFAULT_SORT,
    SESSION_SORTS,
    SortSpec,
    SortTerm,
    apply_sort,
    parse_find_filter,
    parse_sort_terms,
)

ZONEINFO = ZoneInfo(settings.TIME_ZONE)

# A minimal map; parse_sort_terms only checks key membership, not spec internals.
SAMPLE_MAP = {"name": SortSpec("name"), "date": SortSpec("created_at")}


class TestParseSortTerms:
    def test_bare_key_is_ascending(self):
        parsed = parse_sort_terms("name", SAMPLE_MAP)
        assert parsed.terms == [SortTerm("name", False)]
        assert parsed.unknown == []

    def test_dash_prefix_is_descending(self):
        parsed = parse_sort_terms("-date", SAMPLE_MAP)
        assert parsed.terms == [SortTerm("date", True)]

    def test_multi_column_preserves_order(self):
        parsed = parse_sort_terms("date,-name", SAMPLE_MAP)
        assert parsed.terms == [SortTerm("date", False), SortTerm("name", True)]

    def test_unknown_key_is_reported_not_raised(self):
        parsed = parse_sort_terms("bogus", SAMPLE_MAP)
        assert parsed.terms == []
        assert parsed.unknown == ["bogus"]

    def test_mixed_valid_and_unknown(self):
        parsed = parse_sort_terms("-name,bogus", SAMPLE_MAP)
        assert parsed.terms == [SortTerm("name", True)]
        assert parsed.unknown == ["bogus"]

    def test_whitespace_and_empty_tokens_ignored(self):
        parsed = parse_sort_terms(" name , , -date ", SAMPLE_MAP)
        assert parsed.terms == [SortTerm("name", False), SortTerm("date", True)]

    def test_empty_string_yields_nothing(self):
        parsed = parse_sort_terms("", SAMPLE_MAP)
        assert parsed.terms == []
        assert parsed.unknown == []


def _find(sort=None):
    return FindFilter(sort=sort)


@pytest.fixture
def two_games(db):
    platform = Platform.objects.create(name="P", icon="p")
    alpha = Game.objects.create(name="Alpha", sort_name="Alpha", platform=platform)
    beta = Game.objects.create(name="Beta", sort_name="Beta", platform=platform)
    return alpha, beta


class TestApplySortGames:
    def test_name_ascending(self, two_games):
        alpha, beta = two_games
        result = apply_sort(Game.objects.all(), _find("name"), GAME_SORTS, GAME_DEFAULT_SORT)
        assert list(result.queryset) == [alpha, beta]
        assert result.terms[0].key == "name"
        assert result.unknown == []

    def test_name_descending(self, two_games):
        alpha, beta = two_games
        result = apply_sort(Game.objects.all(), _find("-name"), GAME_SORTS, GAME_DEFAULT_SORT)
        assert list(result.queryset) == [beta, alpha]

    def test_default_sort_when_absent_is_created_desc(self, two_games):
        alpha, beta = two_games  # beta created after alpha
        result = apply_sort(Game.objects.all(), _find(None), GAME_SORTS, GAME_DEFAULT_SORT)
        assert list(result.queryset) == [beta, alpha]

    def test_unknown_key_reported_and_falls_back(self, two_games):
        result = apply_sort(Game.objects.all(), _find("bogus"), GAME_SORTS, GAME_DEFAULT_SORT)
        assert result.unknown == ["bogus"]
        assert result.queryset.count() == 2  # still returns rows (default order)

    def test_playtime_annotation_no_duplicate_rows(self, two_games):
        alpha, _ = two_games
        Session.objects.create(
            game=alpha,
            timestamp_start=datetime(2022, 1, 1, 10, tzinfo=ZONEINFO),
            timestamp_end=datetime(2022, 1, 1, 12, tzinfo=ZONEINFO),
        )
        Session.objects.create(
            game=alpha,
            timestamp_start=datetime(2022, 1, 2, 10, tzinfo=ZONEINFO),
            timestamp_end=datetime(2022, 1, 2, 11, tzinfo=ZONEINFO),
        )
        result = apply_sort(Game.objects.all(), _find("-playtime"), GAME_SORTS, GAME_DEFAULT_SORT)
        # two sessions on alpha must not duplicate the alpha row
        assert result.queryset.count() == 2
        assert list(result.queryset)[0] == alpha  # most playtime first



class TestParseFindFilter:
    def test_reads_sort_param(self):
        request = RequestFactory().get("/x", {"sort": "-playtime,name"})
        assert parse_find_filter(request).sort == "-playtime,name"

    def test_absent_sort_is_none(self):
        request = RequestFactory().get("/x")
        assert parse_find_filter(request).sort is None


class TestSortMapShapes:
    def test_default_sort_keys_exist_in_maps(self):
        # every key referenced by a default sort string must be defined in its map
        for default, sort_map in [
            (GAME_DEFAULT_SORT, GAME_SORTS),
            (SESSION_DEFAULT_SORT, SESSION_SORTS),
            (PURCHASE_DEFAULT_SORT, PURCHASE_SORTS),
        ]:
            for token in default.split(","):
                assert token.lstrip("-") in sort_map


@pytest.fixture
def logged_client(client, django_user_model):
    user = django_user_model.objects.create_user(username="u", password="p")
    client.force_login(user)
    return client


class TestListGamesSort:
    def test_sort_param_orders_rows(self, logged_client, two_games):
        alpha, beta = two_games
        response = logged_client.get(reverse("games:list_games"), {"sort": "-name"})
        assert response.status_code == 200
        body = response.content.decode()
        assert body.index("Beta") < body.index("Alpha")
        # ascending name must flip order vs the default (-created → Beta first)
        ascending = logged_client.get(reverse("games:list_games"), {"sort": "name"})
        ascending_body = ascending.content.decode()
        assert ascending_body.index("Alpha") < ascending_body.index("Beta")

    def test_unknown_sort_emits_warning_message(self, logged_client, two_games):
        response = logged_client.get(reverse("games:list_games"), {"sort": "bogus"})
        assert response.status_code == 200
        warnings = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("bogus" in w for w in warnings)

    def test_valid_sort_emits_no_warning(self, logged_client, two_games):
        response = logged_client.get(reverse("games:list_games"), {"sort": "name"})
        warnings = [str(m) for m in get_messages(response.wsgi_request)]
        assert warnings == []


class TestListSessionsSort:
    def test_sort_by_duration_descending(self, logged_client, two_games):
        alpha, beta = two_games
        Session.objects.create(
            game=alpha,
            timestamp_start=datetime(2022, 1, 1, 10, tzinfo=ZONEINFO),
            timestamp_end=datetime(2022, 1, 1, 10, 30, tzinfo=ZONEINFO),  # 30 min
        )
        Session.objects.create(
            game=beta,
            timestamp_start=datetime(2022, 1, 2, 10, tzinfo=ZONEINFO),
            timestamp_end=datetime(2022, 1, 2, 13, tzinfo=ZONEINFO),  # 3 h
        )
        response = logged_client.get(reverse("games:list_sessions"), {"sort": "-duration"})
        assert response.status_code == 200
        body = response.content.decode()
        assert body.index("Beta") < body.index("Alpha")  # longer session first

    def test_unknown_sort_emits_warning(self, logged_client, two_games):
        response = logged_client.get(reverse("games:list_sessions"), {"sort": "nope"})
        warnings = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("nope" in w for w in warnings)
