"""The games list and the game page show the projection, not the catalog."""

import uuid
from html.parser import HTMLParser

import pytest
from django.urls import reverse
from django.utils import timezone

from games.models import Game, PlayerGame, PlayerGameStatus, Session
from games.writes.playergame import new_correlation_id, record_facts, track_game


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


def _history_markup(html: str) -> str:
    """The History section alone, heading through list."""
    start = html.index('id="history-container"')
    return html[start : html.index("</ul>", start)]


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


@pytest.mark.django_db
def test_an_archived_game_is_off_the_list(logged_in, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    PlayerGame.objects.filter(library=owned_library, game=game).update(
        archived_at=timezone.now()
    )

    response = logged_in.get(reverse("games:list_games"))

    assert "Outer Wilds" not in response.content.decode()


@pytest.mark.django_db
@pytest.mark.untracked_games
def test_the_edit_form_falls_back_to_the_catalog_with_no_row(logged_in, owned_library):
    #: An unseeded select posts its first option, which would record
    #: Unplayed over a game the catalog calls finished.
    game = Game.objects.create(
        library=owned_library, name="Outer Wilds", status="f", mastered=True
    )

    response = logged_in.get(reverse("games:edit_game", args=[game.pk]))

    body = response.content.decode()
    assert '<option value="completed" selected>' in body
    assert 'name="mastered"' in body and "checked" in body


@pytest.mark.django_db
def test_a_shared_games_page_shows_no_librarys_sessions(logged_in, owned_library):
    """A shared game's rows belong to nobody, so the page claims none.

    ``tracked_by()`` admits a shared game, whose reverse accessors reach
    every library that ever wrote against it. A Session is scoped through
    ``game.library``, so no library owns one on a shared game and every
    other view already shows none. The page agrees rather than being the
    one place that shows them all.

    A Purchase cannot reach here at all: ``validate_purchase_game_ownership``
    refuses to link one to a game of another library, and a shared game is
    of no library.
    """
    shared = Game.objects.create(library=None, name="Shared Title")
    PlayerGame.objects.create(
        pk=uuid.uuid7(),
        library=owned_library,
        game=shared,
        tracked_at=timezone.now(),
    )
    Session.objects.create(game=shared, timestamp_start=timezone.now(), note="Theirs")

    response = logged_in.get(shared.get_absolute_url())

    body = response.content.decode()
    assert response.status_code == 200
    assert "No sessions yet." in body


@pytest.mark.untracked_games
@pytest.mark.django_db(transaction=True)
def test_a_shared_games_page_shows_no_librarys_history(
    logged_in, owned_user, django_user_model
):
    """History is scoped like every other section of the page.

    ``game.status_changes`` reached every library that ever wrote
    against a shared game, so the page was the one place showing
    another library's transitions.
    """
    shared = Game.objects.create(library=None, name="Shared Title")
    other_user = django_user_model.objects.create_user(
        username="other-owner", password="p"
    )
    track_game(owned_user, shared, correlation_id=new_correlation_id())
    track_game(other_user, shared, correlation_id=new_correlation_id())
    record_facts(
        owned_user,
        shared,
        status=PlayerGameStatus.PLAYED,
        correlation_id=new_correlation_id(),
    )
    record_facts(
        other_user,
        shared,
        status=PlayerGameStatus.ABANDONED,
        correlation_id=new_correlation_id(),
    )

    #: Both words are on the page regardless: the status dropdown
    #: lists every one of them.
    history = _history_markup(logged_in.get(shared.get_absolute_url()).content.decode())

    assert "Played" in history
    assert "Abandoned" not in history


@pytest.mark.django_db
def test_an_owned_games_page_still_shows_its_own_rows(logged_in, owned_library):
    #: The scoping above must cost an owned game nothing.
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    Session.objects.create(game=game, timestamp_start=timezone.now())

    response = logged_in.get(game.get_absolute_url())

    assert "No sessions yet." not in response.content.decode()


@pytest.mark.django_db
def test_the_tracking_fixture_states_the_games_facts(owned_library):
    """The projection row says what the game says.

    The fixture stands in for `track_game()`. A row taking the column
    defaults would say `unplayed` for a finished game, and every
    filter on the projection would then select nothing.
    """
    game = Game.objects.create(
        library=owned_library,
        name="Outer Wilds",
        status=Game.Status.FINISHED,
        mastered=True,
    )

    tracked = PlayerGame.objects.get(library=owned_library, game=game)

    assert tracked.status == PlayerGameStatus.COMPLETED
    assert tracked.mastered is True
