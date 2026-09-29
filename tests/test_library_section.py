"""Game detail's Library section."""

import uuid

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from entries import end_entry_access, record_entry, remove_entry

from games.catalog_release import SHARED_GAME_RELEASE
from games.models import Edition, Game, Platform, PlayerGame, PlayerGameStatus
from games.views.library_cards import copy_anchor

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def graph(owned_library, stated_graph):
    ps5 = Platform.objects.create(name="PS5", group="Sony")
    return stated_graph(
        Game(name="Tunic", library=owned_library), owned_library, platform=ps5
    )


def _page(client, game, query: str = "") -> str:
    response = client.get(game.get_absolute_url() + query)
    assert response.status_code == 200
    return response.content.decode()


def test_a_card_per_live_copy(client, owned_user, owned_library, graph):
    held = record_entry(owned_library, graph.release, access="borrowed")
    ended = end_entry_access(record_entry(owned_library, graph.release))
    gone = remove_entry(record_entry(owned_library, graph.release))
    client.force_login(owned_user)

    html = _page(client, graph.game)

    assert f'id="{copy_anchor(held.pk)}"' in html
    assert f'id="{copy_anchor(ended.pk)}"' in html
    assert copy_anchor(gone.pk) not in html
    assert "Borrowed · Digital" in html
    assert "Returned" in html
    assert "Resume" in html
    assert "End access" in html


def test_an_empty_section_offers_add(client, owned_user, graph):
    client.force_login(owned_user)

    html = _page(client, graph.game)

    assert "Nothing in your library yet." in html
    assert "Add to library" in html


def test_a_named_edition_joins_the_card_line(client, owned_user, owned_library, graph):
    Edition.objects.filter(pk=graph.edition.pk).update(name="Deluxe")
    record_entry(owned_library, graph.release)
    client.force_login(owned_user)

    assert "PS5 · Deluxe" in _page(client, graph.game)


def test_a_shared_game_without_a_release_states_the_sentence(
    client, owned_user, owned_library
):
    shared = Game.objects.create(name="Celeste")
    PlayerGame.objects.create(
        pk=uuid.uuid7(),
        library=owned_library,
        game=shared,
        tracked_at=timezone.now(),
        status=PlayerGameStatus.UNPLAYED,
        mastered=False,
    )
    client.force_login(owned_user)

    html = _page(client, shared)

    assert SHARED_GAME_RELEASE in html
    assert "Add to library" not in html


def test_the_query_opens_that_disclosure(client, owned_user, owned_library, graph):
    entry = record_entry(owned_library, graph.release)
    client.force_login(owned_user)

    html = _page(client, graph.game, f"?library=end&copy={entry.pk}")

    card = html[html.index(f'id="{copy_anchor(entry.pk)}"') :]
    assert "<details open" in card.split("End access")[0].rsplit("Edit", 1)[1]


def test_a_bad_query_opens_nothing(client, owned_user, owned_library, graph):
    record_entry(owned_library, graph.release)
    client.force_login(owned_user)

    html = _page(client, graph.game, "?library=end&copy=nonsense")

    assert "<details open" not in html


def test_another_librarys_copies_are_absent(
    client, owned_user, owned_library, graph, django_user_model
):
    stranger = django_user_model.objects.create_user(username="stranger")
    entry = record_entry(owned_library, graph.release)
    client.force_login(stranger)

    response = client.get(graph.game.get_absolute_url())

    assert response.status_code == 404
    assert copy_anchor(entry.pk) not in response.content.decode()


def _count_queries(client, game) -> int:
    with CaptureQueriesContext(connection) as captured:
        _page(client, game)
    return len(captured)


def test_the_query_count_holds_over_more_copies(
    client, owned_user, owned_library, graph
):
    record_entry(owned_library, graph.release)
    client.force_login(owned_user)
    _page(client, graph.game)
    one = _count_queries(client, graph.game)

    for _ in range(3):
        end_entry_access(record_entry(owned_library, graph.release))
    four = _count_queries(client, graph.game)

    assert four == one
