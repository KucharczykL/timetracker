"""Facts stated on many games, and the Undo that states the ones before."""

import html as html_module
import json
import logging
import uuid
from dataclasses import fields as dataclass_fields

import pytest
from bulk_posts import said
from django.http import Http404, QueryDict
from django.urls import reverse
from session_rows import tracked_run
from tri_state_markup import held_word

from games.bulk_actions import BULK_ACTIONS
from games.bulk_edit import STATEMENT_UNREADABLE
from games.bulk_game_edit import (
    EDIT,
    GAME_REMOVED,
    NOT_EDITED_BY_THIS_BATCH,
    NOTHING_STATED,
    GameEditJson,
    GameEditStatement,
)
from games.bulk_games import GAME_GONE
from games.bulk_parts import AsksNothing, Control, RowOutcome
from games.commands.playergame import RecordPlayerGameFacts
from games.events.dispatch import CommandRejected, RowUnreadable
from games.events.playergame import (
    PLAYERGAME_STATUS_CHANGED,
)
from games.forms import TRI_STATE_HINTS
from games.models import (
    VISIBILITY_FIELDS,
    Game,
    LibraryEvent,
    LibraryIdempotencyRecord,
    Platform,
    PlayerGame,
    PlayerGameStatus,
)
from games.reads.events import batch_aggregate_ids
from games.reads.playergame_facts import (
    BatchFactChanges,
    FactChange,
    batch_fact_changes,
    status_change,
)
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

URL = reverse("games:run_bulk_action", args=[EDIT.name])
STATUS = f"{CHOICE_FIELD}-status"


MASTERED = f"{CHOICE_FIELD}-mastered"
EXCLUDED = f"{CHOICE_FIELD}-excluded_from_unfinished"
DROPPED = f"{CHOICE_FIELD}-excluded_from_dropped"


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


def _tracked(game) -> PlayerGame:
    return PlayerGame.objects.get(game=game)


def _status(game) -> PlayerGameStatus:
    return PlayerGameStatus(_tracked(game).status)


def _events() -> int:
    return LibraryEvent.objects.filter(
        event_type__startswith="library.playergame."
    ).count()


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


def _confirmed(client, *games, **answers: str) -> dict[str, str]:
    """The confirmation's fields, with the form filled."""
    fields = posted(client.post(URL, {STATEMENT_FIELD: some(*games)}))
    fields.update(answers)
    return fields


def _run(client, *games, **answers: str):
    fields = _confirmed(client, *games, **answers)
    return fields[TOKEN_FIELD], client.post(URL, fields)


def _undo(client, token):
    return client.post(reverse("games:undo_bulk_action", args=[token]))


def _post(**fields: str) -> QueryDict:
    post = QueryDict(mutable=True)
    post.update(fields)
    return post


def _inverse(user, game, undoes):
    return EDIT.inverse(
        user,
        _tracked(game).pk,
        undoes=undoes,
        idempotency_key=str(uuid.uuid7()),
        correlation_id=uuid.uuid7(),
    )


# ── The declaration ──────────────────────────────────────────────────────────


def test_the_act_is_declared():
    assert BULK_ACTIONS["playergame.edit"] is EDIT


def test_the_games_list_offers_edit_before_remove(client_in, game):
    markup = client_in.get(reverse("games:list_games")).content.decode()

    assert markup.index(URL) < markup.index(
        reverse("games:run_bulk_action", args=["playergame.remove"])
    )


# ── The rows ─────────────────────────────────────────────────────────────────


def test_a_key_the_library_does_not_track_comes_out_lost(
    owned_library, game, django_user_model
):
    stranger = django_user_model.objects.create_user("stranger", password="p")
    theirs = _game(stranger, "Hades")

    resolution = EDIT.resolve(owned_library, [game.pk, theirs.pk])

    assert [row.pk for row in resolution.rows] == [game.pk]
    assert [(refused.key, refused.sentence) for refused in resolution.refused] == [
        (str(theirs.pk), GAME_GONE)
    ]


def test_the_preview_names_every_fact(owned_user, owned_library, game):
    _stated(owned_user, game, PlayerGameStatus.PLAYED)
    (row,) = EDIT.resolve(owned_library, [game.pk]).rows

    cells = [str(column.cell(row, None)) for column in EDIT.preview]

    assert cells == ["Outer Wilds", "PC", "Played", "No", "Included", "Included"]


# ── The question ─────────────────────────────────────────────────────────────


def test_the_control_groups_visibility(owned_library, game):
    rows = EDIT.resolve(owned_library, [game.pk]).rows

    markup = str(EDIT.choice.offer(owned_library, rows, CHOICE_FIELD).node)
    visibility = markup.split("Visibility</legend>", 1)[1].split("</fieldset>", 1)[0]

    assert "Leave these games out of:" in visibility
    assert f'name="{EXCLUDED}"' in visibility
    assert f'name="{DROPPED}"' in visibility
    assert f'name="{STATUS}"' not in visibility


def test_no_rows_ask_nothing(owned_library):
    assert isinstance(EDIT.choice.offer(owned_library, (), CHOICE_FIELD), AsksNothing)


def test_the_control_keeps_what_the_rows_hold(
    owned_user, owned_library, game, second_game
):
    _stated(owned_user, game, PlayerGameStatus.PLAYED)
    for each in (game, second_game):
        record_facts(
            owned_user,
            each,
            excluded_from_dropped=True,
            correlation_id=new_correlation_id(),
        )
    rows = EDIT.resolve(owned_library, [game.pk, second_game.pk]).rows

    offered = EDIT.choice.offer(owned_library, rows, CHOICE_FIELD)

    assert isinstance(offered, Control)
    markup = str(offered.node)
    for name in (STATUS, MASTERED, EXCLUDED, DROPPED):
        assert f'name="{name}"' in markup
    #: Status differs; the flags agree.
    assert "Keep: mixed" in markup
    assert held_word(markup, MASTERED) == "unchecked"
    assert held_word(markup, EXCLUDED) == "unchecked"
    assert held_word(markup, DROPPED) == "checked"
    assert markup.count("<tri-state-checkbox name=") == 3
    assert markup.count(f">{TRI_STATE_HINTS.kept}</span>") == 3


def test_a_flag_the_rows_differ_on_is_held_mixed(
    owned_user, owned_library, game, second_game
):
    record_facts(owned_user, game, mastered=True, correlation_id=new_correlation_id())
    rows = EDIT.resolve(owned_library, [game.pk, second_game.pk]).rows

    markup = str(EDIT.choice.offer(owned_library, rows, CHOICE_FIELD).node)

    assert held_word(markup, MASTERED) == "mixed"
    assert f">{TRI_STATE_HINTS.mixed}</span>" in markup


def test_settling_refuses_a_form_that_states_nothing(owned_library):
    with pytest.raises(CommandRejected) as refused:
        EDIT.choice.settle(owned_library, _post(**{STATUS: ""}))

    assert refused.value.sentence == NOTHING_STATED


def test_settling_refuses_status_and_every_flag_kept(owned_library):
    with pytest.raises(CommandRejected) as refused:
        EDIT.choice.settle(
            owned_library,
            _post(**{STATUS: "", MASTERED: "", EXCLUDED: "", DROPPED: ""}),
        )

    assert refused.value.sentence == NOTHING_STATED


def test_settling_composes_the_statement(owned_library):
    settled = EDIT.choice.settle(
        owned_library, _post(**{STATUS: "completed", MASTERED: "True"})
    )

    assert GameEditStatement.decode(settled) == GameEditStatement(
        status=PlayerGameStatus.COMPLETED, mastered=True
    )


def test_settling_states_the_dropped_flag_alone(owned_library):
    settled = EDIT.choice.settle(owned_library, _post(**{DROPPED: "True"}))

    assert GameEditStatement.decode(settled) == GameEditStatement(
        excluded_from_dropped=True
    )


def test_settling_reads_a_carried_statement(owned_library):
    carried = GameEditStatement(excluded_from_dropped=True).encode()

    assert EDIT.choice.settle(owned_library, _post(**{CHOICE_FIELD: carried})) == (
        carried
    )


@pytest.mark.parametrize(
    "carried",
    [
        '{"status": "finished"}',
        '{"mastered": "yes"}',
        '{"note": "x"}',
        '{"mastered": null}',
        '{"excluded_from_dropped": "yes"}',
        '{"status": null}',
        "{}",
        "[]",
        "not json",
    ],
)
def test_an_unreadable_statement_is_refused(carried):
    with pytest.raises(CommandRejected) as refused:
        GameEditStatement.decode(carried)

    assert refused.value.sentence == STATEMENT_UNREADABLE


# ── Forward ──────────────────────────────────────────────────────────────────


def test_every_selected_game_states_the_facts_under_one_batch(
    client_in, owned_library, game, second_game
):
    token, _ = _run(
        client_in,
        game,
        second_game,
        **{STATUS: "completed", MASTERED: "True", EXCLUDED: "True", DROPPED: "True"},
    )

    for row in (_tracked(game), _tracked(second_game)):
        assert row.status == PlayerGameStatus.COMPLETED
        assert row.mastered is True
        assert row.excluded_from_unfinished is True
        assert row.excluded_from_dropped is True
    assert set(batch_aggregate_ids(owned_library, uuid.UUID(token), "playergame")) == {
        _tracked(game).pk,
        _tracked(second_game).pk,
    }


def test_a_kept_field_states_nothing(client_in, game):
    _run(client_in, game, **{MASTERED: "True"})

    assert _status(game) == PlayerGameStatus.UNPLAYED
    assert not LibraryEvent.objects.filter(
        event_type=PLAYERGAME_STATUS_CHANGED.event_type
    ).exists()


def test_a_game_that_holds_every_fact_is_unchanged(owned_user, game):
    _stated(owned_user, game, PlayerGameStatus.COMPLETED)

    outcome = EDIT.run(
        owned_user,
        game,
        choice=GameEditStatement(
            status=PlayerGameStatus.COMPLETED,
            mastered=False,
            excluded_from_unfinished=False,
            excluded_from_dropped=False,
        ).encode(),
        idempotency_key=str(uuid.uuid7()),
        correlation_id=uuid.uuid7(),
    )

    assert outcome is RowOutcome.UNCHANGED


def test_a_missing_statement_is_a_defect(owned_user, game):
    with pytest.raises(CommandFailed) as failed:
        EDIT.run(
            owned_user,
            game,
            choice=None,
            idempotency_key=str(uuid.uuid7()),
            correlation_id=uuid.uuid7(),
        )

    assert isinstance(failed.value.__cause__, RowUnreadable)


# ── Through the runner ───────────────────────────────────────────────────────


def test_the_confirmation_asks_for_the_facts(client_in, game, second_game):
    confirmation = client_in.post(URL, {STATEMENT_FIELD: some(game, second_game)})

    markup = html_module.unescape(confirmation.content.decode())
    assert "Edit 2 games" in markup
    for heading in (
        "Game",
        "Platform",
        "Status",
        "Mastered",
        "Unfinished lists",
        "Dropped figures",
    ):
        assert f">{heading}<" in markup
    assert f'name="{STATUS}"' in markup


def test_an_empty_form_asks_again_and_writes_nothing(client_in, game):
    fields = _confirmed(client_in, game)
    events = _events()

    again = client_in.post(URL, fields)

    assert NOTHING_STATED in html_module.unescape(again.content.decode())
    assert _events() == events


def test_a_chunk_posted_twice_acts_once(client_in, owned_user, game):
    fields = _confirmed(client_in, game, **{STATUS: "completed"})
    client_in.post(URL, fields)
    _stated(owned_user, game, PlayerGameStatus.ABANDONED)
    events = _events()

    client_in.post(URL, fields)

    assert _events() == events
    assert _status(game) == PlayerGameStatus.ABANDONED


def test_a_game_removed_after_the_confirmation_is_left_alone(
    client_in, owned_user, game, second_game
):
    fields = _confirmed(client_in, game, second_game, **{STATUS: "completed"})
    remove_from_library(owned_user, game, correlation_id=new_correlation_id())

    client_in.post(URL, fields)

    assert _status(game) == PlayerGameStatus.UNPLAYED
    assert _status(second_game) == PlayerGameStatus.COMPLETED


# ── Backward ─────────────────────────────────────────────────────────────────


def test_an_undo_states_every_fact_before_the_batch(
    client_in, owned_user, game, second_game
):
    _stated(owned_user, game, PlayerGameStatus.PLAYED)
    record_facts(
        owned_user,
        game,
        excluded_from_unfinished=True,
        correlation_id=new_correlation_id(),
    )
    token, _ = _run(
        client_in,
        game,
        second_game,
        **{STATUS: "completed", MASTERED: "True", EXCLUDED: "False", DROPPED: "True"},
    )

    _undo(client_in, token)

    def facts(row):
        return (
            row.status,
            row.mastered,
            row.excluded_from_unfinished,
            row.excluded_from_dropped,
        )

    assert facts(_tracked(game)) == (PlayerGameStatus.PLAYED, False, True, False)
    #: Creation leaves the defaults; excluded never changed.
    assert facts(_tracked(second_game)) == (
        PlayerGameStatus.UNPLAYED,
        False,
        False,
        False,
    )


def test_an_undo_pressed_twice_is_already_so(client_in, game):
    token, _ = _run(client_in, game, **{STATUS: "completed", EXCLUDED: "True"})
    _undo(client_in, token)
    events = _events()

    again = _undo(client_in, token)

    assert _status(game) == PlayerGameStatus.UNPLAYED
    assert _events() == events
    assert any("already" in sentence for sentence in said(again))


def test_an_undo_of_a_dropped_flag_already_back_is_already_so(
    client_in, owned_user, game
):
    token, _ = _run(client_in, game, **{DROPPED: "True"})
    record_facts(
        owned_user,
        game,
        excluded_from_dropped=False,
        correlation_id=new_correlation_id(),
    )
    events = _events()

    answer = _undo(client_in, token)

    assert _tracked(game).excluded_from_dropped is False
    assert _events() == events
    assert any("already" in sentence for sentence in said(answer))


def test_the_fact_lists_agree():
    """Command, statement, wire and Undo name one set."""
    #: Bulk Edit never states an implied status.
    command_facts = {
        field.name for field in dataclass_fields(RecordPlayerGameFacts)
    } - {"game_id", "implied_status"}

    assert command_facts == {
        field.name for field in dataclass_fields(GameEditStatement)
    }
    assert command_facts == set(GameEditJson.__annotations__)
    assert command_facts == {field.name for field in dataclass_fields(BatchFactChanges)}
    assert set(VISIBILITY_FIELDS) < command_facts


def test_an_undo_states_the_earlier_word_over_a_later_one(
    client_in, owned_user, game, capture_games_logger
):
    token, _ = _run(client_in, game, **{STATUS: "completed"})
    _stated(owned_user, game, PlayerGameStatus.ABANDONED)

    with capture_games_logger() as captured:
        captured.set_level(logging.INFO, logger="games")
        _undo(client_in, token)

    assert _status(game) == PlayerGameStatus.UNPLAYED
    assert any("over abandoned" in record.getMessage() for record in captured.records)


def test_an_undo_refuses_a_removed_game(client_in, owned_user, game):
    token, _ = _run(client_in, game, **{STATUS: "completed"})
    remove_from_library(owned_user, game, correlation_id=new_correlation_id())

    with pytest.raises(CommandFailed) as refused:
        _inverse(owned_user, game, uuid.UUID(token))

    assert refused.value.message == GAME_REMOVED


def test_an_undo_answers_a_removed_game_already_so_when_it_holds_the_facts(
    client_in, owned_user, game
):
    token, _ = _run(client_in, game, **{STATUS: "completed"})
    _stated(owned_user, game, PlayerGameStatus.UNPLAYED)
    remove_from_library(owned_user, game, correlation_id=new_correlation_id())

    assert _inverse(owned_user, game, uuid.UUID(token)) is RowOutcome.UNCHANGED


def test_an_undo_refuses_a_game_the_batch_did_not_change(owned_user, game):
    with pytest.raises(CommandFailed) as refused:
        _inverse(owned_user, game, uuid.uuid7())

    assert refused.value.message == NOT_EDITED_BY_THIS_BATCH


# ── The reader ───────────────────────────────────────────────────────────────


def test_the_reader_answers_none_for_another_batch(owned_user, owned_library, game):
    _stated(owned_user, game, PlayerGameStatus.PLAYED)

    assert status_change(owned_library, _tracked(game).pk, uuid.uuid7()) is None


def test_the_reader_reads_the_batch_it_is_asked(owned_user, owned_library, game):
    first, second = new_correlation_id(), new_correlation_id()
    record_facts(owned_user, game, status=PlayerGameStatus.PLAYED, correlation_id=first)
    record_facts(
        owned_user, game, status=PlayerGameStatus.COMPLETED, correlation_id=second
    )

    key = _tracked(game).pk
    assert status_change(owned_library, key, first) == FactChange("unplayed", "played")
    assert status_change(owned_library, key, second) == FactChange(
        "played", "completed"
    )


@pytest.mark.parametrize(
    "fact", ["mastered", "excluded_from_unfinished", "excluded_from_dropped"]
)
def test_a_flag_starts_false(owned_user, owned_library, game, fact):
    batch = new_correlation_id()
    record_facts(owned_user, game, **{fact: True}, correlation_id=batch)

    changes = batch_fact_changes(owned_library, _tracked(game).pk, batch)

    assert getattr(changes, fact) == FactChange(False, True)


def test_a_stream_with_no_creation_is_a_defect(owned_user, owned_library):
    """A projection row written by hand has no stream behind it."""
    game = Game.objects.create(library=owned_library, name="Written by hand")
    tracked_run(owned_library, game)
    batch = new_correlation_id()
    record_facts(owned_user, game, status=PlayerGameStatus.PLAYED, correlation_id=batch)

    with pytest.raises(RowUnreadable):
        status_change(owned_library, _tracked(game).pk, batch)


# ── Review gaps ──────────────────────────────────────────────────────────────


def test_a_form_refusal_names_its_field(owned_library):
    with pytest.raises(CommandRejected) as refused:
        EDIT.choice.settle(owned_library, _post(**{MASTERED: "maybe"}))

    assert refused.value.sentence.startswith("Mastered: ")


def test_a_chunk_posted_twice_states_the_flag_once(client_in, owned_user, game):
    fields = _confirmed(client_in, game, **{STATUS: "completed", EXCLUDED: "True"})
    client_in.post(URL, fields)
    record_facts(
        owned_user,
        game,
        excluded_from_unfinished=False,
        correlation_id=new_correlation_id(),
    )
    events = _events()

    client_in.post(URL, fields)

    assert _events() == events
    assert _tracked(game).excluded_from_unfinished is False


def test_a_row_states_every_fact_under_one_key(client_in, game, second_game):
    before = LibraryIdempotencyRecord.objects.count()

    _run(
        client_in,
        game,
        second_game,
        **{STATUS: "completed", MASTERED: "True", EXCLUDED: "True"},
    )

    #: One command, one record, per row.
    assert LibraryIdempotencyRecord.objects.count() - before == 2
    assert _tracked(game).excluded_from_unfinished is True


def test_a_row_with_one_changed_fact_of_two_counts_moved(owned_user, game):
    _stated(owned_user, game, PlayerGameStatus.COMPLETED)

    outcome = EDIT.run(
        owned_user,
        game,
        choice=GameEditStatement(
            status=PlayerGameStatus.COMPLETED, excluded_from_unfinished=True
        ).encode(),
        idempotency_key=str(uuid.uuid7()),
        correlation_id=uuid.uuid7(),
    )

    assert outcome is RowOutcome.MOVED


def test_an_undo_restates_only_the_facts_still_changed(client_in, owned_user, game):
    token, _ = _run(client_in, game, **{STATUS: "completed", MASTERED: "True"})
    _stated(owned_user, game, PlayerGameStatus.UNPLAYED)
    events = LibraryEvent.objects.filter(
        event_type=PLAYERGAME_STATUS_CHANGED.event_type
    ).count()

    assert _inverse(owned_user, game, uuid.UUID(token)) is RowOutcome.MOVED

    assert _tracked(game).mastered is False
    assert (
        LibraryEvent.objects.filter(
            event_type=PLAYERGAME_STATUS_CHANGED.event_type
        ).count()
        == events
    )


def test_an_undo_of_another_librarys_game_is_absent(client_in, game, django_user_model):
    token, _ = _run(client_in, game, **{STATUS: "completed"})
    stranger = django_user_model.objects.create_user("stranger", password="p")

    with pytest.raises(Http404):
        _inverse(stranger, game, uuid.UUID(token))

    assert _status(game) == PlayerGameStatus.COMPLETED
