"""Game detail's Library section."""

import uuid

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from entries import end_entry_access, record_entry, remove_entry

from games.catalog_release import SHARED_GAME_RELEASE
from games.models import Edition, Game, Platform, PlayerGame, PlayerGameStatus

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


def test_a_row_per_live_copy_with_its_acts(client, owned_user, owned_library, graph):
    held = record_entry(owned_library, graph.release, access="borrowed", note="shelf")
    ended = end_entry_access(record_entry(owned_library, graph.release))
    gone = remove_entry(record_entry(owned_library, graph.release))
    client.force_login(owned_user)

    html = _page(client, graph.game)

    assert html.count("data-summary-row") == 2
    assert "Borrowed · Digital" in html
    assert "shelf" in html
    assert f"{reverse('games:end_library_entry', args=[held.pk])}?" in html
    assert f"{reverse('games:edit_library_entry_end', args=[ended.pk])}?" in html
    assert f"{reverse('games:resume_library_entry', args=[ended.pk])}?" in html
    assert reverse("games:end_library_entry_now", args=[held.pk]) in html
    assert reverse("games:resume_library_entry_now", args=[ended.pk]) in html
    assert "I no longer have it" in html
    assert "I have it again" in html
    assert f"{reverse('games:end_library_entry', args=[ended.pk])}?" not in html
    assert str(gone.pk) not in html
    assert "Returned" in html


def test_an_empty_section_offers_add(client, owned_user, graph):
    client.force_login(owned_user)

    html = _page(client, graph.game)

    assert "Nothing in your library yet." in html
    assert reverse("games:add_library_entry_now", args=[graph.game.pk]) in html


def test_a_named_edition_joins_the_row_label(client, owned_user, owned_library, graph):
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
    assert reverse("games:add_library_entry", args=[shared.pk]) not in html


def test_another_librarys_copies_are_absent(
    client, owned_user, owned_library, graph, django_user_model
):
    stranger = django_user_model.objects.create_user(username="stranger")
    entry = record_entry(owned_library, graph.release)
    client.force_login(stranger)

    response = client.get(graph.game.get_absolute_url())

    assert response.status_code == 404
    assert str(entry.pk) not in response.content.decode()


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
