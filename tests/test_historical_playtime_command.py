"""Stating untracked playtime."""

import uuid
from datetime import timedelta

import pytest
from devices import create_device, remove_device
from django.utils import timezone

from games.commands.historical_playtime import (
    GAME_REMOVED,
    INTO_THE_BUCKET_HISTORICAL,
    ONE_GAME,
    RUN_REMOVED,
    WHEN_NO_SUCH_DATE,
    WHEN_NOT_A_DATE,
    WHEN_RANGE_BACKWARDS,
    WHEN_UNSUPPORTED,
    HistoricalPlaytimeStatement,
    RecordHistoricalPlaytime,
    RemoveHistoricalPlaytime,
    RestateHistoricalPlaytime,
    RestoreHistoricalPlaytime,
)
from games.commands.playergame import RemovePlayerGame, TrackGame
from games.commands.playthrough import (
    CreatePlaythrough,
    PlaythroughNotHeld,
    RemovePlaythrough,
)
from games.events.dispatch import (
    CommandOutcome,
    CommandRejected,
    RowNotHeld,
    RowUnreadable,
    dispatch,
)
from games.models import (
    Game,
    HistoricalPlaytime,
    HistoricalPlaytimeProvenance,
    HistoricalPlaytimeRun,
    LibraryEvent,
    PlayerGame,
    Playthrough,
    PlaythroughKind,
)
from games.reads.playthrough_referrers import HISTORICAL_PLAYTIME_RECORDED
from timetracker.temporal import TemporalValueParseError

pytestmark = [pytest.mark.untracked_games, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def game(owned_library):
    return Game.objects.create(library=owned_library, name="Outer Wilds")


@pytest.fixture
def run(owned_user, owned_library, game) -> Playthrough:
    dispatch(
        TrackGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="track",
    )
    return Playthrough.objects.get(player_game__game=game)


@pytest.fixture
def second_run(owned_user, owned_library, run) -> Playthrough:
    dispatch(
        CreatePlaythrough(game_id=run.player_game.game_id),
        actor=owned_user,
        library=owned_library,
        idempotency_key="second",
    )
    return Playthrough.objects.exclude(pk=run.pk).get()


@pytest.fixture
def second_library(django_user_model):
    other = django_user_model.objects.create_user(username="second-owner")
    return other.library


A_STATEMENT = HistoricalPlaytimeStatement(
    duration=timedelta(hours=100),
    when="2005",
    provenance=HistoricalPlaytimeProvenance.ESTIMATED,
    playthrough_ids=(),
    device_id=None,
    emulated=False,
    note="",
)


def stated(run, **changes) -> HistoricalPlaytimeStatement:
    return A_STATEMENT._replace(playthrough_ids=(run.pk,))._replace(**changes)


def record(library, actor, statement, *, key=None) -> HistoricalPlaytime:
    dispatch(
        RecordHistoricalPlaytime(statement=statement),
        actor=actor,
        library=library,
        idempotency_key=key or str(uuid.uuid7()),
    )
    return HistoricalPlaytime.objects.get()


def _refused(library, actor, command) -> CommandRejected:
    with pytest.raises(CommandRejected) as refused:
        dispatch(
            command, actor=actor, library=library, idempotency_key=str(uuid.uuid7())
        )
    assert refused.value.sentence
    return refused.value


def _not_held(library, actor, command, raising=RowNotHeld) -> RowNotHeld:
    """A row this library does not hold; the boundary owns the answer."""
    with pytest.raises(raising) as absent:
        dispatch(
            command, actor=actor, library=library, idempotency_key=str(uuid.uuid7())
        )
    assert not hasattr(absent.value, "sentence")
    return absent.value


def test_it_records_the_statement(owned_user, owned_library, run, second_run):
    stored = record(
        owned_library,
        owned_user,
        stated(run, playthrough_ids=(second_run.pk, run.pk)),
    )
    assert stored.duration == timedelta(hours=100)
    assert stored.when.canonical == "2005"
    assert stored.player_game_id == run.player_game_id
    assert stored.provenance == HistoricalPlaytimeProvenance.ESTIMATED
    assert set(stored.runs.values_list("playthrough_id", flat=True)) == {
        run.pk,
        second_run.pk,
    }
    assert (
        LibraryEvent.objects.filter(
            library=owned_library, event_type="library.historicalplaytime.created"
        ).count()
        == 1
    )


def test_an_unknown_when_is_admitted(owned_user, owned_library, run):
    assert record(owned_library, owned_user, stated(run, when=None)).when is None


def test_a_device_is_captured(owned_user, owned_library, run):
    device = create_device(library=owned_library, name="Steam Deck")
    stored = record(owned_library, owned_user, stated(run, device_id=device.pk))
    assert stored.device_id == device.pk
    event = LibraryEvent.objects.get(event_type="library.historicalplaytime.created")
    assert event.payload["device"]["label"] == "Steam Deck"


@pytest.mark.parametrize(
    ("changes", "fragment"),
    [
        ({"playthrough_ids": ()}, "at least one"),
        ({"duration": timedelta(0)}, "at least a second"),
        ({"duration": timedelta(seconds=-1)}, "at least a second"),
        ({"when": "not a date"}, ""),
        ({"note": "a\x00b"}, "cannot store"),
    ],
    ids=["no-runs", "zero", "negative", "unparseable-when", "nul-note"],
)
def test_a_statement_is_refused_before_the_fingerprint(run, changes, fragment):
    with pytest.raises(CommandRejected) as refused:
        RecordHistoricalPlaytime(statement=stated(run, **changes))
    assert refused.value.sentence
    assert fragment in refused.value.sentence


def test_a_duration_is_truncated_to_whole_seconds(run):
    command = RecordHistoricalPlaytime(
        statement=stated(run, duration=timedelta(seconds=90, microseconds=500))
    )
    assert command.statement.duration == timedelta(seconds=90)


def test_a_repeated_run_is_named_once(run):
    command = RecordHistoricalPlaytime(
        statement=stated(run, playthrough_ids=(run.pk, run.pk))
    )
    assert command.statement.playthrough_ids == (run.pk,)


def test_the_note_is_stripped(run):
    command = RecordHistoricalPlaytime(statement=stated(run, note="  read off Steam  "))
    assert command.statement.note == "read off Steam"


def test_the_when_is_made_canonical(run):
    command = RecordHistoricalPlaytime(statement=stated(run, when="2005-03"))
    assert command.statement.when == "2005-03"


def test_it_refuses_runs_of_two_games(owned_user, owned_library, run):
    other = Game.objects.create(library=owned_library, name="Elden Ring")
    dispatch(
        TrackGame(game_id=other.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="track-other",
    )
    other_run = Playthrough.objects.get(player_game__game=other)
    refused = _refused(
        owned_library,
        owned_user,
        RecordHistoricalPlaytime(
            statement=stated(run, playthrough_ids=(run.pk, other_run.pk))
        ),
    )
    assert refused.sentence == ONE_GAME


def test_it_refuses_the_bucket(owned_user, owned_library, run):
    bucket = Playthrough.objects.create(
        id=uuid.uuid7(),
        library=owned_library,
        player_game=run.player_game,
        kind=PlaythroughKind.IMPORTED_HISTORY,
        created_at=timezone.now(),
    )
    refused = _refused(
        owned_library,
        owned_user,
        RecordHistoricalPlaytime(statement=stated(run, playthrough_ids=(bucket.pk,))),
    )
    assert refused.sentence == INTO_THE_BUCKET_HISTORICAL


def test_it_refuses_a_run_another_library_holds(
    owned_user, owned_library, run, second_library
):
    Playthrough.objects.filter(pk=run.pk).update(library=second_library)
    _not_held(
        owned_library,
        owned_user,
        RecordHistoricalPlaytime(statement=stated(run)),
        raising=PlaythroughNotHeld,
    )


def test_it_refuses_a_removed_run(owned_user, owned_library, run):
    Playthrough.objects.filter(pk=run.pk).update(removed_at=timezone.now())
    refused = _refused(
        owned_library, owned_user, RecordHistoricalPlaytime(statement=stated(run))
    )
    assert refused.sentence == (
        "That playthrough was removed from your library. Restore it before "
        "recording this."
    )


def test_it_refuses_a_run_under_a_removed_game(owned_user, owned_library, run):
    PlayerGame.objects.filter(pk=run.player_game_id).update(removed_at=timezone.now())
    refused = _refused(
        owned_library, owned_user, RecordHistoricalPlaytime(statement=stated(run))
    )
    assert refused.sentence == (
        "That game was removed from your library. Restore it before recording this."
    )


def test_it_refuses_a_removed_device(owned_user, owned_library, run):
    device = remove_device(create_device(library=owned_library, name="Deck"))
    refused = _refused(
        owned_library,
        owned_user,
        RecordHistoricalPlaytime(statement=stated(run, device_id=device.pk)),
    )
    assert refused.sentence == (
        "That device was removed from your library. Restore it before choosing it."
    )


def test_it_refuses_a_device_another_library_holds(
    owned_user, owned_library, run, second_library
):
    device = create_device(library=second_library, name="Deck")
    _not_held(
        owned_library,
        owned_user,
        RecordHistoricalPlaytime(statement=stated(run, device_id=device.pk)),
    )


@pytest.mark.parametrize(
    ("when", "sentence"),
    [
        ("march 2005", WHEN_NOT_A_DATE),
        ("2005-13", WHEN_NO_SUCH_DATE),
        ("2007/2005", WHEN_RANGE_BACKWARDS),
        ("{2005,2006}", WHEN_UNSUPPORTED),
    ],
    ids=["syntax", "no-such-date", "backwards-range", "unsupported"],
)
def test_an_unreadable_when_answers_a_written_sentence(run, when, sentence):
    with pytest.raises(CommandRejected) as refused:
        RecordHistoricalPlaytime(statement=stated(run, when=when))
    assert refused.value.sentence == sentence


def test_a_when_of_the_wrong_type_is_a_defect(run):
    with pytest.raises(TemporalValueParseError):
        RecordHistoricalPlaytime(statement=stated(run, when=2005))


def test_a_sub_second_retry_under_one_key_replays(owned_user, owned_library, run):
    dispatch(
        RecordHistoricalPlaytime(
            statement=stated(run, duration=timedelta(seconds=90, microseconds=400000))
        ),
        actor=owned_user,
        library=owned_library,
        idempotency_key="k",
    )
    again = dispatch(
        RecordHistoricalPlaytime(statement=stated(run, duration=timedelta(seconds=90))),
        actor=owned_user,
        library=owned_library,
        idempotency_key="k",
    )
    assert again.outcome is CommandOutcome.REPLAYED
    assert HistoricalPlaytime.objects.get().duration == timedelta(seconds=90)


def test_reordered_runs_under_one_key_replay(
    owned_user, owned_library, run, second_run
):
    dispatch(
        RecordHistoricalPlaytime(
            statement=stated(run, playthrough_ids=(run.pk, second_run.pk))
        ),
        actor=owned_user,
        library=owned_library,
        idempotency_key="k",
    )
    again = dispatch(
        RecordHistoricalPlaytime(
            statement=stated(run, playthrough_ids=(second_run.pk, run.pk))
        ),
        actor=owned_user,
        library=owned_library,
        idempotency_key="k",
    )
    assert again.outcome is CommandOutcome.REPLAYED
    assert HistoricalPlaytime.objects.count() == 1


def test_it_admits_every_provenance(owned_user, owned_library, run):
    for index, provenance in enumerate(HistoricalPlaytimeProvenance):
        dispatch(
            RecordHistoricalPlaytime(statement=stated(run, provenance=provenance)),
            actor=owned_user,
            library=owned_library,
            idempotency_key=f"p{index}",
        )
    assert set(HistoricalPlaytime.objects.values_list("provenance", flat=True)) == set(
        HistoricalPlaytimeProvenance.values
    )


def test_a_retry_of_one_statement_appends_nothing_more(owned_user, owned_library, run):
    command = RecordHistoricalPlaytime(statement=stated(run))
    dispatch(command, actor=owned_user, library=owned_library, idempotency_key="k")
    second = dispatch(
        command, actor=owned_user, library=owned_library, idempotency_key="k"
    )
    assert second.outcome is CommandOutcome.REPLAYED
    assert HistoricalPlaytime.objects.count() == 1


def test_the_same_runs_in_another_order_fingerprint_alike(run, second_run):
    one = RecordHistoricalPlaytime(
        statement=stated(run, playthrough_ids=(run.pk, second_run.pk))
    )
    other = RecordHistoricalPlaytime(
        statement=stated(run, playthrough_ids=(second_run.pk, run.pk))
    )
    assert one.statement == other.statement


def test_a_restatement_overwrites_and_keeps_a_kept_join_id(
    owned_user, owned_library, run, second_run
):
    stored = record(
        owned_library, owned_user, stated(run, playthrough_ids=(run.pk, second_run.pk))
    )
    kept_id = stored.runs.get(playthrough=run).pk
    dispatch(
        RestateHistoricalPlaytime(
            record_id=stored.pk,
            statement=stated(run, duration=timedelta(hours=50), when="2006~"),
        ),
        actor=owned_user,
        library=owned_library,
        idempotency_key="restate",
    )
    stored.refresh_from_db()
    assert stored.duration == timedelta(hours=50)
    assert stored.when.canonical == "2006~"
    assert list(stored.runs.values_list("pk", "playthrough_id")) == [(kept_id, run.pk)]


def test_an_equal_restatement_appends_nothing(owned_user, owned_library, run):
    stored = record(owned_library, owned_user, stated(run))
    before = LibraryEvent.objects.count()
    result = dispatch(
        RestateHistoricalPlaytime(record_id=stored.pk, statement=stated(run)),
        actor=owned_user,
        library=owned_library,
        idempotency_key="same",
    )
    assert result.outcome is CommandOutcome.UNCHANGED
    assert LibraryEvent.objects.count() == before


def test_an_equal_restatement_with_an_unknown_when_appends_nothing(
    owned_user, owned_library, run
):
    stored = record(owned_library, owned_user, stated(run, when=None))
    result = dispatch(
        RestateHistoricalPlaytime(
            record_id=stored.pk, statement=stated(run, when=None)
        ),
        actor=owned_user,
        library=owned_library,
        idempotency_key="same",
    )
    assert result.outcome is CommandOutcome.UNCHANGED


def test_a_restatement_of_a_removed_record_is_refused(owned_user, owned_library, run):
    stored = record(owned_library, owned_user, stated(run))
    dispatch(
        RemoveHistoricalPlaytime(record_id=stored.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="rm",
    )
    _refused(
        owned_library,
        owned_user,
        RestateHistoricalPlaytime(record_id=stored.pk, statement=stated(run, note="x")),
    )


def test_a_restatement_under_a_removed_game_is_refused(owned_user, owned_library, run):
    stored = record(owned_library, owned_user, stated(run))
    PlayerGame.objects.filter(pk=run.player_game_id).update(removed_at=timezone.now())
    _refused(
        owned_library,
        owned_user,
        RestateHistoricalPlaytime(record_id=stored.pk, statement=stated(run, note="x")),
    )


def test_remove_and_restore_move_the_mark_and_repeat_as_no_ops(
    owned_user, owned_library, run
):
    stored = record(owned_library, owned_user, stated(run))
    dispatch(
        RemoveHistoricalPlaytime(record_id=stored.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="rm",
    )
    stored.refresh_from_db()
    assert stored.removed_at is not None
    again = dispatch(
        RemoveHistoricalPlaytime(record_id=stored.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="rm2",
    )
    assert again.outcome is CommandOutcome.UNCHANGED
    dispatch(
        RestoreHistoricalPlaytime(record_id=stored.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="rs",
    )
    stored.refresh_from_db()
    assert stored.removed_at is None
    again = dispatch(
        RestoreHistoricalPlaytime(record_id=stored.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="rs2",
    )
    assert again.outcome is CommandOutcome.UNCHANGED


def test_a_record_another_library_holds_is_refused(
    owned_user, owned_library, run, second_library
):
    stored = record(owned_library, owned_user, stated(run))
    HistoricalPlaytime.objects.filter(pk=stored.pk).update(library=second_library)
    _not_held(owned_library, owned_user, RemoveHistoricalPlaytime(record_id=stored.pk))
    _not_held(owned_library, owned_user, RestoreHistoricalPlaytime(record_id=stored.pk))
    assert HistoricalPlaytimeRun.objects.count() == 1


def _restate(library, actor, record_id, statement, *, key):
    return dispatch(
        RestateHistoricalPlaytime(record_id=record_id, statement=statement),
        actor=actor,
        library=library,
        idempotency_key=key,
    )


def test_a_restatement_that_adds_a_run_mints_one_fresh_id(
    owned_user, owned_library, run, second_run
):
    stored = record(owned_library, owned_user, stated(run))
    kept_id = stored.runs.get().pk
    _restate(
        owned_library,
        owned_user,
        stored.pk,
        stated(run, playthrough_ids=(run.pk, second_run.pk)),
        key="add",
    )
    joins = dict(stored.runs.values_list("playthrough_id", "pk"))
    assert joins[run.pk] == kept_id
    assert joins[second_run.pk] != kept_id
    assert len(joins) == 2


def test_a_restatement_clears_and_restores_the_device(owned_user, owned_library, run):
    device = create_device(library=owned_library, name="Deck")
    stored = record(owned_library, owned_user, stated(run, device_id=device.pk))
    cleared = _restate(owned_library, owned_user, stored.pk, stated(run), key="clear")
    assert cleared.outcome is CommandOutcome.APPENDED
    stored.refresh_from_db()
    assert stored.device_id is None
    back = _restate(
        owned_library,
        owned_user,
        stored.pk,
        stated(run, device_id=device.pk),
        key="back",
    )
    assert back.outcome is CommandOutcome.APPENDED
    stored.refresh_from_db()
    assert stored.device_id == device.pk


def test_a_restatement_to_an_unknown_when_clears_the_bounds(
    owned_user, owned_library, run
):
    stored = record(owned_library, owned_user, stated(run, when="2005"))
    _restate(
        owned_library, owned_user, stored.pk, stated(run, when=None), key="unknown"
    )
    stored.refresh_from_db()
    assert stored.when is None
    assert stored.when_lower is None
    assert stored.when_upper is None


@pytest.mark.parametrize(
    "changes",
    [
        {"duration": timedelta(hours=1)},
        {"when": "2006"},
        {"provenance": HistoricalPlaytimeProvenance.MANUALLY_ENTERED},
        {"emulated": True},
        {"note": "changed"},
    ],
    ids=["duration", "when", "provenance", "emulated", "note"],
)
def test_a_restatement_differing_in_one_column_appends(
    owned_user, owned_library, run, changes
):
    stored = record(owned_library, owned_user, stated(run))
    result = _restate(
        owned_library, owned_user, stored.pk, stated(run, **changes), key="one"
    )
    assert result.outcome is CommandOutcome.APPENDED


def test_a_restatement_differing_in_its_runs_appends(
    owned_user, owned_library, run, second_run
):
    stored = record(owned_library, owned_user, stated(run))
    result = _restate(
        owned_library,
        owned_user,
        stored.pk,
        stated(run, playthrough_ids=(second_run.pk,)),
        key="runs",
    )
    assert result.outcome is CommandOutcome.APPENDED
    assert list(stored.runs.values_list("playthrough_id", flat=True)) == [second_run.pk]


def test_a_restatement_keeps_a_removed_device_it_names(owned_user, owned_library, run):
    device = create_device(library=owned_library, name="Deck")
    stored = record(owned_library, owned_user, stated(run, device_id=device.pk))
    remove_device(device)
    result = _restate(
        owned_library,
        owned_user,
        stored.pk,
        stated(run, device_id=device.pk, note="typo fixed"),
        key="keep",
    )
    assert result.outcome is CommandOutcome.APPENDED
    stored.refresh_from_db()
    assert stored.device_id == device.pk
    assert stored.note == "typo fixed"


def test_a_restatement_onto_a_removed_device_is_refused(owned_user, owned_library, run):
    stored = record(owned_library, owned_user, stated(run))
    device = remove_device(create_device(library=owned_library, name="Deck"))
    _refused(
        owned_library,
        owned_user,
        RestateHistoricalPlaytime(
            record_id=stored.pk, statement=stated(run, device_id=device.pk)
        ),
    )


def test_a_removal_under_a_removed_game_is_refused(owned_user, owned_library, run):
    stored = record(owned_library, owned_user, stated(run))
    dispatch(
        RemovePlayerGame(game_id=run.player_game.game_id),
        actor=owned_user,
        library=owned_library,
        idempotency_key="rm-game",
    )
    refused = _refused(
        owned_library, owned_user, RemoveHistoricalPlaytime(record_id=stored.pk)
    )
    assert refused.sentence == GAME_REMOVED


def test_a_restore_under_a_removed_game_is_refused(owned_user, owned_library, run):
    stored = record(owned_library, owned_user, stated(run))
    dispatch(
        RemoveHistoricalPlaytime(record_id=stored.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="rm",
    )
    dispatch(
        RemovePlayerGame(game_id=run.player_game.game_id),
        actor=owned_user,
        library=owned_library,
        idempotency_key="rm-game",
    )
    refused = _refused(
        owned_library, owned_user, RestoreHistoricalPlaytime(record_id=stored.pk)
    )
    assert refused.sentence == GAME_REMOVED
    stored.refresh_from_db()
    assert stored.removed_at is not None


# --- A record keeps its run in place -----------------------------------------


def _remove_run(library, actor, run, *, key):
    return dispatch(
        RemovePlaythrough(playthrough_id=run.pk),
        actor=actor,
        library=library,
        idempotency_key=key,
    )


def test_a_live_record_keeps_its_run_in_place(
    owned_user, owned_library, run, second_run
):
    record(owned_library, owned_user, stated(run, playthrough_ids=(second_run.pk,)))
    refused = _refused(
        owned_library, owned_user, RemovePlaythrough(playthrough_id=second_run.pk)
    )
    assert refused.sentence == HISTORICAL_PLAYTIME_RECORDED
    second_run.refresh_from_db()
    assert second_run.removed_at is None


def test_a_removed_record_keeps_nothing_in_place(
    owned_user, owned_library, run, second_run
):
    stored = record(
        owned_library, owned_user, stated(run, playthrough_ids=(second_run.pk,))
    )
    dispatch(
        RemoveHistoricalPlaytime(record_id=stored.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="rm",
    )
    _remove_run(owned_library, owned_user, second_run, key="rm-run")
    second_run.refresh_from_db()
    assert second_run.removed_at is not None


def test_a_restated_away_record_keeps_nothing_in_place(
    owned_user, owned_library, run, second_run
):
    stored = record(
        owned_library, owned_user, stated(run, playthrough_ids=(second_run.pk,))
    )
    dispatch(
        RestateHistoricalPlaytime(record_id=stored.pk, statement=stated(run)),
        actor=owned_user,
        library=owned_library,
        idempotency_key="move",
    )
    _remove_run(owned_library, owned_user, second_run, key="rm-run")
    second_run.refresh_from_db()
    assert second_run.removed_at is not None


def test_a_foreign_record_is_refused_as_a_defect(
    owned_user, owned_library, run, second_run, second_library
):
    stored = record(
        owned_library, owned_user, stated(run, playthrough_ids=(second_run.pk,))
    )
    HistoricalPlaytime.objects.filter(pk=stored.pk).update(library=second_library)
    HistoricalPlaytimeRun.objects.filter(record=stored).update(library=second_library)
    with pytest.raises(RowUnreadable) as refusal:
        _remove_run(owned_library, owned_user, second_run, key="rm-run")
    argument = str(refusal.value)
    assert str(second_run.pk) in argument
    assert str(second_library.pk) in argument
    assert "HistoricalPlaytimeRun.playthrough" in argument
    second_run.refresh_from_db()
    assert second_run.removed_at is None


def test_a_restore_after_its_run_was_removed_is_refused(
    owned_user, owned_library, run, second_run
):
    stored = record(
        owned_library, owned_user, stated(run, playthrough_ids=(second_run.pk,))
    )
    dispatch(
        RemoveHistoricalPlaytime(record_id=stored.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="rm",
    )
    _remove_run(owned_library, owned_user, second_run, key="rm-run")
    refused = _refused(
        owned_library, owned_user, RestoreHistoricalPlaytime(record_id=stored.pk)
    )
    assert refused.sentence == RUN_REMOVED
    stored.refresh_from_db()
    assert stored.removed_at is not None
    assert not HistoricalPlaytimeRun.objects.alive().exists()
