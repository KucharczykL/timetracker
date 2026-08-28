"""Every switched view states its fact as a command."""

import pytest
from django.urls import reverse
from django.utils import timezone

from games.models import (
    Game,
    GameStatusChange,
    LibraryEvent,
    PlayerGame,
    PlayerGameStatus,
    PlayEvent,
    Purchase,
    Session,
)
from games.writes.playergame import new_correlation_id, track_game

GAME_PAYLOAD = {"name": "Outer Wilds", "status": "u", "wikidata": ""}


@pytest.fixture
def logged_in(client, owned_user):
    client.force_login(owned_user)
    return client


@pytest.fixture
def tracked_game(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds", status="u")
    track_game(owned_user, game, correlation_id=new_correlation_id())
    return game


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


@pytest.mark.django_db(transaction=True)
def test_the_status_api_records_the_fact(logged_in, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds", status="u")

    response = logged_in.patch(
        f"/api/games/{game.id}/status",
        data={"status": "f"},
        content_type="application/json",
    )

    assert response.status_code == 204
    assert PlayerGame.objects.get().status == PlayerGameStatus.COMPLETED
    game.refresh_from_db()
    assert game.status == "f"


@pytest.mark.django_db(transaction=True)
def test_the_status_api_refuses_a_status_that_is_not_one(logged_in, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds", status="u")

    response = logged_in.patch(
        f"/api/games/{game.id}/status",
        data={"status": "zzz"},
        content_type="application/json",
    )

    #: Today the value reaches the column: Game.save() calls clean() and not
    #: full_clean(), and neither checks choices. Typing the schema field is
    #: what makes Ninja refuse it before the view runs.
    assert response.status_code == 422
    game.refresh_from_db()
    assert game.status == "u"


@pytest.mark.django_db(transaction=True)
def test_a_failed_status_write_answers_409_with_a_toast(
    logged_in, owned_library, monkeypatch
):
    from games.writes.playergame import PlayerGameWriteFailed

    game = Game.objects.create(library=owned_library, name="Outer Wilds", status="u")

    def refuse(*args, **kwargs):
        raise PlayerGameWriteFailed("Nothing was recorded; try again.", 409)

    monkeypatch.setattr("games.api.record_facts", refuse)
    response = logged_in.patch(
        f"/api/games/{game.id}/status",
        data={"status": "f"},
        content_type="application/json",
    )

    assert response.status_code == 409
    #: The dropdown reverts itself on any non-ok response and shows whatever
    #: the trigger header carries, so the sentence must ride along.
    assert "show-toast" in response.headers["HX-Trigger"]


def _session_payload(game, **overrides):
    started = timezone.now().replace(microsecond=0)
    return {
        "game": str(game.id),
        "timestamp_start": started.strftime("%Y-%m-%d %H:%M"),
        "timestamp_start_timezone": "",
        "timestamp_end": "",
        "timestamp_end_timezone": "",
        "duration_manual": "",
        "note": "",
        "mark_as_played": "on",
        **overrides,
    }


@pytest.mark.django_db(transaction=True)
def test_adding_a_session_records_played(logged_in, owned_library, tracked_game):
    logged_in.post(reverse("games:add_session"), _session_payload(tracked_game))

    assert PlayerGame.objects.get().status == PlayerGameStatus.PLAYED
    tracked_game.refresh_from_db()
    assert tracked_game.status == "p"


@pytest.mark.django_db(transaction=True)
def test_editing_a_session_records_played_too(logged_in, owned_library, tracked_game):
    #: The checkbox is a field of the form and an edit binds it, so an edit
    #: re-applies the flip today. Covering only the add view would be a
    #: silent regression rather than a smaller change.
    #: Session and PlayEvent take no library kwarg; each derives it from
    #: the game.
    session = Session.objects.create(game=tracked_game, timestamp_start=timezone.now())
    Game.objects.filter(pk=tracked_game.pk).update(status="u")

    logged_in.post(
        reverse("games:edit_session", args=[session.id]),
        _session_payload(tracked_game),
    )

    assert PlayerGame.objects.get().status == PlayerGameStatus.PLAYED


@pytest.mark.django_db(transaction=True)
def test_a_session_leaves_a_finished_game_alone(logged_in, owned_library, tracked_game):
    Game.objects.filter(pk=tracked_game.pk).update(status="f")

    logged_in.post(reverse("games:add_session"), _session_payload(tracked_game))

    #: The guard reads the catalog, because every read reads the catalog
    #: until #678. Without it a completed game falls back to played.
    tracked_game.refresh_from_db()
    assert tracked_game.status == "f"


@pytest.mark.django_db(transaction=True)
def test_adding_a_play_event_records_completed(logged_in, owned_library, tracked_game):
    logged_in.post(
        reverse("games:add_playevent"),
        {
            "game": str(tracked_game.id),
            "started": "",
            "ended": "",
            "note": "",
            "mark_as_finished": "on",
        },
    )

    assert PlayerGame.objects.get().status == PlayerGameStatus.COMPLETED
    tracked_game.refresh_from_db()
    assert tracked_game.status == "f"


@pytest.mark.django_db(transaction=True)
def test_editing_a_play_event_records_completed_too(
    logged_in, owned_library, tracked_game
):
    play_event = PlayEvent.objects.create(game=tracked_game)
    Game.objects.filter(pk=tracked_game.pk).update(status="u")

    logged_in.post(
        reverse("games:edit_playevent", args=[play_event.id]),
        {
            "game": str(tracked_game.id),
            "started": "",
            "ended": "",
            "note": "",
            "mark_as_finished": "on",
        },
    )

    assert PlayerGame.objects.get().status == PlayerGameStatus.COMPLETED


@pytest.mark.django_db(transaction=True)
def test_refunding_abandons_every_game_under_one_correlation_id(
    logged_in, owned_user, owned_library
):
    games = []
    for name in ("Outer Wilds", "Tunic"):
        game = Game.objects.create(library=owned_library, name=name, status="p")
        track_game(owned_user, game, correlation_id=new_correlation_id())
        games.append(game)
    purchase = Purchase.objects.create(
        library=owned_library,
        price=0,
        price_currency="CZK",
        date_purchased=timezone.now(),
    )
    purchase.games.set(games)

    response = logged_in.post(reverse("games:refund_purchase", args=[purchase.id]))

    assert response.status_code == 200
    assert set(PlayerGame.objects.values_list("status", flat=True)) == {
        PlayerGameStatus.ABANDONED
    }
    correlation_ids = set(
        LibraryEvent.objects.filter(
            event_type="library.playergame.status_changed"
        ).values_list("correlation_id", flat=True)
    )
    #: One button press is one act, whatever number of games it moves.
    assert len(correlation_ids) == 1


@pytest.mark.django_db(transaction=True)
def test_a_failed_refund_answers_409_and_swaps_nothing(
    logged_in, owned_user, owned_library, monkeypatch
):
    from games.writes.playergame import PlayerGameWriteFailed

    game = Game.objects.create(library=owned_library, name="Outer Wilds", status="p")
    track_game(owned_user, game, correlation_id=new_correlation_id())
    purchase = Purchase.objects.create(
        library=owned_library,
        price=0,
        price_currency="CZK",
        date_purchased=timezone.now(),
    )
    purchase.games.set([game])

    def refuse(*args, **kwargs):
        raise PlayerGameWriteFailed("Nothing was recorded; try again.", 409)

    #: The view calls record_facts_for_request, which is the one caller of
    #: record_facts, so the patch goes where the call is made.
    monkeypatch.setattr("games.views.playergame_writes.record_facts", refuse)
    response = logged_in.post(reverse("games:refund_purchase", args=[purchase.id]))

    #: htmx swaps nothing outside 2xx, so the row keeps what it shows and
    #: the modal stays open. A redirect would swap a whole page into a cell.
    assert response.status_code == 409
    assert response.content == b""
    assert "show-toast" in response.headers["HX-Trigger"]
    purchase.refresh_from_db()
    assert purchase.date_refunded is None
