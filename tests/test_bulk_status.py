"""One status stated on many games, and the Undo that states the one before."""

import html as html_module
import json
import uuid

import pytest
from django.contrib.messages import get_messages
from django.http import QueryDict
from django.urls import reverse
from session_rows import tracked_run

from games.bulk_actions import BULK_ACTIONS, AsksNothing, Control, RowOutcome
from games.bulk_removal import GAME_GONE
from games.bulk_status import (
    CHOOSE_A_STATUS,
    GAME_REMOVED,
    NOT_CHANGED_BY_THIS_BATCH,
    SET_STATUS,
)
from games.events.dispatch import CommandRejected, RowUnreadable
from games.models import Game, LibraryEvent, Platform, PlayerGame, PlayerGameStatus
from games.reads.events import batch_aggregate_ids
from games.reads.playergame_status import status_before
from games.views.bulk import (
    CHOICE_FIELD,
    PROGRESS_FIELD,
    STATEMENT_FIELD,
    TOKEN_FIELD,
)
from games.writes.answers import CommandFailed
from games.writes.playergame import (
    new_correlation_id,
    record_facts,
    remove_from_library,
    track_game,
)

pytestmark = [pytest.mark.untracked_games, pytest.mark.django_db(transaction=True)]

URL = reverse("games:run_bulk_action", args=[SET_STATUS.name])
STATUS_CHANGED = "library.playergame.status_changed"


@pytest.fixture
def client_in(client, owned_user):
    client.force_login(owned_user)
    return client


def _game(user, name, platform=None) -> Game:
    game = Game.objects.create(
        library=user.library, name=name, sort_name=name, platform=platform
    )
    track_game(user, game, correlation_id=new_correlation_id())
    return game


@pytest.fixture
def game(owned_user):
    return _game(owned_user, "Outer Wilds", Platform.objects.create(name="PC"))


@pytest.fixture
def second_game(owned_user):
    return _game(owned_user, "Tunic")


def _stated(user, game, status):
    record_facts(user, game, status=status, correlation_id=new_correlation_id())


def _status(game) -> PlayerGameStatus:
    return PlayerGameStatus(PlayerGame.objects.get(game=game).status)


def _tracked(game) -> PlayerGame:
    return PlayerGame.objects.get(game=game)


def some(*games) -> str:
    return json.dumps({"mode": "some", "keys": sorted(str(game.pk) for game in games)})


def posted(response) -> dict[str, str]:
    """The hidden fields the confirmation would submit."""
    markup = response.content.decode()
    fields: dict[str, str] = {}
    for name in (TOKEN_FIELD, PROGRESS_FIELD, STATEMENT_FIELD):
        marker = f'name="{name}" value="'
        if marker in markup:
            start = markup.index(marker) + len(marker)
            fields[name] = html_module.unescape(
                markup[start : markup.index('"', start)]
            )
    return fields


def _run(client, status, *games):
    """Confirm, pick the word, post through to the end."""
    confirmation = client.post(URL, {STATEMENT_FIELD: some(*games)})
    fields = posted(confirmation)
    fields[CHOICE_FIELD] = status
    return fields[TOKEN_FIELD], client.post(URL, fields)


def _undo(client, token):
    return client.post(reverse("games:undo_bulk_action", args=[token]))


def said(response) -> list[str]:
    return [str(message) for message in get_messages(response.wsgi_request)]


def _post(**fields: str) -> QueryDict:
    post = QueryDict(mutable=True)
    post.update(fields)
    return post


# ── The declaration ──────────────────────────────────────────────────────────


def test_the_act_is_declared():
    assert BULK_ACTIONS["playergame.set_status"] is SET_STATUS


def test_the_games_list_offers_set_status_before_remove(client_in, game):
    markup = client_in.get(reverse("games:list_games")).content.decode()

    assert markup.index("Set status…") < markup.index(
        reverse("games:run_bulk_action", args=["playergame.remove"])
    )


# ── The rows ─────────────────────────────────────────────────────────────────


def test_a_key_the_library_does_not_track_comes_out_lost(
    owned_library, game, django_user_model
):
    stranger = django_user_model.objects.create_user("stranger", password="p")
    theirs = _game(stranger, "Hades")

    resolution = SET_STATUS.resolve(owned_library, [game.pk, theirs.pk])

    assert [row.pk for row in resolution.rows] == [game.pk]
    assert [(refused.key, refused.sentence) for refused in resolution.refused] == [
        (str(theirs.pk), GAME_GONE)
    ]


def test_the_preview_names_platform_and_word(owned_user, owned_library, game):
    _stated(owned_user, game, PlayerGameStatus.PLAYED)
    (row,) = SET_STATUS.resolve(owned_library, [game.pk]).rows

    cells = [str(column.cell(row, None)) for column in SET_STATUS.preview]

    assert cells == ["Outer Wilds", "PC", "Played"]


# ── The question ─────────────────────────────────────────────────────────────


def test_no_rows_ask_nothing(owned_library):
    assert isinstance(
        SET_STATUS.choice.offer(owned_library, (), CHOICE_FIELD), AsksNothing
    )


def test_the_control_names_the_word_the_rows_hold(
    owned_user, owned_library, game, second_game
):
    _stated(owned_user, game, PlayerGameStatus.PLAYED)
    _stated(owned_user, second_game, PlayerGameStatus.PLAYED)
    rows = SET_STATUS.resolve(owned_library, [game.pk, second_game.pk]).rows

    offered = SET_STATUS.choice.offer(owned_library, rows, CHOICE_FIELD)

    assert isinstance(offered, Control)
    markup = str(offered.node)
    assert f'name="{CHOICE_FIELD}"' in markup
    assert "Now: Played" in markup


def test_differing_words_read_mixed(owned_user, owned_library, game, second_game):
    _stated(owned_user, game, PlayerGameStatus.PLAYED)
    rows = SET_STATUS.resolve(owned_library, [game.pk, second_game.pk]).rows

    offered = SET_STATUS.choice.offer(owned_library, rows, CHOICE_FIELD)

    assert "Now: mixed" in str(offered.node)


@pytest.mark.parametrize("word", ["", "finished"])
def test_settling_refuses_anything_but_a_word(owned_library, word):
    with pytest.raises(CommandRejected) as refused:
        SET_STATUS.choice.settle(owned_library, _post(**{CHOICE_FIELD: word}))

    assert refused.value.sentence == CHOOSE_A_STATUS


def test_settling_answers_the_word(owned_library):
    settled = SET_STATUS.choice.settle(
        owned_library, _post(**{CHOICE_FIELD: "completed"})
    )

    assert settled == "completed"


# ── Forward ──────────────────────────────────────────────────────────────────


def test_every_selected_game_states_the_word_under_one_batch(
    client_in, owned_library, game, second_game
):
    token, _ = _run(client_in, "completed", game, second_game)

    assert _status(game) == _status(second_game) == PlayerGameStatus.COMPLETED
    assert set(batch_aggregate_ids(owned_library, uuid.UUID(token), "playergame")) == {
        _tracked(game).pk,
        _tracked(second_game).pk,
    }


def test_a_game_that_states_the_word_already_is_unchanged(owned_user, game):
    _stated(owned_user, game, PlayerGameStatus.COMPLETED)

    outcome = SET_STATUS.run(
        owned_user,
        game,
        choice="completed",
        idempotency_key=str(uuid.uuid7()),
        correlation_id=uuid.uuid7(),
    )

    assert outcome is RowOutcome.UNCHANGED


def test_a_choice_that_is_no_word_is_a_defect(owned_user, game):
    with pytest.raises(CommandFailed) as failed:
        SET_STATUS.run(
            owned_user,
            game,
            choice=None,
            idempotency_key=str(uuid.uuid7()),
            correlation_id=uuid.uuid7(),
        )

    assert isinstance(failed.value.__cause__, RowUnreadable)
    assert _status(game) == PlayerGameStatus.UNPLAYED


# ── Backward ─────────────────────────────────────────────────────────────────


def test_an_undo_states_the_word_before_the_batch(
    client_in, owned_user, game, second_game
):
    _stated(owned_user, game, PlayerGameStatus.PLAYED)
    token, _ = _run(client_in, "completed", game, second_game)

    _undo(client_in, token)

    assert _status(game) == PlayerGameStatus.PLAYED
    #: A creation states no word: the row started Unplayed.
    assert _status(second_game) == PlayerGameStatus.UNPLAYED


def test_an_undo_pressed_twice_is_already_so(client_in, game):
    token, _ = _run(client_in, "completed", game)
    _undo(client_in, token)
    events = LibraryEvent.objects.filter(event_type=STATUS_CHANGED).count()

    again = _undo(client_in, token)

    assert _status(game) == PlayerGameStatus.UNPLAYED
    assert LibraryEvent.objects.filter(event_type=STATUS_CHANGED).count() == events
    assert any("already" in sentence for sentence in said(again))


def test_an_undo_states_the_earlier_word_over_a_later_one(client_in, owned_user, game):
    token, _ = _run(client_in, "completed", game)
    _stated(owned_user, game, PlayerGameStatus.ABANDONED)

    _undo(client_in, token)

    assert _status(game) == PlayerGameStatus.UNPLAYED


def _inverse(user, game, undoes):
    return SET_STATUS.inverse(
        user,
        _tracked(game).pk,
        undoes=undoes,
        idempotency_key=str(uuid.uuid7()),
        correlation_id=uuid.uuid7(),
    )


def test_an_undo_refuses_a_removed_game(client_in, owned_user, game):
    token, _ = _run(client_in, "completed", game)
    remove_from_library(owned_user, game, correlation_id=new_correlation_id())

    with pytest.raises(CommandFailed) as refused:
        _inverse(owned_user, game, uuid.UUID(token))

    assert refused.value.message == GAME_REMOVED


def test_an_undo_refuses_a_game_the_batch_did_not_change(owned_user, game):
    with pytest.raises(CommandFailed) as refused:
        _inverse(owned_user, game, uuid.uuid7())

    assert refused.value.message == NOT_CHANGED_BY_THIS_BATCH


# ── The reader ───────────────────────────────────────────────────────────────


def test_the_reader_answers_none_for_another_batch(owned_user, owned_library, game):
    _stated(owned_user, game, PlayerGameStatus.PLAYED)

    assert status_before(owned_library, _tracked(game).pk, uuid.uuid7()) is None


def test_the_reader_reads_the_batch_it_is_asked(owned_user, owned_library, game):
    first, second = new_correlation_id(), new_correlation_id()
    record_facts(owned_user, game, status=PlayerGameStatus.PLAYED, correlation_id=first)
    record_facts(
        owned_user, game, status=PlayerGameStatus.COMPLETED, correlation_id=second
    )

    key = _tracked(game).pk
    assert status_before(owned_library, key, first) == PlayerGameStatus.UNPLAYED
    assert status_before(owned_library, key, second) == PlayerGameStatus.PLAYED


def test_a_stream_with_no_creation_is_a_defect(owned_user, owned_library):
    """A projection row written by hand has no stream behind it."""
    game = Game.objects.create(library=owned_library, name="Written by hand")
    tracked_run(owned_library, game)
    batch = new_correlation_id()
    record_facts(owned_user, game, status=PlayerGameStatus.PLAYED, correlation_id=batch)

    with pytest.raises(RowUnreadable):
        status_before(owned_library, _tracked(game).pk, batch)
