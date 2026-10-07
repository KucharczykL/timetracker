"""Every event type of the four families, replayed.

The dispatches need real transactions, and the conftest tracking
fixture would otherwise write projection rows no event states.
"""

from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, NamedTuple

import pytest
from django.db import connection

from games.catalog_writes import EditionState, ReleaseState, state_catalog_graph
from games.commands.device import (
    CorrectDeviceAccessEnd,
    CreateDevice,
    DescribeDevice,
    EndDeviceAccess,
    RemoveDevice,
    RestoreDevice,
    VoidDeviceAccessEnd,
)
from games.commands.endpoint import ActStatement, WayActStatement
from games.commands.historical_playtime import (
    HistoricalPlaytimeStatement,
    RecordHistoricalPlaytime,
    RemoveHistoricalPlaytime,
    RestateHistoricalPlaytime,
    RestoreHistoricalPlaytime,
)
from games.commands.libraryentry import (
    CorrectEntryAccessEnd,
    CorrectEntryAcquisition,
    DescribeEntry,
    EndEntryAccess,
    EntryStatement,
    RecordEntry,
    RemoveEntry,
    RestoreEntry,
    ResumeEntryAccess,
    VoidEntryAccessEnd,
)
from games.commands.playergame import (
    RecordPlayerGameFacts,
    RemovePlayerGame,
    RestorePlayerGame,
    TrackGame,
)
from games.commands.playersession import (
    CorrectedTiming,
    CorrectSessionTiming,
    CreateSession,
    DescribeSession,
    DurationOnlyTiming,
    EndSession,
    MoveSessionToPlaythrough,
    RemoveSession,
    RestoreSession,
    StatedDevice,
    StatedRelease,
    TimedTiming,
)
from games.commands.playthrough import (
    CompletePlaythrough,
    CorrectPlaythroughCompletion,
    CorrectPlaythroughStart,
    CreatePlaythrough,
    DescribePlaythrough,
    MovePlaythroughToGame,
    RemovePlaythrough,
    RestorePlaythrough,
    StartPlaythrough,
    VoidPlaythroughCompletion,
    VoidPlaythroughStart,
)
from games.commands.playthrough_count import (
    StatePlaythroughCount,
    UndoPlaythroughCount,
)
from games.commands.purchase import (
    CorrectPurchaseRefund,
    DescribePurchase,
    RecordPurchase,
    RefundPurchase,
    RemovePurchase,
    RestorePurchase,
    StatedPrice,
    UndoPurchaseRefund,
    VoidPurchaseRefund,
)
from games.commands.session_reclassification import (
    ReclassifySessionAsHistoricalPlaytime,
    UndoSessionReclassification,
    statement_from_session,
)
from games.end_ways import EndWay
from games.events.dispatch import Command, CommandOutcome, CommandResult, dispatch
from games.events.rebuild import RebuildMode, rebuild_projections
from games.events.replay import replay
from games.models import (
    Device,
    Game,
    HistoricalPlaytime,
    HistoricalPlaytimeProvenance,
    HistoricalPlaytimeRun,
    LibraryEntry,
    LibraryEvent,
    LibraryEventStreamHead,
    LibraryIdempotencyRecord,
    PlayerGame,
    PlayerGameStatus,
    PlayerSession,
    Playthrough,
    PlaythroughKind,
    Purchase,
    Release,
)
from games.projectors.device import Devices
from games.projectors.historical_playtime import HistoricalPlaytimes
from games.projectors.libraryentry import Entries
from games.projectors.playergame import PlayerGames
from games.projectors.playersession import PlayerSessions
from games.projectors.playthrough import Playthroughs
from games.projectors.purchase import Purchases
from games.reads.calendar import calendar_day_zone
from games.reads.playthrough_numbering import DISPLAY_ORDER_FIELDS
from games.retention import purging_library
from timetracker.temporal import TemporalValue

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.untracked_games,
]

#: No command states one; an importer takes it.
UNREACHABLE_KINDS = frozenset({PlaythroughKind.IMPORTED_HISTORY})


class DispatchedCommand(NamedTuple):
    """One command, and its idempotency key."""

    command: Command
    key: str


def _created_id(result: CommandResult) -> Any:
    """The row a creation wrote: its event's aggregate id."""
    assert result.sequences is not None
    return LibraryEvent.objects.get(
        stream_id=result.stream_id, sequence=result.sequences.first
    ).aggregate_id


def _default_releases(library, game: Game, count: int = 1) -> list[Release]:
    """Releases to name; a bare Game holds none."""
    written = state_catalog_graph(
        game=game,
        library=library,
        editions=[
            EditionState(
                key="edition-0",
                is_default=True,
                releases=tuple(
                    ReleaseState(
                        key=f"edition-0-release-{index}", is_default=index == 0
                    )
                    for index in range(count)
                ),
            )
        ],
    )
    return [entry.release for entry in written.editions[0].releases]


def assert_entries_belong_to_their_games(library) -> None:
    """Every entry's Release is its game's."""
    for entry in LibraryEntry._base_manager.filter(library=library).select_related(
        "release__edition", "player_game"
    ):
        assert entry.release.edition.game_id == entry.player_game.game_id, entry.pk


def build_stream(user, library) -> list[DispatchedCommand]:
    """Every type of the four families, through commands.

    Nothing appends by hand: the gate is a claim about what the write
    path produces, and an event this module wrote itself would prove
    only that the projector reads it.
    """
    first = Game.objects.create(library=library, name="Outer Wilds")
    second = Game.objects.create(library=library, name="Tunic")
    third = Game.objects.create(library=library, name="Hades")
    dispatched: list[DispatchedCommand] = []

    def run(command: Command, key: str) -> CommandResult:
        result = dispatch(command, actor=user, library=library, idempotency_key=key)
        assert result.outcome is CommandOutcome.APPENDED, (
            f"{key} recorded nothing, so the stream misses its event types."
        )
        dispatched.append(DispatchedCommand(command, key))
        return result

    run(TrackGame(game_id=first.pk), "track-first")
    run(TrackGame(game_id=second.pk), "track-second")
    run(TrackGame(game_id=third.pk), "track-third")

    first_run = Playthrough.objects.get(player_game__game=first)
    run(
        RecordPlayerGameFacts(
            game_id=first.pk, status=PlayerGameStatus.PLAYED, mastered=None
        ),
        "status-first",
    )
    #: A second word, so the column is no constant.
    run(
        RecordPlayerGameFacts(
            game_id=second.pk, status=PlayerGameStatus.ABANDONED, mastered=None
        ),
        "status-second",
    )
    run(
        RecordPlayerGameFacts(game_id=first.pk, status=None, mastered=True),
        "mastered-first",
    )
    #: On, then off: the false is stated, not defaulted.
    run(
        RecordPlayerGameFacts(game_id=second.pk, status=None, mastered=True),
        "mastered-second-on",
    )
    run(
        RecordPlayerGameFacts(game_id=second.pk, status=None, mastered=False),
        "mastered-second-off",
    )
    run(
        RecordPlayerGameFacts(game_id=first.pk, excluded_from_unfinished=True),
        "excluded-first",
    )
    run(
        RecordPlayerGameFacts(game_id=second.pk, excluded_from_unfinished=True),
        "excluded-second-on",
    )
    run(
        RecordPlayerGameFacts(game_id=second.pk, excluded_from_unfinished=False),
        "excluded-second-off",
    )
    run(
        RecordPlayerGameFacts(game_id=first.pk, excluded_from_dropped=True),
        "dropped-first",
    )
    run(
        RecordPlayerGameFacts(game_id=second.pk, excluded_from_dropped=True),
        "dropped-second-on",
    )
    run(
        RecordPlayerGameFacts(game_id=second.pk, excluded_from_dropped=False),
        "dropped-second-off",
    )
    run(
        StartPlaythrough(
            playthrough_id=first_run.pk,
            when=TemporalValue.from_day(date(2024, 1, 1)),
            note="Began here",
            #: A two-aggregate dispatch replays too.
            implies_status=True,
        ),
        "start-first-run",
    )
    run(
        CompletePlaythrough(
            playthrough_id=first_run.pk,
            when=TemporalValue.from_day(date(2024, 2, 1)),
            note="Ended here",
            #: A two-aggregate dispatch replays too.
            implies_status=True,
        ),
        "complete-first-run",
    )
    run(
        CorrectPlaythroughStart(
            playthrough_id=first_run.pk,
            when=TemporalValue.from_day(date(2023, 12, 24)),
            note="Played before that",
        ),
        "correct-start-first-run",
    )
    run(
        CorrectPlaythroughCompletion(
            playthrough_id=first_run.pk,
            when=TemporalValue.from_day(date(2024, 2, 14)),
            note="Finished later",
        ),
        "correct-completion-first-run",
    )
    run(
        DescribePlaythrough(
            playthrough_id=first_run.pk, name="Blind run", note="No hints"
        ),
        "describe-first-run",
    )

    run(
        CreatePlaythrough(
            game_id=first.pk, implies_played=False, implies_completed=False
        ),
        "create-second-run",
    )
    second_run = (
        Playthrough.objects.filter(player_game__game=first)
        .exclude(pk=first_run.pk)
        .get()
    )
    #: A stated act on no day: the marker stands, the date is null.
    run(
        StartPlaythrough(
            playthrough_id=second_run.pk,
            when=None,
            note="Before I kept dates",
            implies_status=False,
        ),
        "start-second-run-undated",
    )
    run(
        CompletePlaythrough(
            playthrough_id=second_run.pk,
            when=None,
            note="Some time later",
            implies_status=False,
        ),
        "complete-second-run-undated",
    )
    #: Both endpoints taken back, then stated again: a void
    #: leaves the run where a first statement is allowed.
    run(
        VoidPlaythroughStart(playthrough_id=second_run.pk),
        "void-start-second-run",
    )
    run(
        VoidPlaythroughCompletion(playthrough_id=second_run.pk),
        "void-completion-second-run",
    )
    run(
        StartPlaythrough(
            playthrough_id=second_run.pk,
            when=None,
            note="Before I kept dates",
            implies_status=False,
        ),
        "restate-start-second-run",
    )
    run(
        CompletePlaythrough(
            playthrough_id=second_run.pk,
            when=None,
            note="Some time later",
            implies_status=False,
        ),
        "restate-completion-second-run",
    )
    #: A name alone, then a note alone: one fact each.
    run(
        DescribePlaythrough(playthrough_id=second_run.pk, name="Undated", note=None),
        "name-second-run",
    )
    run(
        DescribePlaythrough(playthrough_id=second_run.pk, name=None, note="No days"),
        "note-second-run",
    )
    run(RemovePlaythrough(playthrough_id=second_run.pk), "remove-second-run")
    run(RestorePlaythrough(playthrough_id=second_run.pk), "restore-second-run")

    #: Left removed, so a stamped removed_at reaches the snapshot.
    run(
        CreatePlaythrough(
            game_id=first.pk, implies_played=False, implies_completed=False
        ),
        "create-third-run",
    )
    third_run = (
        Playthrough.objects.filter(player_game__game=first)
        .exclude(pk__in=(first_run.pk, second_run.pk))
        .get()
    )
    run(RemovePlaythrough(playthrough_id=third_run.pk), "remove-third-run")

    #: Sessions: one per mode, then every act on one.
    zone = calendar_day_zone(library).key
    device = Device.objects.get(
        pk=_created_id(
            run(CreateDevice(name="Deck", type=Device.UNKNOWN), "create-device")
        )
    )
    run(
        DescribeDevice(device_id=device.pk, name="Steam Deck", type=Device.HANDHELD),
        "describe-device",
    )
    #: Left removed so removed_at reaches snapshot.
    retired = Device.objects.get(
        pk=_created_id(run(CreateDevice(name="Tower", type=Device.PC), "create-tower"))
    )
    run(RemoveDevice(device_id=retired.pk), "remove-tower")
    run(RestoreDevice(device_id=retired.pk), "restore-tower")
    run(RemoveDevice(device_id=retired.pk), "remove-tower-again")
    #: Every end act; left stated for snapshot.
    sold = WayActStatement(TemporalValue.parse("2023-11"), EndWay.SOLD, "to a friend")
    run(EndDeviceAccess(device_id=device.pk, statement=sold), "end-deck")
    run(VoidDeviceAccessEnd(device_id=device.pk), "void-deck-end")
    run(EndDeviceAccess(device_id=device.pk, statement=sold), "end-deck-again")
    run(
        CorrectDeviceAccessEnd(
            device_id=device.pk,
            statement=WayActStatement(None, EndWay.LOST, ""),
        ),
        "correct-deck-end",
    )
    run(
        CreateDevice(
            name="Phone",
            type=Device.MOBILE,
            access_end=WayActStatement(None, EndWay.BROKEN, ""),
        ),
        "create-broken-phone",
    )
    noon = datetime(2024, 1, 5, 12, tzinfo=UTC)
    timed = _created_id(
        run(
            CreateSession(
                playthrough_id=first_run.pk,
                timing=TimedTiming(started_at=noon, day_zone=zone),
                implies_played=False,
            ),
            "create-timed-session",
        )
    )
    duration_only = _created_id(
        run(
            CreateSession(
                playthrough_id=first_run.pk,
                timing=DurationOnlyTiming(
                    day=date(2024, 1, 3), duration=timedelta(minutes=45)
                ),
                note="From memory",
                implies_played=False,
            ),
            "create-duration-only-session",
        )
    )
    corrected = _created_id(
        run(
            CreateSession(
                playthrough_id=first_run.pk,
                timing=CorrectedTiming(
                    started_at=noon + timedelta(days=1),
                    ended_at=noon + timedelta(days=1, hours=3),
                    duration=timedelta(hours=2),
                    day_zone=zone,
                ),
                device_id=device.pk,
                implies_played=False,
            ),
            "create-corrected-session",
        )
    )
    run(
        EndSession(
            session_id=timed, ended_at=noon + timedelta(hours=1), ended_at_zone=None
        ),
        "end-timed-session",
    )
    #: A correction that changes the mode and every timing column.
    run(
        CorrectSessionTiming(
            session_id=duration_only,
            timing=TimedTiming(
                started_at=noon + timedelta(days=2),
                day_zone=zone,
                ended_at=noon + timedelta(days=2, minutes=30),
            ),
        ),
        "correct-duration-only-session",
    )
    #: Three facts at once: three events.
    run(
        DescribeSession(
            session_id=corrected,
            note="Long one",
            device=StatedDevice(None),
            emulated=True,
        ),
        "describe-corrected-session",
    )
    second_game_run = Playthrough.objects.get(player_game__game=second)
    run(
        MoveSessionToPlaythrough(
            session_id=corrected, playthrough_id=second_game_run.pk
        ),
        "move-corrected-session",
    )
    run(RemoveSession(session_id=timed), "remove-timed-session")
    run(RestoreSession(session_id=timed), "restore-timed-session")
    #: Left removed, as the third run and the third game are.
    run(RemoveSession(session_id=duration_only), "remove-duration-only-session")

    #: Two-run record restated; one removed; one restored.
    a_statement = HistoricalPlaytimeStatement(
        duration=timedelta(hours=100),
        when="2005",
        provenance=HistoricalPlaytimeProvenance.ESTIMATED,
        playthrough_ids=(first_run.pk, second_run.pk),
        device_id=None,
        release_id=None,
        emulated=False,
        note="",
    )
    restated_record = _created_id(
        run(RecordHistoricalPlaytime(statement=a_statement), "record-two-runs")
    )
    run(
        RestateHistoricalPlaytime(
            record_id=restated_record,
            statement=replace(
                a_statement,
                duration=timedelta(hours=50),
                when="2005-06~",
                provenance=HistoricalPlaytimeProvenance.MANUALLY_ENTERED,
                playthrough_ids=(first_run.pk,),
                device_id=device.pk,
                emulated=True,
                note="Read off the launcher",
            ),
        ),
        "restate-onto-one-run",
    )
    removed_record = _created_id(
        run(
            RecordHistoricalPlaytime(
                statement=replace(
                    a_statement, when=None, playthrough_ids=(first_run.pk,)
                )
            ),
            "record-to-remove",
        )
    )
    run(RemoveHistoricalPlaytime(record_id=removed_record), "remove-record")
    restored_record = _created_id(
        run(
            RecordHistoricalPlaytime(
                statement=replace(
                    a_statement,
                    when="2006/2007",
                    provenance=HistoricalPlaytimeProvenance.EXTERNALLY_MEASURED,
                    playthrough_ids=(first_run.pk,),
                )
            ),
            "record-to-restore",
        )
    )
    run(RemoveHistoricalPlaytime(record_id=restored_record), "remove-record-again")
    run(RestoreHistoricalPlaytime(record_id=restored_record), "restore-record")

    #: A run moved to the second game; its record follows.
    moving_run = _created_id(
        run(
            CreatePlaythrough(
                game_id=first.pk, implies_played=False, implies_completed=False
            ),
            "create-run-to-move",
        )
    )
    run(
        RecordHistoricalPlaytime(
            statement=replace(a_statement, playthrough_ids=(moving_run,))
        ),
        "record-on-run-to-move",
    )
    run(
        MovePlaythroughToGame(playthrough_id=moving_run, game_id=second.pk),
        "move-run",
    )

    #: A session that became a record.
    converted = _created_id(
        run(
            CreateSession(
                playthrough_id=first_run.pk,
                timing=DurationOnlyTiming(
                    day=date(2024, 2, 9), duration=timedelta(hours=9)
                ),
                note="Off the launcher",
                implies_played=False,
            ),
            "create-session-to-reclassify",
        )
    )
    run(
        ReclassifySessionAsHistoricalPlaytime(
            session_id=converted,
            statement=statement_from_session(PlayerSession.objects.get(pk=converted)),
        ),
        "reclassify-session",
    )
    #: A second one, put back again.
    undone = _created_id(
        run(
            CreateSession(
                playthrough_id=first_run.pk,
                timing=DurationOnlyTiming(
                    day=date(2024, 2, 10), duration=timedelta(hours=11)
                ),
                implies_played=False,
            ),
            "create-session-to-reclassify-and-undo",
        )
    )
    run(
        ReclassifySessionAsHistoricalPlaytime(
            session_id=undone,
            statement=statement_from_session(PlayerSession.objects.get(pk=undone)),
        ),
        "reclassify-session-to-undo",
    )
    run(
        UndoSessionReclassification(session_id=undone),
        "undo-reclassification",
    )

    #: Two copies on one Release; one untracked game.
    first_release, first_other = _default_releases(library, first, count=2)
    (second_release,) = _default_releases(library, second)
    fourth = Game.objects.create(library=library, name="Stardew Valley")
    (fourth_release,) = _default_releases(library, fourth)
    kept_entry = _created_id(
        run(
            RecordEntry(
                release_id=first_release.pk,
                access="owned",
                format="digital",
                acquired=ActStatement(TemporalValue.parse("2021-05"), "birthday"),
            ),
            "record-entry",
        )
    )
    second_copy = _created_id(
        run(
            RecordEntry(
                release_id=first_release.pk, access="borrowed", format="physical"
            ),
            "record-entry-twice",
        )
    )
    #: A session and a record name a Release; a run move clears both.
    released_run = _created_id(
        run(
            CreatePlaythrough(
                game_id=first.pk, implies_played=False, implies_completed=False
            ),
            "create-released-run",
        )
    )
    released = _created_id(
        run(
            CreateSession(
                playthrough_id=released_run,
                timing=TimedTiming(
                    started_at=noon + timedelta(days=9),
                    day_zone=zone,
                    ended_at=noon + timedelta(days=9, hours=1),
                ),
                release_id=first_release.pk,
                implies_played=False,
            ),
            "create-released-session",
        )
    )
    run(
        DescribeSession(session_id=released, release=StatedRelease(None)),
        "unstate-session-release",
    )
    run(
        DescribeSession(session_id=released, release=StatedRelease(first_release.pk)),
        "state-session-release",
    )
    run(
        RecordHistoricalPlaytime(
            statement=replace(
                a_statement,
                playthrough_ids=(released_run,),
                release_id=first_release.pk,
            )
        ),
        "record-released",
    )
    run(
        MovePlaythroughToGame(playthrough_id=released_run, game_id=second.pk),
        "move-released-run",
    )
    #: Tracking pair, then the copy: three events.
    run(
        RecordEntry(
            release_id=fourth_release.pk, access="subscription", format="unknown"
        ),
        "record-entry-untracked",
    )
    run(
        DescribeEntry(
            entry_id=kept_entry,
            access="rented",
            format="unknown",
            note="lent",
            release_id=first_other.pk,
        ),
        "describe-entry",
    )
    run(
        CorrectEntryAcquisition(
            entry_id=kept_entry, statement=ActStatement(None, "no receipt")
        ),
        "correct-entry-acquisition",
    )
    run(
        EndEntryAccess(
            entry_id=kept_entry,
            statement=WayActStatement(
                TemporalValue.parse("2022-01"), EndWay.RETURNED, "lent"
            ),
        ),
        "end-entry-access",
    )
    run(
        CorrectEntryAccessEnd(
            entry_id=kept_entry,
            statement=WayActStatement(
                TemporalValue.parse("2022-02"), EndWay.EXPIRED, ""
            ),
        ),
        "correct-entry-access-end",
    )
    run(VoidEntryAccessEnd(entry_id=kept_entry), "void-entry-access-end")
    run(
        EndEntryAccess(
            entry_id=kept_entry,
            statement=WayActStatement(None, EndWay.SOLD, ""),
        ),
        "end-entry-access-again",
    )
    run(
        ResumeEntryAccess(
            entry_id=kept_entry,
            statement=ActStatement(TemporalValue.parse("2023"), "bought back"),
        ),
        "resume-entry-access",
    )
    #: Left ended, so the end's columns are compared.
    run(
        EndEntryAccess(
            entry_id=kept_entry,
            statement=WayActStatement(
                TemporalValue.parse("2024"), EndWay.GIVEN_AWAY, "to a friend"
            ),
        ),
        "end-entry-access-last",
    )
    run(RemoveEntry(entry_id=kept_entry), "remove-entry")
    run(RestoreEntry(entry_id=kept_entry), "restore-entry")
    removed_entry = _created_id(
        run(
            RecordEntry(release_id=second_release.pk, access="demo", format="digital"),
            "record-entry-to-remove",
        )
    )
    #: Left removed, so the mark is compared.
    run(RemoveEntry(entry_id=removed_entry), "remove-entry-again")

    kept_purchase = _created_id(
        run(
            RecordPurchase(
                kind="game",
                copy=kept_entry,
                name="Deluxe",
                price=StatedPrice(Decimal("12.50"), "EUR"),
                purchased=ActStatement(TemporalValue.parse("2021-05"), "sale"),
            ),
            "record-purchase",
        )
    )
    #: Tracking pair, the copy, then the purchase.
    fifth = Game.objects.create(library=library, name="Celeste")
    (fifth_release,) = _default_releases(library, fifth)
    run(
        RecordPurchase(
            kind="season_pass",
            copy=EntryStatement(
                release_id=fifth_release.pk, access="owned", format="digital"
            ),
        ),
        "record-purchase-new-copy",
    )
    run(
        DescribePurchase(
            purchase_id=kept_purchase,
            kind="upgrade",
            name="Ultimate",
            price=StatedPrice(None, ""),
            note="gift",
            entry_id=second_copy,
        ),
        "describe-purchase",
    )
    run(
        DescribePurchase(
            purchase_id=kept_purchase, purchased=ActStatement(None, "no receipt")
        ),
        "correct-purchase-day",
    )
    #: A game on a new owned copy: refunds couple.
    refundable_copy = _created_id(
        run(
            RecordEntry(release_id=fifth_release.pk, access="owned", format="physical"),
            "record-entry-to-refund",
        )
    )
    refunded_purchase = _created_id(
        run(
            RecordPurchase(
                kind="game",
                copy=refundable_copy,
                purchased=ActStatement(TemporalValue.parse("2022-01"), ""),
            ),
            "record-purchase-to-refund",
        )
    )
    run(
        RefundPurchase(
            purchase_id=refunded_purchase,
            statement=ActStatement(TemporalValue.parse("2022-02"), "store"),
        ),
        "refund-purchase",
    )
    run(
        CorrectPurchaseRefund(
            purchase_id=refunded_purchase,
            statement=ActStatement(TemporalValue.parse("2022-03"), "store"),
        ),
        "correct-purchase-refund",
    )
    run(VoidPurchaseRefund(purchase_id=refunded_purchase), "void-purchase-refund")
    undone = run(
        RefundPurchase(
            purchase_id=refunded_purchase,
            statement=ActStatement(TemporalValue.parse("2022-03"), ""),
        ),
        "refund-purchase-to-undo",
    )
    assert undone.sequences is not None
    run(
        UndoPurchaseRefund(
            purchase_id=refunded_purchase, refunded_at=undone.sequences.first
        ),
        "undo-purchase-refund",
    )
    #: Left refunded, so the columns are compared.
    run(
        RefundPurchase(
            purchase_id=refunded_purchase,
            statement=ActStatement(TemporalValue.parse("2022-04"), "again"),
        ),
        "refund-purchase-again",
    )
    run(RemovePurchase(purchase_id=kept_purchase), "remove-purchase")
    run(RestorePurchase(purchase_id=kept_purchase), "restore-purchase")
    removed_purchase = _created_id(
        run(
            RecordPurchase(kind="game", copy=second_copy),
            "record-purchase-to-remove",
        )
    )
    #: Left removed, so the mark is compared.
    run(RemovePurchase(purchase_id=removed_purchase), "remove-purchase-again")
    #: A copy's removal takes its purchases.
    run(RemoveEntry(entry_id=refundable_copy), "remove-copy-with-purchase")
    run(RestoreEntry(entry_id=refundable_copy), "restore-copy-with-purchase")
    cascaded_copy = _created_id(
        run(
            RecordEntry(release_id=fifth_release.pk, access="owned", format="digital"),
            "record-copy-to-cascade",
        )
    )
    run(RecordPurchase(kind="game", copy=cascaded_copy), "record-purchase-to-cascade")
    #: Left removed with its purchase.
    run(RemoveEntry(entry_id=cascaded_copy), "remove-copy-and-purchase")

    counted = Game.objects.create(library=library, name="Celeste")
    run(TrackGame(game_id=counted.pk), "track-counted")
    run(StatePlaythroughCount(game_id=counted.pk, count=3), "count-raise")
    #: To zero: removes runs, voids the last.
    lowered = run(StatePlaythroughCount(game_id=counted.pk, count=0), "count-lower")
    run(
        UndoPlaythroughCount(
            game_id=counted.pk, statement=lowered.correlation_id, stated=0
        ),
        "count-undo",
    )

    run(RemovePlayerGame(game_id=second.pk), "remove-second-game")
    run(RestorePlayerGame(game_id=second.pk), "restore-second-game")
    #: Left removed, for the same reason as the third run.
    run(RemovePlayerGame(game_id=third.pk), "remove-third-game")
    return dispatched


def registered_event_types() -> set[str]:
    """Every type the seven listed projectors read."""
    return {
        spec.event_type
        for handles in (
            Devices.handles,
            Entries.handles,
            Purchases.handles,
            PlayerGames.handles,
            Playthroughs.handles,
            PlayerSessions.handles,
            HistoricalPlaytimes.handles,
        )
        for spec in handles
    }


def missing_event_types(library) -> set[str]:
    """Every registered type this stream never appended."""
    appended = set(
        LibraryEvent.objects.filter(library=library).values_list(
            "event_type", flat=True
        )
    )
    return registered_event_types() - appended


def test_the_stream_carries_every_registered_event_type(owned_user, owned_library):
    """A type the stream misses goes untested."""
    build_stream(owned_user, owned_library)

    assert missing_event_types(owned_library) == set()


def test_the_guard_names_a_type_a_partial_stream_missed(owned_user, owned_library):
    """A real stream, short of sixty-four types."""
    game = Game.objects.create(library=owned_library, name="Celeste")
    dispatch(
        TrackGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="partial-track",
    )

    missing = missing_event_types(owned_library)

    #: What TrackGame appends, so neither is named.
    assert missing == registered_event_types() - {
        "library.playergame.created",
        "library.playthrough.created",
    }
    assert len(missing) == 65


def build_neighbour(user, library) -> None:
    """A shorter stream every step leaves alone.

    Each dispatch is asserted, because a build that quietly wrote
    nothing would turn every neighbour comparison into two empty lists
    agreeing with each other.
    """
    game = Game.objects.create(library=library, name="Hollow Knight")
    for command, key in (
        (TrackGame(game_id=game.pk), "neighbour-track"),
        (
            RecordPlayerGameFacts(
                game_id=game.pk, status=PlayerGameStatus.COMPLETED, mastered=None
            ),
            "neighbour-status",
        ),
    ):
        result = dispatch(command, actor=user, library=library, idempotency_key=key)
        assert result.outcome is CommandOutcome.APPENDED, key
    #: One row in the third table, so its xmin is watched too.
    run = Playthrough.objects.get(player_game__game=game)
    result = dispatch(
        CreateSession(
            playthrough_id=run.pk,
            timing=DurationOnlyTiming(
                day=date(2024, 3, 1), duration=timedelta(hours=1)
            ),
            implies_played=False,
        ),
        actor=user,
        library=library,
        idempotency_key="neighbour-session",
    )
    assert result.outcome is CommandOutcome.APPENDED, "neighbour-session"
    #: One record; both new tables hold neighbours.
    result = dispatch(
        RecordHistoricalPlaytime(
            statement=HistoricalPlaytimeStatement(
                duration=timedelta(hours=10),
                when="2019",
                provenance=HistoricalPlaytimeProvenance.ESTIMATED,
                playthrough_ids=(run.pk,),
                device_id=None,
                release_id=None,
                emulated=False,
                note="",
            )
        ),
        actor=user,
        library=library,
        idempotency_key="neighbour-record",
    )
    assert result.outcome is CommandOutcome.APPENDED, "neighbour-record"
    #: One entry; the sixth table holds a neighbour.
    (release,) = _default_releases(library, game)
    result = dispatch(
        RecordEntry(release_id=release.pk, access="owned", format="physical"),
        actor=user,
        library=library,
        idempotency_key="neighbour-entry",
    )
    assert result.outcome is CommandOutcome.APPENDED, "neighbour-entry"
    #: A neighbour in the seventh table.
    result = dispatch(
        RecordPurchase(
            kind="game",
            copy=LibraryEntry.objects.get(library=library).pk,
        ),
        actor=user,
        library=library,
        idempotency_key="neighbour-purchase",
    )
    assert result.outcome is CommandOutcome.APPENDED, "neighbour-purchase"


@pytest.fixture
def neighbour(django_user_model):
    """A second owner with their own library."""
    user = django_user_model.objects.create_user(
        username="gate-neighbour", password="p"
    )
    build_neighbour(user, user.library)
    return user.library


#: One table's rows, as `.values()` answers them.
type ProjectionRows = list[Mapping[str, Any]]


type ProjectionSnapshot = tuple[
    ProjectionRows,
    ProjectionRows,
    ProjectionRows,
    ProjectionRows,
    ProjectionRows,
    ProjectionRows,
    ProjectionRows,
]


def rows_of(library) -> ProjectionSnapshot:
    """Seven tables' whole rows, in key order.

    `.values()` rather than a column list, so a column added later is
    in the comparison the day it lands. Refuses an empty table, because
    every caller compares two snapshots and two empty ones agree
    whatever the step between them did.
    """
    tracked: ProjectionRows = list(
        PlayerGame.objects.filter(library=library).order_by("pk").values()
    )
    runs: ProjectionRows = list(
        Playthrough.objects.filter(library=library).order_by("pk").values()
    )
    sessions: ProjectionRows = list(
        PlayerSession.objects.filter(library=library).order_by("pk").values()
    )
    records: ProjectionRows = list(
        HistoricalPlaytime.objects.filter(library=library).order_by("pk").values()
    )
    joins: ProjectionRows = list(
        HistoricalPlaytimeRun.objects.filter(library=library).order_by("pk").values()
    )
    entries: ProjectionRows = list(
        LibraryEntry.objects.filter(library=library).order_by("pk").values()
    )
    purchases: ProjectionRows = list(
        Purchase.objects.filter(library=library).order_by("pk").values()
    )
    assert all((tracked, runs, sessions, records, joins, entries, purchases)), (
        f"Library {library.pk} holds no rows to compare."
    )
    return (tracked, runs, sessions, records, joins, entries, purchases)


def row_versions(library) -> list[tuple[str, str]]:
    """Each row's key and its `xmin`, in key order.

    A rewrite moves `xmin` even where it writes the values the row
    already held, which is what parts an untouched neighbour from one
    an unscoped replay upserted over.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id::text, xmin::text FROM games_playergame WHERE library_id = %s
            UNION ALL
            SELECT id::text, xmin::text FROM games_playthrough WHERE library_id = %s
            UNION ALL
            SELECT id::text, xmin::text FROM games_playersession WHERE library_id = %s
            UNION ALL
            SELECT id::text, xmin::text FROM games_historicalplaytime WHERE library_id = %s
            UNION ALL
            SELECT id::text, xmin::text FROM games_historicalplaytimerun WHERE library_id = %s
            UNION ALL
            SELECT id::text, xmin::text FROM games_libraryentry WHERE library_id = %s
            UNION ALL
            SELECT id::text, xmin::text FROM games_purchase WHERE library_id = %s
            ORDER BY 1
            """,
            [library.pk] * 7,
        )
        return cursor.fetchall()


def empty_projections(library) -> None:
    """By library, children first; records before sessions."""
    #: Purchase events name entries; retention refuses.
    with purging_library():
        Purchase.objects.filter(library=library).delete()
        LibraryEntry.objects.filter(library=library).delete()
        HistoricalPlaytimeRun.objects.filter(library=library).delete()
        HistoricalPlaytime.objects.filter(library=library).delete()
        PlayerSession.objects.filter(library=library).delete()
        Playthrough.objects.filter(library=library).delete()
        PlayerGame.objects.filter(library=library).delete()


def test_replaying_an_emptied_library_reproduces_every_table(
    owned_user, owned_library, neighbour
):
    """Every column, including the clock-derived ones."""
    build_stream(owned_user, owned_library)
    before = rows_of(owned_library)
    untouched = rows_of(neighbour)
    unwritten = row_versions(neighbour)
    empty_projections(owned_library)

    result = replay(owned_library)

    assert result.replayed_through == (
        LibraryEventStreamHead.objects.get(library=owned_library).current_sequence
    )
    assert rows_of(owned_library) == before
    assert rows_of(neighbour) == untouched
    #: Values alone cannot part untouched from upserted alike.
    assert row_versions(neighbour) == unwritten
    assert_entries_belong_to_their_games(owned_library)


def test_a_rebuild_swaps_every_table_with_an_empty_diff(
    owned_user, owned_library, neighbour
):
    """The rebuild's own diff, not this module's."""
    build_stream(owned_user, owned_library)
    untouched = rows_of(neighbour)

    report = rebuild_projections(owned_library, mode=RebuildMode.REBUILD)

    assert report.swapped is True
    assert [
        (table.table, table.only_live, table.only_rebuilt, table.differing)
        for table in report.tables
    ] == [
        ("games_device", 0, 0, 0),
        ("games_historicalplaytime", 0, 0, 0),
        ("games_historicalplaytimerun", 0, 0, 0),
        ("games_librarycalendar", 0, 0, 0),
        ("games_libraryentry", 0, 0, 0),
        ("games_playergame", 0, 0, 0),
        ("games_playersession", 0, 0, 0),
        ("games_playthrough", 0, 0, 0),
        ("games_purchase", 0, 0, 0),
    ]
    assert rows_of(neighbour) == untouched
    assert_entries_belong_to_their_games(owned_library)


def test_every_command_repeated_under_its_key_records_nothing(
    owned_user, owned_library, neighbour
):
    """A repeat answers from the record."""
    dispatched = build_stream(owned_user, owned_library)
    before = rows_of(owned_library)
    untouched = rows_of(neighbour)
    unwritten = row_versions(neighbour)
    head_before = LibraryEventStreamHead.objects.get(
        library=owned_library
    ).current_sequence
    events_before = LibraryEvent.objects.filter(library=owned_library).count()

    for command, key in dispatched:
        result = dispatch(
            command, actor=owned_user, library=owned_library, idempotency_key=key
        )
        assert result.outcome is CommandOutcome.REPLAYED, key

    assert (
        LibraryEventStreamHead.objects.get(library=owned_library).current_sequence
        == head_before
    )
    assert LibraryEvent.objects.filter(library=owned_library).count() == events_before
    assert rows_of(owned_library) == before
    assert rows_of(neighbour) == untouched
    #: Values alone cannot part untouched from upserted alike.
    assert row_versions(neighbour) == unwritten
    assert LibraryIdempotencyRecord.objects.filter(
        library=owned_library
    ).count() == len({key for _command, key in dispatched})


def test_the_display_number_is_ordered_by_a_total_key():
    """The key last is what a swap cannot renumber.

    Two runs recorded in one instant tie on the first three sort
    fields. RowNumber over peers follows the plan's input order, and
    a swap changes that -- so the fourth field, which is unique, is
    the whole reason a rebuild leaves the numbers alone.
    """
    assert DISPLAY_ORDER_FIELDS[-1] == "id"


def test_the_stream_leaves_a_removed_row_in_each_table(owned_user, owned_library):
    """A restored row states no removed_at to compare."""
    build_stream(owned_user, owned_library)

    assert PlayerGame.objects.filter(
        library=owned_library, removed_at__isnull=False
    ).exists()
    assert Playthrough.objects.filter(
        library=owned_library, removed_at__isnull=False
    ).exists()
    assert PlayerSession.objects.filter(
        library=owned_library, removed_at__isnull=False
    ).exists()
    assert HistoricalPlaytime.objects.filter(
        library=owned_library, removed_at__isnull=False
    ).exists()
    assert LibraryEntry.objects.filter(
        library=owned_library, removed_at__isnull=False
    ).exists()
    assert Purchase.objects.filter(
        library=owned_library, removed_at__isnull=False
    ).exists()


def test_the_gate_replays_every_reachable_playthrough_kind(owned_user, owned_library):
    """A new kind fails here until a step states it."""
    build_stream(owned_user, owned_library)

    stated = set(
        Playthrough.objects.filter(library=owned_library).values_list("kind", flat=True)
    )

    assert stated == {kind for kind in PlaythroughKind} - UNREACHABLE_KINDS
