"""Each switched view states its fact."""

import re

import pytest
from django.urls import reverse
from django.utils import timezone

from games.models import (
    Game,
    LibraryEvent,
    PlayerGame,
    PlayerGameStatus,
    PlayEvent,
    Purchase,
    Session,
)
from games.writes.playergame import new_correlation_id, record_facts, track_game

pytestmark = pytest.mark.untracked_games

GAME_PAYLOAD = {"name": "Outer Wilds", "status": "unplayed", "wikidata": ""}


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
        reverse("games:add_game"),
        {**GAME_PAYLOAD, "status": "completed", "mastered": "on"},
    )

    assert response.status_code == 302
    game = Game.objects.get(name="Outer Wilds")
    row = PlayerGame.objects.get(library=owned_library, game=game)
    assert (row.status, row.mastered) == (PlayerGameStatus.COMPLETED, True)


@pytest.mark.django_db(transaction=True)
def test_adding_a_game_records_one_creation_event(logged_in, owned_library):
    logged_in.post(reverse("games:add_game"), {**GAME_PAYLOAD, "status": "unplayed"})

    types = list(
        LibraryEvent.objects.filter(library=owned_library).values_list(
            "event_type", flat=True
        )
    )
    #: The row starts where the form says, so nothing changes.
    assert types == ["library.playergame.created"]


@pytest.mark.django_db(transaction=True)
def test_editing_a_games_status_records_the_event(logged_in, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds", status="u")

    logged_in.post(
        reverse("games:edit_game", args=[game.id]),
        {**GAME_PAYLOAD, "status": "played"},
    )

    assert PlayerGame.objects.get().status == PlayerGameStatus.PLAYED


@pytest.mark.django_db(transaction=True)
def test_the_edit_form_shows_the_games_current_status(
    logged_in, owned_user, tracked_game
):
    record_facts(
        owned_user,
        tracked_game,
        status=PlayerGameStatus.COMPLETED,
        correlation_id=new_correlation_id(),
    )

    response = logged_in.get(reverse("games:edit_game", args=[tracked_game.id]))

    #: They left Meta.fields, so the form seeds them itself —
    #: from the projection row, which is where the word lives.
    #: Read from the HTML: render_page() returns no context.
    assert '<option value="completed" selected>' in response.content.decode()


@pytest.mark.django_db(transaction=True)
def test_the_status_api_records_the_fact(logged_in, owned_library, tracked_game):
    #: The endpoint needs the tracked row.
    game = tracked_game

    response = logged_in.patch(
        f"/api/games/{game.id}/status",
        data={"status": "completed"},
        content_type="application/json",
    )

    assert response.status_code == 204
    assert PlayerGame.objects.get().status == PlayerGameStatus.COMPLETED


@pytest.mark.django_db(transaction=True)
def test_the_status_api_refuses_a_status_that_is_not_one(logged_in, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds", status="u")

    response = logged_in.patch(
        f"/api/games/{game.id}/status",
        data={"status": "zzz"},
        content_type="application/json",
    )

    #: Game.save() checks no choices, so the typed schema
    #: field is what refuses this before the view runs.
    assert response.status_code == 422
    game.refresh_from_db()
    assert game.status == "u"


@pytest.mark.django_db(transaction=True)
def test_a_failed_status_write_answers_409_with_a_toast(
    logged_in, owned_library, tracked_game, monkeypatch
):
    from games.writes.answers import CommandFailed

    game = tracked_game

    def refuse(*args, **kwargs):
        raise CommandFailed("Nothing was recorded; try again.", 409)

    monkeypatch.setattr("games.api.record_facts", refuse)
    response = logged_in.patch(
        f"/api/games/{game.id}/status",
        data={"status": "completed"},
        content_type="application/json",
    )

    assert response.status_code == 409
    #: The dropdown reverts on non-ok and shows the header.
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


@pytest.mark.django_db(transaction=True)
def test_editing_a_session_records_played_too(logged_in, owned_library, tracked_game):
    #: An edit binds the checkbox too, so it re-applies the
    #: flip. Session and PlayEvent derive their library.
    session = Session.objects.create(game=tracked_game, timestamp_start=timezone.now())

    logged_in.post(
        reverse("games:edit_session", args=[session.id]),
        _session_payload(tracked_game),
    )

    assert PlayerGame.objects.get().status == PlayerGameStatus.PLAYED


@pytest.mark.django_db(transaction=True)
def test_a_session_on_an_untracked_game_tracks_it_and_records_played(
    logged_in, owned_library
):
    #: A missing row is a defect.
    #: record_facts() tracks the game and records.
    game = Game.objects.create(library=owned_library, name="Outer Wilds", status="u")

    logged_in.post(reverse("games:add_session"), _session_payload(game))

    assert PlayerGame.objects.get().status == PlayerGameStatus.PLAYED


@pytest.mark.django_db(transaction=True)
def test_a_session_on_an_untracked_game_ignores_the_letter(logged_in, owned_library):
    #: The letter once held the session back.
    #: Nothing maintains it, so the row wins.
    game = Game.objects.create(library=owned_library, name="Outer Wilds", status="f")

    logged_in.post(reverse("games:add_session"), _session_payload(game))

    assert PlayerGame.objects.get().status == PlayerGameStatus.PLAYED


@pytest.mark.django_db
def test_the_box_comes_up_ticked(logged_in):
    #: A falsy initial would untick it everywhere.
    response = logged_in.get(reverse("games:add_session"))

    match = re.search(r'<input[^>]*name="mark_as_played"[^>]*>', response.text)
    assert match is not None
    assert "checked" in match.group(0)


@pytest.mark.django_db(transaction=True)
@pytest.mark.untracked_games
def test_an_unticked_box_records_nothing_and_tracks_nothing(logged_in, owned_library):
    #: The checkbox owns the tracking, not sessions.
    game = Game.objects.create(library=owned_library, name="Outer Wilds", status="u")

    logged_in.post(
        reverse("games:add_session"), _session_payload(game, mark_as_played="")
    )

    assert Session.objects.filter(game=game).exists()
    assert not PlayerGame.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_a_game_no_command_could_track_is_not_left_behind(
    logged_in, owned_library, monkeypatch
):
    #: A game with no projection row is off the list and 404s on its
    #: page, while its name goes on holding the unique constraint.
    monkeypatch.setattr(
        "games.views.game.track_game_for_request",
        lambda request, game, *, correlation_id: False,
    )

    logged_in.post(reverse("games:add_game"), GAME_PAYLOAD)

    assert not Game.objects.filter(name="Outer Wilds").exists()


@pytest.mark.django_db(transaction=True)
def test_a_session_leaves_a_finished_game_alone(
    logged_in, owned_user, owned_library, tracked_game
):
    record_facts(
        owned_user,
        tracked_game,
        status=PlayerGameStatus.COMPLETED,
        correlation_id=new_correlation_id(),
    )

    logged_in.post(reverse("games:add_session"), _session_payload(tracked_game))

    #: The guard reads the projection, as every read now does.
    assert PlayerGame.objects.get().status == PlayerGameStatus.COMPLETED


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


@pytest.mark.django_db(transaction=True)
def test_editing_a_play_event_records_completed_too(
    logged_in, owned_library, tracked_game
):
    play_event = PlayEvent.objects.create(game=tracked_game)

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
    #: One press is one act, however many games.
    assert len(correlation_ids) == 1


@pytest.mark.django_db(transaction=True)
def test_a_failed_refund_answers_409_and_swaps_nothing(
    logged_in, owned_user, owned_library, monkeypatch
):
    from games.writes.answers import CommandFailed

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
        raise CommandFailed("Nothing was recorded; try again.", 409)

    #: Patched where the call is made, not where it is named.
    monkeypatch.setattr("games.views.playergame_writes.record_facts", refuse)
    response = logged_in.post(reverse("games:refund_purchase", args=[purchase.id]))

    #: htmx swaps nothing outside 2xx, so the row stands.
    assert response.status_code == 409
    assert response.content == b""
    assert "show-toast" in response.headers["HX-Trigger"]
    purchase.refresh_from_db()
    assert purchase.date_refunded is None


@pytest.mark.django_db(transaction=True)
def test_a_failed_add_leaves_the_row_at_the_defaults(
    logged_in, owned_library, monkeypatch
):
    from games.writes.answers import CommandFailed

    def refuse(*args, **kwargs):
        raise CommandFailed("Nothing was recorded; try again.", 409)

    monkeypatch.setattr("games.views.playergame_writes.record_facts", refuse)
    response = logged_in.post(
        reverse("games:add_game"),
        {**GAME_PAYLOAD, "status": "completed", "mastered": "on"},
    )

    assert response.status_code == 302
    game = Game.objects.get(name="Outer Wilds")
    #: The failed command left the row untouched.
    row = PlayerGame.objects.get(library=owned_library, game=game)
    assert (row.status, row.mastered) == (PlayerGameStatus.UNPLAYED, False)


@pytest.mark.django_db(transaction=True)
def test_a_failed_edit_re_renders_the_form(logged_in, tracked_game, monkeypatch):
    from games.writes.answers import CommandFailed

    def refuse(*args, **kwargs):
        raise CommandFailed("Nothing was recorded; try again.", 409)

    monkeypatch.setattr("games.views.playergame_writes.record_facts", refuse)
    response = logged_in.post(
        reverse("games:edit_game", args=[tracked_game.id]),
        {**GAME_PAYLOAD, "status": "completed"},
    )

    #: A redirect would read as a save that landed.
    assert response.status_code == 200
    assert "show-toast" in response.headers["HX-Trigger"]
    row = PlayerGame.objects.get(game=tracked_game)
    assert row.status == PlayerGameStatus.UNPLAYED


@pytest.mark.django_db(transaction=True)
def test_a_partly_applied_refund_says_how_far_it_went(
    logged_in, owned_user, owned_library, monkeypatch
):
    from games.views import playergame_writes
    from games.writes.answers import CommandFailed

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

    record_facts = playergame_writes.record_facts
    calls = []

    def refuse_the_second(*args, **kwargs):
        calls.append(None)
        if len(calls) > 1:
            raise CommandFailed("Nothing was recorded; try again.", 409)
        return record_facts(*args, **kwargs)

    monkeypatch.setattr(playergame_writes, "record_facts", refuse_the_second)
    response = logged_in.post(reverse("games:refund_purchase", args=[purchase.id]))

    assert response.status_code == 409
    #: The first game is abandoned and stays that way, so the
    #: toast has to say so rather than claim nothing landed.
    assert "1 of 2 games were abandoned" in response.headers["HX-Trigger"]
    assert PlayerGame.objects.filter(status=PlayerGameStatus.ABANDONED).count() == 1
