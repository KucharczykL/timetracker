"""Every switched view states its fact as a command."""

import pytest
from django.urls import reverse

from games.models import (
    Game,
    GameStatusChange,
    LibraryEvent,
    PlayerGame,
    PlayerGameStatus,
)

GAME_PAYLOAD = {"name": "Outer Wilds", "status": "u", "wikidata": ""}


@pytest.fixture
def logged_in(client, owned_user):
    client.force_login(owned_user)
    return client


@pytest.mark.django_db(transaction=True)
def test_adding_a_game_tracks_it_and_records_its_facts(logged_in, owned_library):
    response = logged_in.post(
        reverse("games:add_game"), {**GAME_PAYLOAD, "status": "f", "mastered": "on"}
    )

    assert response.status_code == 302
    game = Game.objects.get(name="Outer Wilds")
    assert (game.status, game.mastered) == ("f", True)
    row = PlayerGame.objects.get(library=owned_library, game=game)
    assert (row.status, row.mastered) == (PlayerGameStatus.COMPLETED, True)


@pytest.mark.django_db(transaction=True)
def test_a_game_created_as_finished_records_no_status_change(logged_in):
    #: The pre_save audit signal returns early when no previous row exists,
    #: so a game created at a non-default status records no transition today.
    #: Assigning the two values before the first save keeps that exactly true.
    logged_in.post(reverse("games:add_game"), {**GAME_PAYLOAD, "status": "f"})

    assert GameStatusChange.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_adding_a_game_records_one_creation_event(logged_in, owned_library):
    logged_in.post(reverse("games:add_game"), {**GAME_PAYLOAD, "status": "u"})

    types = list(
        LibraryEvent.objects.filter(library=owned_library).values_list(
            "event_type", flat=True
        )
    )
    #: The row is created at the state the form states, so the composite
    #: finds both facts already holding and appends nothing.
    assert types == ["library.playergame.created"]


@pytest.mark.django_db(transaction=True)
def test_editing_a_games_status_records_the_event_and_the_audit_row(
    logged_in, owned_library
):
    game = Game.objects.create(library=owned_library, name="Outer Wilds", status="u")

    logged_in.post(
        reverse("games:edit_game", args=[game.id]),
        {**GAME_PAYLOAD, "status": "p"},
    )

    game.refresh_from_db()
    assert game.status == "p"
    assert PlayerGame.objects.get().status == PlayerGameStatus.PLAYED
    #: Legacy history is unchanged by the cutover.
    assert GameStatusChange.objects.filter(game=game, new_status="p").count() == 1


@pytest.mark.django_db(transaction=True)
def test_the_edit_form_shows_the_games_current_status(logged_in, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds", status="f")

    response = logged_in.get(reverse("games:edit_game", args=[game.id]))

    #: status and mastered left Meta.fields, so ModelForm no longer seeds
    #: their initial from the instance and the form must do it. Asserted on
    #: the HTML rather than a form object: the view renders through
    #: render_page(), which returns no template context to read.
    assert '<option value="f" selected>' in response.content.decode()
