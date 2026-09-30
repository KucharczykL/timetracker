import json
from html import escape

import pytest
from django.urls import reverse

#: The act table imports `bulk_games`; loading it first breaks the cycle.
import games.bulk_actions  # noqa: F401
from games.bulk_games import game_scope
from games.filters import FindFilter, GameFilter, filter_url
from games.list_columns import hidden_columns
from games.models import Game, GameKind
from games.views.game import game_list_columns, games_for_list

pytestmark = pytest.mark.django_db


@pytest.fixture
def kinds(owned_library):
    base = Game.objects.create(library=owned_library, name="Base")
    dlc = Game.objects.create(library=owned_library, name="Base DLC")
    expansion = Game.objects.create(library=owned_library, name="Base Expansion")
    Game.objects.filter(pk=dlc.pk).update(kind=GameKind.DLC, parent=base)
    Game.objects.filter(pk=expansion.pk).update(kind=GameKind.EXPANSION, parent=base)
    return {"base": base, "dlc": dlc, "expansion": expansion}


def _listed(library, game_filter: GameFilter | None) -> set[str]:
    listed = games_for_list(library, game_filter=game_filter, find=FindFilter())
    return {game.name for game in listed.sort.queryset}


def _from_json(game_filter: GameFilter) -> GameFilter:
    restored = GameFilter.from_json(json.loads(json.dumps(game_filter.to_json())))
    assert restored is not None
    return restored


def test_the_list_hides_addons_by_default(owned_library, kinds):
    assert _listed(owned_library, None) == {"Base"}
    assert _listed(owned_library, GameFilter.where(name__contains="Base")) == {"Base"}


@pytest.mark.parametrize(
    ("game_filter", "expected"),
    [
        (GameFilter.where(kind=["dlc"]), {"Base DLC"}),
        (GameFilter(NOT=[GameFilter.where(kind=["dlc"])]), {"Base", "Base Expansion"}),
        (
            GameFilter(OR=[GameFilter.where(kind=["expansion"])]),
            {"Base Expansion"},
        ),
        (GameFilter.every_kind(), {"Base", "Base DLC", "Base Expansion"}),
    ],
)
def test_a_filter_naming_kind_lists_every_kind(
    owned_library, kinds, game_filter, expected
):
    assert _listed(owned_library, _from_json(game_filter)) == expected


def test_a_filter_naming_the_parent_lists_its_addons(owned_library, kinds):
    by_parent = GameFilter.where(parent=[kinds["base"].pk])

    assert _listed(owned_library, by_parent) == {"Base DLC", "Base Expansion"}


@pytest.mark.parametrize(
    "game_filter",
    [None, GameFilter.where(kind=["dlc"]), GameFilter.where(name__contains="Base")],
)
def test_the_bulk_scope_and_the_live_count_match_the_list(
    client, owned_user, owned_library, kinds, game_filter
):
    filter_json = "" if game_filter is None else json.dumps(game_filter.to_json())
    listed = _listed(owned_library, game_filter)

    scoped = {game.name for game in game_scope(owned_library, filter_json)}
    client.force_login(owned_user)
    counted = client.get(
        "/api/filter/count", {"model": "game", "filter": filter_json}
    ).json()["count"]

    assert scoped == listed
    assert counted == len(listed)


def test_names_addon_fields_reads_every_level():
    assert not GameFilter.where(name__contains="x").names_addon_fields()
    assert GameFilter(NOT=[GameFilter.where(kind=["dlc"])]).names_addon_fields()
    assert GameFilter(
        AND=[GameFilter(OR=[GameFilter.where(parent=[])])]
    ).names_addon_fields()


def test_the_kind_column_starts_hidden_and_can_be_shown(owned_user):
    columns = game_list_columns("Playtime")
    kind = next(column for column in columns if column.key == "kind")

    assert kind.hidden_by_default
    assert "kind" in hidden_columns(owned_user, "games", columns)


def test_the_kind_facet_renders_on_the_list(client, owned_user, kinds):
    client.force_login(owned_user)
    page = client.get(reverse("games:list_games")).content.decode()

    assert "quick-kind" in page


def test_every_library_page_link_into_the_list_states_every_kind(client, owned_user):
    client.force_login(owned_user)
    page = client.get(reverse("games:library")).content.decode()
    every_game = escape(filter_url(GameFilter.every_kind()))

    #: The card, the row's figure and its Browse.
    assert page.count(f'href="{every_game}"') >= 3
    assert f'href="{reverse("games:list_games")}"' not in page
