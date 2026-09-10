"""A start for the runs #684 left empty. #1038.

#684 states one run per legacy PlayEvent row, and one empty
default for a tracked game holding none. Most tracked games
held none, so most runs state no day at all while a status
change and a session both record when play began. This pass
states that day, and states no completion.
"""

import uuid
from collections.abc import Mapping
from datetime import date
from enum import StrEnum
from typing import NamedTuple

from django.db.models import Min
from django.db.models.functions import TruncDate

from games.events.playthrough import PLAYTHROUGH_CREATED
from games.models import (
    LibraryEvent,
    Playthrough,
    PlaythroughKind,
    Session,
    UserLibrary,
)
from games.preflight.playthrough import candidate_events
from games.reads.playthrough_activity import activity_clock

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
