"""A session or a record names the Release it was played on."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from entries import end_entry_access, record_entry, remove_entry, second_release

from games.commands.historical_playtime import (
    HistoricalPlaytimeStatement,
    RecordHistoricalPlaytime,
    RestateHistoricalPlaytime,
)
from games.commands.playersession import (
    CreateSession,
    DescribeSession,
    MoveSessionToPlaythrough,
    RemoveSession,
    StatedRelease,
    TimedTiming,
)
from games.commands.playthrough import CreatePlaythrough, MovePlaythroughToGame
from games.commands.scope import (
    NO_COPY_OF_RELEASE,
    RELEASE_OF_ANOTHER_GAME,
    RELEASE_REMOVED,
)
from games.commands.session_reclassification import (
    ReclassifySessionAsHistoricalPlaytime,
    statement_from_session,
)
from games.events.dispatch import (
    CommandOutcome,
    CommandRejected,
    RowNotHeld,
    dispatch,
)
from games.models import (
    Game,
    HistoricalPlaytime,
    HistoricalPlaytimeProvenance,
    LibraryEvent,
    PlayerSession,
    Playthrough,
)
from games.reads.calendar import calendar_day_zone
from games.removal import remove

pytestmark = [pytest.mark.untracked_games, pytest.mark.django_db(transaction=True)]

START = datetime(2026, 1, 1, 12, tzinfo=UTC)


@pytest.fixture
def graph(owned_library, stated_graph):
    return stated_graph(Game(name="Hades", library=owned_library), owned_library)


@pytest.fixture
def other_graph(owned_library, stated_graph):
    return stated_graph(Game(name="Celeste", library=owned_library), owned_library)


@pytest.fixture
def entry(owned_library, graph):
    return record_entry(owned_library, graph.release)


@pytest.fixture
def run(entry, graph) -> Playthrough:
    return Playthrough.objects.get(player_game__game=graph.game)


@pytest.fixture
def other_run(owned_library, other_graph) -> Playthrough:
    record_entry(owned_library, other_graph.release)
    return Playthrough.objects.get(player_game__game=other_graph.game)


def state(library, command) -> CommandOutcome:
    return dispatch(
        command,
        actor=library.user,
        library=library,
        idempotency_key=str(uuid.uuid7()),
    ).outcome


def refused(library, command) -> CommandRejected:
    with pytest.raises(CommandRejected) as refusal:
        state(library, command)
    return refusal.value


def a_session(library, run, release=None) -> PlayerSession:
    state(
        library,
        CreateSession(
            playthrough_id=run.pk,
            timing=TimedTiming(
                started_at=START,
                ended_at=START + timedelta(hours=1),
                day_zone=calendar_day_zone(library).key,
            ),
            release_id=None if release is None else release.pk,
        ),
    )
    return PlayerSession.objects.latest("created_at")


def created_session(run, release) -> CreateSession:
    return CreateSession(
        playthrough_id=run.pk,
        timing=TimedTiming(
            started_at=START, day_zone=calendar_day_zone(run.library).key
        ),
        release_id=release.pk,
    )


def a_statement(run, release=None) -> HistoricalPlaytimeStatement:
    return HistoricalPlaytimeStatement(
        duration=timedelta(hours=10),
        when="2005",
        provenance=HistoricalPlaytimeProvenance.ESTIMATED,
        playthrough_ids=(run.pk,),
        device_id=None,
        emulated=False,
        note="",
        release_id=None if release is None else release.pk,
    )


def latest_types(count: int) -> list[str]:
    events = LibraryEvent.objects.order_by("-sequence")[:count]
    return [event.event_type for event in reversed(events)]


def test_a_session_names_a_release_of_a_held_copy(owned_library, graph, run):
    session = a_session(owned_library, run, graph.release)

    assert session.release_id == graph.release.pk
    created = LibraryEvent.objects.get(event_type="library.playersession.created")
    assert created.payload["release"]["kind"] == "catalog.release"


def test_an_ended_copy_still_holds_its_release(owned_library, graph, entry, run):
    end_entry_access(entry)

    assert a_session(owned_library, run, graph.release).release_id == graph.release.pk


def test_a_release_with_no_copy_is_refused(owned_library, run, entry):
    uncopied = second_release(owned_library, entry.release)

    refusal = refused(owned_library, created_session(run, uncopied))

    assert refusal.sentence == NO_COPY_OF_RELEASE


def test_a_removed_copy_holds_no_release(owned_library, graph, entry, run):
    remove_entry(entry)

    refusal = refused(owned_library, created_session(run, graph.release))

    assert refusal.sentence == NO_COPY_OF_RELEASE


def test_a_removed_release_is_refused_first(owned_library, graph, run):
    remove(graph.release)

    refusal = refused(owned_library, created_session(run, graph.release))

    assert refusal.sentence == RELEASE_REMOVED


def test_another_games_release_is_refused(owned_library, run, other_graph, other_run):
    refusal = refused(owned_library, created_session(run, other_graph.release))

    assert refusal.sentence == RELEASE_OF_ANOTHER_GAME


def test_a_release_the_library_cannot_see_is_absent(
    owned_library, run, django_user_model, stated_graph
):
    stranger = django_user_model.objects.create_user(username="stranger").library
    theirs = stated_graph(Game(name="Tunic", library=stranger), stranger)

    with pytest.raises(RowNotHeld):
        state(owned_library, created_session(run, theirs.release))


def test_a_description_states_clears_and_repeats_a_release(owned_library, graph, run):
    session = a_session(owned_library, run)
    held = StatedRelease(graph.release.pk)

    state(owned_library, DescribeSession(session.pk, release=held))
    session.refresh_from_db()
    assert session.release_id == graph.release.pk

    assert state(owned_library, DescribeSession(session.pk, release=held)) is (
        CommandOutcome.UNCHANGED
    )

    state(owned_library, DescribeSession(session.pk, release=StatedRelease(None)))
    session.refresh_from_db()
    assert session.release_id is None


def test_a_description_keeps_a_held_release_whose_copy_is_gone(
    owned_library, graph, entry, run
):
    session = a_session(owned_library, run, graph.release)
    remove_entry(entry)

    state(owned_library, DescribeSession(session.pk, note="kept"))

    session.refresh_from_db()
    assert session.release_id == graph.release.pk
    assert session.note == "kept"


def test_a_description_states_at_least_one_fact():
    with pytest.raises(CommandRejected):
        DescribeSession(uuid.uuid7())


def test_a_move_to_another_game_clears_the_release(
    owned_library, graph, run, other_run
):
    session = a_session(owned_library, run, graph.release)

    state(
        owned_library,
        MoveSessionToPlaythrough(session_id=session.pk, playthrough_id=other_run.pk),
    )

    session.refresh_from_db()
    assert session.release_id is None
    assert latest_types(2) == [
        "library.playersession.release_changed",
        "library.playersession.moved",
    ]


def test_a_move_within_the_game_keeps_the_release(owned_library, graph, run, entry):
    session = a_session(owned_library, run, graph.release)
    state(owned_library, CreatePlaythrough(game_id=graph.game.pk))
    sibling = Playthrough.objects.exclude(pk=run.pk).get(player_game=run.player_game)

    state(
        owned_library,
        MoveSessionToPlaythrough(session_id=session.pk, playthrough_id=sibling.pk),
    )

    session.refresh_from_db()
    assert session.release_id == graph.release.pk


def test_a_record_names_a_release(owned_library, graph, run):
    state(owned_library, RecordHistoricalPlaytime(a_statement(run, graph.release)))

    assert HistoricalPlaytime.objects.get().release_id == graph.release.pk


def test_a_record_refuses_another_games_release(
    owned_library, run, other_graph, other_run
):
    refusal = refused(
        owned_library, RecordHistoricalPlaytime(a_statement(run, other_graph.release))
    )

    assert refusal.sentence == RELEASE_OF_ANOTHER_GAME


def test_a_restatement_of_the_release_alone_is_a_change(owned_library, graph, run):
    state(owned_library, RecordHistoricalPlaytime(a_statement(run)))
    record = HistoricalPlaytime.objects.get()

    outcome = state(
        owned_library,
        RestateHistoricalPlaytime(record.pk, a_statement(run, graph.release)),
    )

    assert outcome is CommandOutcome.APPENDED
    record.refresh_from_db()
    assert record.release_id == graph.release.pk


def test_a_restatement_keeps_a_held_release_whose_copy_is_gone(
    owned_library, graph, entry, run
):
    state(owned_library, RecordHistoricalPlaytime(a_statement(run, graph.release)))
    record = HistoricalPlaytime.objects.get()
    remove_entry(entry)

    restated = a_statement(run, graph.release)._replace(note="kept")
    state(owned_library, RestateHistoricalPlaytime(record.pk, restated))

    record.refresh_from_db()
    assert (record.note, record.release_id) == ("kept", graph.release.pk)


def test_a_restatement_onto_another_game_cannot_keep_the_release(
    owned_library, graph, run, other_run
):
    state(owned_library, RecordHistoricalPlaytime(a_statement(run, graph.release)))
    record = HistoricalPlaytime.objects.get()

    refusal = refused(
        owned_library,
        RestateHistoricalPlaytime(record.pk, a_statement(other_run, graph.release)),
    )

    assert refusal.sentence == RELEASE_OF_ANOTHER_GAME


def test_a_reclassification_carries_the_sessions_release(
    owned_library, graph, entry, run
):
    session = a_session(owned_library, run, graph.release)
    remove_entry(entry)

    state(
        owned_library,
        ReclassifySessionAsHistoricalPlaytime(
            session.pk, statement_from_session(session)
        ),
    )

    assert HistoricalPlaytime.objects.get().release_id == graph.release.pk


def test_a_run_moved_to_another_game_clears_every_release(
    owned_library, graph, run, other_graph, other_run
):
    live = a_session(owned_library, run, graph.release)
    gone = a_session(owned_library, run, graph.release)
    bare = a_session(owned_library, run)
    state(owned_library, RemoveSession(gone.pk))
    state(owned_library, RecordHistoricalPlaytime(a_statement(run, graph.release)))

    state(
        owned_library,
        MovePlaythroughToGame(playthrough_id=run.pk, game_id=other_graph.game.pk),
    )

    released = PlayerSession.objects.filter(release__isnull=False)
    assert not released.exists()
    assert HistoricalPlaytime.objects.get().release_id is None
    cleared = LibraryEvent.objects.filter(
        event_type="library.playersession.release_changed"
    )
    assert {event.aggregate_id for event in cleared} == {live.pk, gone.pk}
    assert bare.pk not in {event.aggregate_id for event in cleared}
    moved = LibraryEvent.objects.get(event_type="library.historicalplaytime.moved")
    assert moved.payload["release"] is None
