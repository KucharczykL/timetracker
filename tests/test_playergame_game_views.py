"""The games list and the game page show the projection, not the catalog."""

import uuid
from html.parser import HTMLParser

import pytest
from django.urls import reverse
from django.utils import timezone

from games.models import Game, PlayerGame, PlayerGameStatus


def _selected_status(html: str) -> str | None:
    """The one status the listbox marks current.

    Every status is on the page, because the dropdown lists them all.
    Only the selected one says which the page believes.
    """

    class _Options(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.selected: str | None = None

        def handle_starttag(
            self, tag: str, attrs: list[tuple[str, str | None]]
        ) -> None:
            attributes = dict(attrs)
            if "data-option" in attributes and attributes.get("aria-selected") == (
                "true"
            ):
                self.selected = attributes.get("data-value")

    parser = _Options()
    parser.feed(html)
    return parser.selected


@pytest.fixture
def logged_in(client, owned_user):
    client.force_login(owned_user)
    return client


@pytest.fixture
def disagreeing_game(owned_library):
    """The projection says Completed; the catalog still says unplayed."""
    game = Game.objects.create(
        library=owned_library, name="Outer Wilds", status="u", mastered=False
    )
    PlayerGame.objects.filter(library=owned_library, game=game).update(
        status=PlayerGameStatus.COMPLETED, mastered=True
    )
    return game


@pytest.mark.django_db
def test_the_list_shows_the_projection_status(logged_in, disagreeing_game):
    response = logged_in.get(reverse("games:list_games"))

    assert response.status_code == 200
    assert _selected_status(response.content.decode()) == PlayerGameStatus.COMPLETED


@pytest.mark.django_db
def test_the_page_shows_the_projection_status(logged_in, disagreeing_game):
    response = logged_in.get(disagreeing_game.get_absolute_url())

    assert response.status_code == 200
    assert _selected_status(response.content.decode()) == PlayerGameStatus.COMPLETED


@pytest.mark.django_db
def test_the_page_shows_the_projection_mastery(logged_in, disagreeing_game):
    response = logged_in.get(disagreeing_game.get_absolute_url())

    assert "👑" in response.content.decode()


@pytest.mark.django_db
@pytest.mark.untracked_games
def test_an_untracked_game_is_off_the_list(logged_in, owned_library):
    Game.objects.create(library=owned_library, name="Outer Wilds")

    response = logged_in.get(reverse("games:list_games"))

    assert "Outer Wilds" not in response.content.decode()


@pytest.mark.django_db
def test_a_removed_game_is_off_the_list(logged_in, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    Game.objects.filter(pk=game.pk).update(tombstoned_at=timezone.now())

    response = logged_in.get(reverse("games:list_games"))

    assert "Outer Wilds" not in response.content.decode()


@pytest.mark.django_db
def test_a_shared_game_this_library_tracks_is_on_the_list(logged_in, owned_library):
    shared = Game.objects.create(library=None, name="Shared Title")
    PlayerGame.objects.create(
        pk=uuid.uuid7(),
        library=owned_library,
        game=shared,
        tracked_at=timezone.now(),
    )

    response = logged_in.get(reverse("games:list_games"))

    assert "Shared Title" in response.content.decode()
