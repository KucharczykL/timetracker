"""State the fact, then mirror the row."""

import pytest
from django.http import Http404

from games.events.idempotency import IdempotencyKeyMismatch
from games.events.retry import RetryBudgetExhausted
from games.models import Game, LibraryEvent, PlayerGame, PlayerGameStatus
from games.writes.playergame import (
    PlayerGameWriteFailed,
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
def test_a_status_reaches_the_event_the_projection_and_the_catalog(
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
    tracked_game.refresh_from_db()
    assert tracked_game.status == Game.Status.FINISHED


@pytest.mark.django_db(transaction=True)
def test_the_mirror_writes_the_fold_and_not_the_request(
    owned_user, owned_library, tracked_game
):
    #: A column moved behind the projection's back is repaired
    #: to what the events recorded, not to what this call asked.
    record_facts(
        owned_user,
        tracked_game,
        status=PlayerGameStatus.PLAYED,
        correlation_id=new_correlation_id(),
    )
    Game.objects.filter(pk=tracked_game.pk).update(status=Game.Status.RETIRED)

    record_facts(
        owned_user,
        tracked_game,
        status=PlayerGameStatus.PLAYED,
        correlation_id=new_correlation_id(),
    )

    tracked_game.refresh_from_db()
    assert tracked_game.status == Game.Status.PLAYED


@pytest.mark.django_db(transaction=True)
def test_an_untracked_game_heals_and_records(owned_user, owned_library):
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
    game.refresh_from_db()
    assert game.status == Game.Status.PLAYED


@pytest.mark.django_db(transaction=True)
def test_one_act_shares_one_correlation_id(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Tunic")
    correlation_id = new_correlation_id()

    record_facts(
        owned_user, game, status=PlayerGameStatus.PLAYED, correlation_id=correlation_id
    )

    #: The heal and its retry are one act, so one id.
    recorded = set(
        LibraryEvent.objects.filter(library=owned_library).values_list(
            "correlation_id", flat=True
        )
    )
    assert recorded == {correlation_id}


@pytest.mark.django_db(transaction=True)
def test_the_heal_does_not_loop(owned_user, owned_library, monkeypatch):
    game = Game.objects.create(library=owned_library, name="Tunic")

    #: The heal gives up on a second rejection, never recurses.
    monkeypatch.setattr(
        "games.writes.playergame.track_game", lambda *args, **kwargs: None
    )
    with pytest.raises(PlayerGameWriteFailed) as failure:
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
    with pytest.raises(PlayerGameWriteFailed) as failure:
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
    with pytest.raises(PlayerGameWriteFailed) as failure:
        record_facts(
            owned_user,
            tracked_game,
            status=PlayerGameStatus.PLAYED,
            correlation_id=new_correlation_id(),
        )
    assert failure.value.status_code == 409
    assert "try again" in failure.value.message


@pytest.mark.django_db(transaction=True)
def test_a_reused_key_over_different_input_says_it_will_never_work(
    owned_user, tracked_game, monkeypatch
):
    def mismatched(*args, **kwargs):
        raise IdempotencyKeyMismatch("that key belongs to another request")

    monkeypatch.setattr("games.writes.playergame.dispatch", mismatched)
    with pytest.raises(PlayerGameWriteFailed) as failure:
        record_facts(
            owned_user,
            tracked_game,
            status=PlayerGameStatus.PLAYED,
            correlation_id=new_correlation_id(),
        )
    assert failure.value.status_code == 409
    assert "cannot be retried" in failure.value.message
