"""A start for the runs #684 left empty. #1038.

#684 states one run per legacy PlayEvent row, and one empty
default for a tracked game holding none. Most tracked games
held none, so most runs state no day at all while a status
change and a session both record when play began. This pass
states that day, and states no completion.
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, fields
from datetime import date
from enum import StrEnum
from typing import NamedTuple

from django.db import transaction
from django.db.models import Min
from django.db.models.functions import TruncDate
from django.utils import timezone

from games.backfill.appending import append_one
from games.backfill.mismatch import Mismatch
from games.events.playthrough import (
    PLAYTHROUGH_CREATED,
    PLAYTHROUGH_STARTED,
    playthrough_started,
)
from games.models import (
    LibraryEvent,
    Playthrough,
    PlaythroughKind,
    Session,
    UserLibrary,
)
from games.preflight.playthrough import candidate_events
from games.reads.playthrough_activity import activity_clock
from timetracker.temporal import TemporalValue

#: The two evidence days are read in different zones. A status
#: day was frozen when #676 ran, by transition_effective_time,
#: which reads the server's TIME_ZONE. A session day is read now
#: in the viewer's DISPLAY_TIME_ZONE. The legacy timestamp the
#: status day came from is in a table #771 takes, so the frozen
#: day cannot be read again. The report prints both.

#: Named in every key and every metadata value.
START_ISSUE = 1038
KEY_PREFIX = f"backfill:{START_ISSUE}:playthrough-start"

#: The issue whose defaults this repairs.
CONVERSION_ISSUE = 684


class StartSource(StrEnum):
    """Which record dated the start."""

    STATUS = "status"
    SESSION = "session"


class Evidence(NamedTuple):
    """A day, and the record that states it."""

    day: date
    source: StartSource


class RunInScope(NamedTuple):
    """One empty default, and what dates it."""

    run_id: uuid.UUID
    player_game_id: uuid.UUID
    game_id: uuid.UUID


def default_run_ids(library: UserLibrary) -> set[uuid.UUID]:
    """Every run #684 minted holding no legacy row.

    The creation event names its origin and the projection row
    names none, so the stream answers this. A creation #684
    made from a row names that row; a default names none, which
    is what the excluded key reads.
    """
    return set(
        LibraryEvent.objects.filter(
            library=library,
            event_type=PLAYTHROUGH_CREATED.event_type,
            source_metadata__origin="backfill",
            source_metadata__issue=CONVERSION_ISSUE,
        )
        .exclude(source_metadata__has_key="play_event_id")
        .values_list("aggregate_id", flat=True)
    )


def runs_in_scope(library: UserLibrary) -> list[RunInScope]:
    """The empty defaults this pass may date.

    Six conditions, and the sixth carries the weight: a person
    may create a blank run and #679 states one at track time.
    Neither is this pass's debt.

    values_list rather than rows, so the columns this reads are
    named: a migration replaying it against a later schema
    cannot select a column that is not there yet.
    """
    identifiers = default_run_ids(library)
    if not identifiers:
        return []
    rows = (
        Playthrough.objects.filter(
            pk__in=identifiers,
            library=library,
            kind=PlaythroughKind.ORDINARY,
            removed_at__isnull=True,
            start_recorded_at__isnull=True,
            completion_recorded_at__isnull=True,
            player_game__removed_at__isnull=True,
            player_game__game__removed_at__isnull=True,
        )
        .order_by("pk")
        .values_list("pk", "player_game_id", "player_game__game_id")
    )
    return [
        RunInScope(run_id=run_id, player_game_id=player_game_id, game_id=game_id)
        for run_id, player_game_id, game_id in rows
    ]


def status_days(library: UserLibrary) -> dict[uuid.UUID, date]:
    """The earliest #676 status day, per tracked game.

    candidate_events() reads the whole library in one scan,
    because LibraryEvent indexes neither the type nor the
    payload. A query per run would pay that scan 858 times.

    The four statuses are the whole list: legacy Game.Status
    held u, p, f, r and a, so a #676 event carries no other
    word and shelved cannot appear.
    """
    earliest: dict[uuid.UUID, date] = {}
    candidates, _undated = candidate_events(library)
    for candidate in candidates:
        tracked_id = candidate.key.aggregate_id
        day = candidate.key.day
        if tracked_id not in earliest or day < earliest[tracked_id]:
            earliest[tracked_id] = day
    return earliest


def session_days(library: UserLibrary) -> dict[uuid.UUID, date]:
    """The earliest live session day, per game.

    Read in the viewer's own zone, through the very clock
    games/reads/playthrough_activity.py reads a day with, so
    the day this states and the day the Activity column
    counts from cannot come from two calendars. A game the
    library does not own answers nothing, so a run at a
    shared catalog game reads no session.
    """
    zone = activity_clock(library).zone
    rows = (
        Session.objects.alive()
        .filter(game__library=library, game__removed_at__isnull=True)
        #: Cleared, so the grouping keys on the game alone.
        .order_by()
        .annotate(played_day=TruncDate("timestamp_start", tzinfo=zone))
        .values("game_id")
        .annotate(first_day=Min("played_day"))
        .values_list("game_id", "first_day")
    )
    return {game_id: day for game_id, day in rows if day is not None}


def evidence_for(
    run: RunInScope,
    *,
    status: Mapping[uuid.UUID, date],
    session: Mapping[uuid.UUID, date],
) -> Evidence | None:
    """The day this run's start takes, and what dated it.

    The earlier wins: a status set years after the play must
    not outrank a session that proves the play, and a game
    marked Played with no session still states a day. On an
    equal day the session is named, because it records play.
    """
    status_day = status.get(run.player_game_id)
    session_day = session.get(run.game_id)
    if status_day is None:
        #: Nested, so the day mypy reads here is a date.
        if session_day is None:
            return None
        return Evidence(session_day, StartSource.SESSION)
    if session_day is None:
        return Evidence(status_day, StartSource.STATUS)
    if session_day <= status_day:
        return Evidence(session_day, StartSource.SESSION)
    return Evidence(status_day, StartSource.STATUS)


@dataclass(frozen=True, slots=True)
class StartRepairCounts:
    """What one pass did, summable everywhere."""

    libraries: int = 0
    runs_in_scope: int = 0
    #: A run in scope holding neither record.
    no_evidence: int = 0
    status_only: int = 0
    session_only: int = 0
    both: int = 0
    #: Of the runs holding both, the days that match.
    both_agree: int = 0
    from_status: int = 0
    from_session: int = 0
    events_appended: int = 0

    def __add__(self, other: StartRepairCounts) -> StartRepairCounts:
        return StartRepairCounts(
            **{
                field.name: getattr(self, field.name) + getattr(other, field.name)
                for field in fields(self)
            }
        )

    def as_dict(self) -> dict[str, int]:
        return {field.name: getattr(self, field.name) for field in fields(self)}


#: The value an accumulation starts from.
NO_START_COUNTS = StartRepairCounts()


@dataclass(frozen=True, slots=True)
class RepairResult:
    """What the pass stated, for the gate to read."""

    counts: StartRepairCounts
    #: The day and source each repaired run took.
    stated: Mapping[uuid.UUID, Evidence]
    #: Runs in scope this pass left stating no act.
    left_alone: tuple[uuid.UUID, ...]


def repair_library(library: UserLibrary) -> RepairResult:
    """State a start for every empty default holding evidence.

    recorded_at is now. Nothing recorded this before, and a past
    instant would say something did. #684 could use a row's
    created_at because the row was the record; here the record
    is being made now.
    """
    actor = library.user
    recorded_at = timezone.now()
    status = status_days(library)
    session = session_days(library)
    counts = StartRepairCounts(libraries=1)
    stated: dict[uuid.UUID, Evidence] = {}
    left_alone: list[uuid.UUID] = []

    for run in runs_in_scope(library):
        counts = counts + StartRepairCounts(runs_in_scope=1)
        evidence = evidence_for(run, status=status, session=session)
        counts = counts + _witness_counts(run, evidence, status=status, session=session)
        if evidence is None:
            left_alone.append(run.run_id)
            continue
        stated[run.run_id] = evidence
        #: Its own block, as convert_row's is: lock_stream
        #: refuses the head lock outside a transaction, and
        #: inside a caller's it is only a savepoint.
        with transaction.atomic():
            appended = append_one(
                library,
                playthrough_started(
                    run.run_id,
                    when=TemporalValue.from_day(evidence.day),
                    note="",
                ),
                actor=actor,
                idempotency_key=f"{KEY_PREFIX}:{run.run_id}",
                command_input={
                    "fact": "started",
                    #: Stable, and not minted by this pass.
                    "playthrough_id": str(run.run_id),
                    #: Named, so a changed day is loud.
                    "day": evidence.day,
                },
                recorded_at=recorded_at,
                correlation_id=uuid.uuid7(),
                source_metadata={
                    "origin": "backfill",
                    "issue": START_ISSUE,
                    #: The third key tells an inferred day from
                    #: a recorded one, and reconcile() reads it.
                    "source": evidence.source.value,
                },
            )
        if appended:
            counts = counts + StartRepairCounts(events_appended=1)

    return RepairResult(counts=counts, stated=stated, left_alone=tuple(left_alone))


def _witness_counts(
    run: RunInScope,
    evidence: Evidence | None,
    *,
    status: Mapping[uuid.UUID, date],
    session: Mapping[uuid.UUID, date],
) -> StartRepairCounts:
    """Which records this run held, counted."""
    status_day = status.get(run.player_game_id)
    session_day = session.get(run.game_id)
    if status_day is not None and session_day is not None:
        held = StartRepairCounts(both=1, both_agree=int(status_day == session_day))
    elif status_day is not None:
        held = StartRepairCounts(status_only=1)
    elif session_day is not None:
        held = StartRepairCounts(session_only=1)
    else:
        return StartRepairCounts(no_evidence=1)
    won = (
        StartRepairCounts(from_session=1)
        if evidence is not None and evidence.source is StartSource.SESSION
        else StartRepairCounts(from_status=1)
    )
    return held + won


def repaired_run_ids(library: UserLibrary) -> set[uuid.UUID]:
    """Every run whose only act this pass stated.

    #684's reconcile() compares a run stating an act with the
    legacy row it came from. A run repaired here came from no
    row, so it is read as stating none.
    """
    return set(
        LibraryEvent.objects.filter(
            library=library,
            event_type=PLAYTHROUGH_STARTED.event_type,
            source_metadata__origin="backfill",
            source_metadata__issue=START_ISSUE,
        ).values_list("aggregate_id", flat=True)
    )


class StartMismatchCode(StrEnum):
    """Every reason this run refuses to commit."""

    START_DAY_DISAGREEMENT = "start_day_disagreement"
    UNEXPECTED_ACT = "unexpected_act"
    START_MOVED = "start_moved"
    COMPLETION_DRIFT = "completion_drift"
    ACTLESS_DRIFT = "actless_drift"
    COUNT_DRIFT = "count_drift"


class StartSnapshot(NamedTuple):
    """What the library stated before the pass."""

    #: Run id to the day its start states, or None.
    started: Mapping[uuid.UUID, date | None]
    completions: int
    actless: int


def snapshot(library: UserLibrary) -> StartSnapshot:
    """Read the three numbers the gate compares."""
    live = Playthrough.objects.filter(
        library=library,
        kind=PlaythroughKind.ORDINARY,
        removed_at__isnull=True,
    )
    return StartSnapshot(
        started=dict(
            live.filter(start_recorded_at__isnull=False).values_list(
                "pk", "started_lower"
            )
        ),
        completions=live.filter(completion_recorded_at__isnull=False).count(),
        actless=live.filter(
            start_recorded_at__isnull=True,
            completion_recorded_at__isnull=True,
        ).count(),
    )


def gate(
    library: UserLibrary, before: StartSnapshot, result: RepairResult
) -> list[Mismatch]:
    """Every reason this pass must roll back.

    Checks 1, 2, 3, 4 and 6 of the specification. Check 5 is
    the second pass, and check 7 is #684's reconcile and its
    ordering audit; the migration runs all three.
    """
    mismatches: list[Mismatch] = []
    after = snapshot(library)
    days = dict(
        Playthrough.objects.filter(pk__in=result.stated).values_list(
            "pk", "started_lower"
        )
    )
    #: Check 1.
    for run_id, evidence in sorted(
        result.stated.items(), key=lambda pair: str(pair[0])
    ):
        if days.get(run_id) != evidence.day:
            mismatches.append(
                Mismatch(
                    code=StartMismatchCode.START_DAY_DISAGREEMENT,
                    subject=str(run_id),
                    detail=f"the pass states {evidence.day}, "
                    f"the row says {days.get(run_id)}",
                )
            )
    #: Check 2.
    still_empty = set(
        Playthrough.objects.filter(
            pk__in=result.left_alone,
            start_recorded_at__isnull=True,
            completion_recorded_at__isnull=True,
        ).values_list("pk", flat=True)
    )
    for run_id in sorted(result.left_alone, key=str):
        if run_id not in still_empty:
            mismatches.append(
                Mismatch(
                    code=StartMismatchCode.UNEXPECTED_ACT,
                    subject=str(run_id),
                    detail="a run holding no evidence states an act",
                )
            )
    #: Check 3.
    expected = set(before.started) | set(result.stated)
    for run_id in sorted(set(after.started) - expected, key=str):
        mismatches.append(
            Mismatch(
                code=StartMismatchCode.START_MOVED,
                subject=str(run_id),
                detail="a run outside the scope states a start",
            )
        )
    for run_id, day in sorted(before.started.items(), key=lambda pair: str(pair[0])):
        #: Membership, not .get(): a run whose start is gone
        #: and a run whose start states no day both answer
        #: None, and only the first is this code's subject.
        if run_id not in after.started:
            mismatches.append(
                Mismatch(
                    code=StartMismatchCode.START_MOVED,
                    subject=str(run_id),
                    detail=f"a start stated before the pass said {day} "
                    "and now states no act",
                )
            )
        elif after.started[run_id] != day:
            mismatches.append(
                Mismatch(
                    code=StartMismatchCode.START_MOVED,
                    subject=str(run_id),
                    detail=f"a start stated before the pass said {day} "
                    f"and now says {after.started[run_id]}",
                )
            )
    #: Check 4.
    if after.completions != before.completions:
        mismatches.append(
            Mismatch(
                code=StartMismatchCode.COMPLETION_DRIFT,
                subject=str(library.pk),
                detail=f"completions went from {before.completions} "
                f"to {after.completions}",
            )
        )
    #: Check 6.
    if after.actless != before.actless - len(result.stated):
        mismatches.append(
            Mismatch(
                code=StartMismatchCode.ACTLESS_DRIFT,
                subject=str(library.pk),
                detail=f"{before.actless} runs stated no act, {len(result.stated)} "
                f"were repaired, and {after.actless} state none now",
            )
        )
    return mismatches
