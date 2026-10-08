"""A copy's access ends, is corrected, voided and resumes."""

import uuid
from typing import get_args

import pytest
from django.db import transaction
from entries import end_entry_access, record_entry, remove_entry
from graphs import default_graph

from games.commands.endpoint import ActStatement, WayActStatement
from games.commands.libraryentry import (
    ACQUISITION_AFTER_END,
    END_BEFORE_ACQUISITION,
    ENTRY_REMOVED,
    PLAYER_GAME_REMOVED,
    RESUME_BEFORE_END,
    UNKNOWN_WAY,
    CorrectEntryAccessEnd,
    CorrectEntryAcquisition,
    EndEntryAccess,
    ResumeEntryAccess,
    VoidEntryAccessEnd,
)
from games.commands.playergame import RemovePlayerGame
from games.end_ways import EndWay
from games.endpoints import ENTRY_ACCESS_END
from games.events.dispatch import (
    CommandOutcome,
    CommandRejected,
    CommandResult,
    RowNotHeld,
    append_command,
    dispatch,
)
from games.events.libraryentry import EntryWayValue
from games.events.rebuild import RebuildMode, rebuild_projections
from games.models import ENTRY_WAYS, Game, LibraryEntry, LibraryEvent
from games.reads.endpoints import stated
from timetracker.temporal import TemporalValue

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.untracked_games]

MAY = TemporalValue.parse("2021-05")
JUNE = TemporalValue.parse("2021-06")
JULY = TemporalValue.parse("2021-07")


@pytest.fixture
def graph(owned_library):
    return default_graph(Game(name="Tunic", library=owned_library), owned_library)


@pytest.fixture
def second_library(django_user_model):
    return django_user_model.objects.create_user(username="second-owner").library


def _dispatch(library, command) -> CommandResult:
    return dispatch(
        command,
        actor=library.user,
        library=library,
        idempotency_key=str(uuid.uuid7()),
    )


def _refused(library, command) -> CommandRejected:
    with pytest.raises(CommandRejected) as refused:
        _dispatch(library, command)
    return refused.value


def _last_event(entry: LibraryEntry) -> LibraryEvent:
    return LibraryEvent.objects.filter(aggregate_id=entry.pk).latest("sequence")


def _returned(ended=JUNE, note: str = "") -> WayActStatement:
    return WayActStatement(ended, EndWay.RETURNED, note)


def test_the_way_literal_spells_every_entry_way() -> None:
    assert set(get_args(EntryWayValue.__value__)) == {way.value for way in ENTRY_WAYS}


def test_an_end_states_the_way_day_and_marker(owned_library, graph):
    entry = record_entry(owned_library, graph.release, acquired=MAY)

    result = _dispatch(
        owned_library, EndEntryAccess(entry_id=entry.pk, statement=_returned())
    )

    assert result.outcome is CommandOutcome.APPENDED
    entry.refresh_from_db()
    held = stated(entry, ENTRY_ACCESS_END)
    assert held is not None
    assert (held.when, held.way, entry.access_end_way) == (
        JUNE,
        EndWay.RETURNED,
        "returned",
    )
    event = _last_event(entry)
    assert event.event_type == "library.libraryentry.access_ended"
    assert event.payload == {"way": "returned", "note": ""}


def test_the_same_end_again_is_unchanged_and_another_refused(owned_library, graph):
    entry = end_entry_access(record_entry(owned_library, graph.release), ended=JUNE)

    same = _dispatch(
        owned_library, EndEntryAccess(entry_id=entry.pk, statement=_returned())
    )
    other = _refused(
        owned_library,
        EndEntryAccess(entry_id=entry.pk, statement=_returned(JULY)),
    )

    assert same.outcome is CommandOutcome.UNCHANGED
    assert "Correct the one it has" in other.sentence


def test_a_foreign_way_is_refused_with_a_sentence(owned_library, graph):
    entry = record_entry(owned_library, graph.release)

    refused = _refused(
        owned_library,
        EndEntryAccess(
            entry_id=entry.pk,
            statement=WayActStatement(JUNE, "melted", ""),  # type: ignore[arg-type]
        ),
    )

    assert refused.sentence == UNKNOWN_WAY


def test_refunded_is_admitted_by_hand(owned_library, graph):
    entry = record_entry(owned_library, graph.release)

    _dispatch(
        owned_library,
        EndEntryAccess(
            entry_id=entry.pk, statement=WayActStatement(JUNE, EndWay.REFUNDED, "")
        ),
    )

    entry.refresh_from_db()
    assert entry.access_end_way == "refunded"


def test_a_correction_needs_an_end_and_keeps_the_marker(owned_library, graph):
    entry = record_entry(owned_library, graph.release)
    refused = _refused(
        owned_library,
        CorrectEntryAccessEnd(entry_id=entry.pk, statement=_returned()),
    )
    assert "Record how it left first" in refused.sentence

    entry = end_entry_access(entry, ended=JUNE)
    marker = entry.access_end_recorded_at
    same = _dispatch(
        owned_library, CorrectEntryAccessEnd(entry_id=entry.pk, statement=_returned())
    )
    _dispatch(
        owned_library,
        CorrectEntryAccessEnd(
            entry_id=entry.pk, statement=WayActStatement(JULY, EndWay.EXPIRED, "")
        ),
    )

    entry.refresh_from_db()
    assert same.outcome is CommandOutcome.UNCHANGED
    assert (entry.access_ended, entry.access_end_way) == (JULY, "expired")
    assert entry.access_end_recorded_at == marker


def test_a_void_writes_the_end_back_and_repeats_unchanged(owned_library, graph):
    entry = end_entry_access(record_entry(owned_library, graph.release), note="lent")

    _dispatch(owned_library, VoidEntryAccessEnd(entry_id=entry.pk))
    again = _dispatch(owned_library, VoidEntryAccessEnd(entry_id=entry.pk))

    entry.refresh_from_db()
    assert again.outcome is CommandOutcome.UNCHANGED
    assert stated(entry, ENTRY_ACCESS_END) is None
    assert (entry.access_end_note, entry.access_end_way) == ("", "")


def test_a_resume_clears_the_end_and_a_new_end_follows(owned_library, graph):
    entry = end_entry_access(record_entry(owned_library, graph.release), ended=MAY)

    _dispatch(
        owned_library,
        ResumeEntryAccess(entry_id=entry.pk, statement=ActStatement(JUNE, " back ")),
    )
    entry.refresh_from_db()
    resumed = _last_event(entry)
    assert stated(entry, ENTRY_ACCESS_END) is None
    assert resumed.event_type == "library.libraryentry.access_resumed"
    assert resumed.payload == {"note": "back"}

    entry = end_entry_access(entry, way=EndWay.SOLD, ended=JULY)
    assert (entry.access_ended, entry.access_end_way) == (JULY, "sold")


def test_a_resume_without_an_end_is_refused_not_unchanged(owned_library, graph):
    entry = record_entry(owned_library, graph.release)

    refused = _refused(
        owned_library,
        ResumeEntryAccess(entry_id=entry.pk, statement=ActStatement(JUNE, "")),
    )

    assert "nothing to resume" in refused.sentence


def test_a_resume_may_state_no_day(owned_library, graph):
    entry = end_entry_access(record_entry(owned_library, graph.release), ended=MAY)

    _dispatch(
        owned_library,
        ResumeEntryAccess(entry_id=entry.pk, statement=ActStatement(None, "")),
    )

    assert _last_event(entry).effective_time is None


@pytest.mark.parametrize(
    ("acquired", "ended", "refused"),
    [
        (JULY, MAY, True),
        (MAY, JULY, False),
        (JULY, TemporalValue.parse("2021-05~"), False),
        (None, MAY, False),
    ],
)
def test_an_end_certainly_before_the_acquisition_is_refused(
    owned_library, graph, acquired, ended, refused
):
    entry = record_entry(owned_library, graph.release, acquired=acquired)
    command = EndEntryAccess(entry_id=entry.pk, statement=_returned(ended))

    if refused:
        assert _refused(owned_library, command).sentence == END_BEFORE_ACQUISITION
    else:
        assert _dispatch(owned_library, command).outcome is CommandOutcome.APPENDED


def test_a_correction_of_the_end_before_the_acquisition_is_refused(
    owned_library, graph
):
    entry = end_entry_access(
        record_entry(owned_library, graph.release, acquired=JUNE), ended=JULY
    )

    refused = _refused(
        owned_library,
        CorrectEntryAccessEnd(entry_id=entry.pk, statement=_returned(MAY)),
    )

    assert refused.sentence == END_BEFORE_ACQUISITION


def test_a_resume_certainly_before_the_end_is_refused(owned_library, graph):
    entry = end_entry_access(record_entry(owned_library, graph.release), ended=JULY)

    refused = _refused(
        owned_library,
        ResumeEntryAccess(entry_id=entry.pk, statement=ActStatement(MAY, "")),
    )

    assert refused.sentence == RESUME_BEFORE_END


def test_an_acquisition_after_a_standing_end_is_refused(owned_library, graph):
    entry = end_entry_access(
        record_entry(owned_library, graph.release, acquired=MAY), ended=JUNE
    )
    command = CorrectEntryAcquisition(
        entry_id=entry.pk, statement=ActStatement(JULY, "")
    )

    assert _refused(owned_library, command).sentence == ACQUISITION_AFTER_END


def test_an_acquisition_after_an_end_since_resumed_is_admitted(owned_library, graph):
    entry = end_entry_access(
        record_entry(owned_library, graph.release, acquired=MAY), ended=JUNE
    )
    _dispatch(
        owned_library,
        ResumeEntryAccess(entry_id=entry.pk, statement=ActStatement(JUNE, "")),
    )

    result = _dispatch(
        owned_library,
        CorrectEntryAcquisition(entry_id=entry.pk, statement=ActStatement(JULY, "")),
    )

    assert result.outcome is CommandOutcome.APPENDED


def test_a_removed_copy_answers_unchanged_then_refuses(owned_library, graph):
    entry = remove_entry(
        end_entry_access(record_entry(owned_library, graph.release), ended=JUNE)
    )

    same = _dispatch(
        owned_library, EndEntryAccess(entry_id=entry.pk, statement=_returned())
    )
    for command in (
        CorrectEntryAccessEnd(entry_id=entry.pk, statement=_returned(JULY)),
        VoidEntryAccessEnd(entry_id=entry.pk),
        ResumeEntryAccess(entry_id=entry.pk, statement=ActStatement(JULY, "")),
    ):
        assert _refused(owned_library, command).sentence == ENTRY_REMOVED
    assert same.outcome is CommandOutcome.UNCHANGED


@pytest.mark.parametrize(
    "command",
    [
        lambda entry: EndEntryAccess(entry_id=entry.pk, statement=_returned(JULY)),
        lambda entry: CorrectEntryAccessEnd(
            entry_id=entry.pk, statement=_returned(JULY)
        ),
        lambda entry: VoidEntryAccessEnd(entry_id=entry.pk),
        lambda entry: ResumeEntryAccess(
            entry_id=entry.pk, statement=ActStatement(JULY, "")
        ),
    ],
    ids=["end", "correct", "void", "resume"],
)
def test_every_act_is_refused_under_a_removed_player_game(
    owned_library, graph, command
):
    entry = record_entry(owned_library, graph.release)
    if not isinstance(command(entry), EndEntryAccess):
        entry = end_entry_access(entry, ended=JUNE)
    _dispatch(owned_library, RemovePlayerGame(game_id=graph.game.pk))

    assert _refused(owned_library, command(entry)).sentence == PLAYER_GAME_REMOVED


def test_a_foreign_way_is_refused_ahead_of_a_removed_copy(owned_library, graph):
    entry = remove_entry(record_entry(owned_library, graph.release))

    refused = _refused(
        owned_library,
        EndEntryAccess(
            entry_id=entry.pk,
            statement=WayActStatement(JUNE, "melted", ""),  # type: ignore[arg-type]
        ),
    )

    assert refused.sentence == UNKNOWN_WAY


@pytest.mark.parametrize(
    ("ended", "resumed"),
    [
        (None, MAY),
        (JULY, TemporalValue.parse("2021-05~")),
        (TemporalValue.parse("../2021-07"), MAY),
    ],
)
def test_a_resume_the_end_does_not_certainly_follow_is_admitted(
    owned_library, graph, ended, resumed
):
    entry = end_entry_access(record_entry(owned_library, graph.release), ended=ended)

    result = _dispatch(
        owned_library,
        ResumeEntryAccess(entry_id=entry.pk, statement=ActStatement(resumed, "")),
    )

    assert result.outcome is CommandOutcome.APPENDED


def test_another_librarys_copy_is_absent(owned_library, second_library, graph):
    entry = record_entry(owned_library, graph.release)

    for command in (
        EndEntryAccess(entry_id=entry.pk, statement=_returned()),
        CorrectEntryAccessEnd(entry_id=entry.pk, statement=_returned()),
        VoidEntryAccessEnd(entry_id=entry.pk),
        ResumeEntryAccess(entry_id=entry.pk, statement=ActStatement(JUNE, "")),
    ):
        with pytest.raises(RowNotHeld):
            _dispatch(second_library, command)


def test_every_act_replays_to_the_same_row(owned_library, graph):
    entry = record_entry(owned_library, graph.release, acquired=MAY)
    for command in (
        EndEntryAccess(entry_id=entry.pk, statement=_returned(JUNE, "lent")),
        CorrectEntryAccessEnd(entry_id=entry.pk, statement=_returned(JULY)),
        VoidEntryAccessEnd(entry_id=entry.pk),
        EndEntryAccess(entry_id=entry.pk, statement=_returned(JUNE)),
        ResumeEntryAccess(entry_id=entry.pk, statement=ActStatement(JULY, "")),
        EndEntryAccess(
            entry_id=entry.pk, statement=WayActStatement(JULY, EndWay.SOLD, "gone")
        ),
    ):
        with transaction.atomic():
            append_command(
                command,
                actor=owned_library.user,
                library=owned_library,
                idempotency_key=str(uuid.uuid7()),
                correlation_id=uuid.uuid7(),
            )
    before = LibraryEntry.objects.filter(pk=entry.pk).values().get()

    report = rebuild_projections(owned_library, mode=RebuildMode.CHECK)

    assert [
        (table.only_live, table.only_rebuilt, table.differing)
        for table in report.tables
        if table.table == "games_libraryentry"
    ] == [(0, 0, 0)]
    assert before["access_end_way"] == "sold"
    assert before["access_end_note"] == "gone"
