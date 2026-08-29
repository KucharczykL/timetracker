"""State the fact; leave the catalog alone."""

import pytest
from django.http import Http404

from games.events.retry import RetryBudgetExhausted
from games.models import Game, LibraryEvent, PlayerGame, PlayerGameStatus
from games.writes.answers import CommandFailed
from games.writes.playergame import (
    new_correlation_id,
    record_facts,
    track_game,
)

pytestmark = pytest.mark.untracked_games


@pytest.fixture
def other_user(django_user_model, db):
    return django_user_model.objects.create_user(username="other-owner", password="p")


@pytest.fixture
def tracked_game(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track_game(owned_user, game, correlation_id=new_correlation_id())
    return game


@pytest.mark.django_db(transaction=True)
def test_a_status_reaches_the_event_and_the_projection(
    owned_user, owned_library, tracked_game
):
    record_facts(
        owned_user,
        tracked_game,
        status=PlayerGameStatus.COMPLETED,
        correlation_id=new_correlation_id(),
    )

    event = LibraryEvent.objects.get(
        library=owned_library, event_type="library.playergame.status_changed"
    )
    assert event.payload == {"status": "completed"}
    assert PlayerGame.objects.get().status == PlayerGameStatus.COMPLETED


@pytest.mark.django_db(transaction=True)
def test_the_catalog_column_is_left_where_it_stood(owned_user, owned_library):
    #: Nothing copies the row onto the game.
    game = Game.objects.create(library=owned_library, name="Tunic", status="u")
    track_game(owned_user, game, correlation_id=new_correlation_id())

    record_facts(
        owned_user,
        game,
        status=PlayerGameStatus.COMPLETED,
        correlation_id=new_correlation_id(),
    )

    assert PlayerGame.objects.get().status == PlayerGameStatus.COMPLETED
    game.refresh_from_db()
    assert game.status == "u"


@pytest.mark.django_db(transaction=True)
def test_an_untracked_game_is_tracked_then_recorded(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Tunic")

    record_facts(
        owned_user,
        game,
        status=PlayerGameStatus.PLAYED,
        correlation_id=new_correlation_id(),
    )

    types = list(
        LibraryEvent.objects.filter(library=owned_library)
        .order_by("sequence")
        .values_list("event_type", flat=True)
    )
    assert types == ["library.playergame.created", "library.playergame.status_changed"]


@pytest.mark.django_db(transaction=True)
def test_one_act_shares_one_correlation_id(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Tunic")
    correlation_id = new_correlation_id()

    record_facts(
        owned_user, game, status=PlayerGameStatus.PLAYED, correlation_id=correlation_id
    )

    #: Tracking and the retry are one act, so one id.
    recorded = set(
        LibraryEvent.objects.filter(library=owned_library).values_list(
            "correlation_id", flat=True
        )
    )
    assert recorded == {correlation_id}


@pytest.mark.django_db(transaction=True)
def test_tracking_first_does_not_loop(owned_user, owned_library, monkeypatch):
    game = Game.objects.create(library=owned_library, name="Tunic")

    #: A second rejection stops it. It never recurses.
    monkeypatch.setattr(
        "games.writes.playergame.track_game", lambda *args, **kwargs: None
    )
    with pytest.raises(CommandFailed) as failure:
        record_facts(
            owned_user,
            game,
            status=PlayerGameStatus.PLAYED,
            correlation_id=new_correlation_id(),
        )
    assert failure.value.status_code == 409


@pytest.mark.django_db(transaction=True)
def test_another_librarys_game_is_refused(other_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")

    #: The actor names the library, so this one gets their own
    #: and cannot track the game. The views answer 404 first.
    with pytest.raises(CommandFailed) as failure:
        track_game(other_user, game, correlation_id=new_correlation_id())
    assert failure.value.status_code == 409
    assert not LibraryEvent.objects.filter(library=other_user.library).exists()


@pytest.mark.django_db(transaction=True)
def test_an_actor_who_may_not_command_is_not_found(owned_user, tracked_game):
    #: A 404: an unreachable object is absent, not forbidden.
    owned_user.is_active = False
    owned_user.save(update_fields=["is_active"])

    with pytest.raises(Http404):
        record_facts(
            owned_user,
            tracked_game,
            status=PlayerGameStatus.PLAYED,
            correlation_id=new_correlation_id(),
        )


@pytest.mark.django_db(transaction=True)
def test_an_exhausted_retry_budget_asks_the_player_to_try_again(
    owned_user, tracked_game, monkeypatch
):
    def exhausted(*args, **kwargs):
        raise RetryBudgetExhausted(3)

    monkeypatch.setattr("games.writes.playergame.dispatch", exhausted)
    with pytest.raises(CommandFailed) as failure:
        record_facts(
            owned_user,
            tracked_game,
            status=PlayerGameStatus.PLAYED,
            correlation_id=new_correlation_id(),
        )
    assert failure.value.status_code == 409
    assert "try again" in failure.value.message
