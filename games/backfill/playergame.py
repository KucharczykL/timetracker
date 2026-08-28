"""Baseline PlayerGame events for the games a library already holds.

Issue #676. The catalog states which games a library has; the event log
states nothing until this runs. Every live game becomes a tracked game,
expressed as events and folded by the PlayerGames projector, because a
projection row is written by its projector and by nothing else.
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, cast

from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from games.events.append import LockedStream, SourceMetadata
from games.events.idempotency import ReplayedAppend, idempotent_append
from games.events.playergame import (
    PLAYERGAME_CREATED,
    PLAYERGAME_MASTERED_CHANGED,
    PLAYERGAME_STATUS_CHANGED,
    StatusValue,
)
from games.events.references import capture_reference
from games.events.vocabulary import NewEvent
from games.models import (
    Game,
    GameStatusChange,
    PlayerGame,
    PlayerGameStatus,
    UserLibrary,
)
from timetracker.temporal import TemporalValue

#: Named in every key and every source_metadata value.
PGAME_ISSUE = 676
KEY_PREFIX = "backfill:676:playergame"

#: One letter of Game.Status.
type LegacyStatus = str  # "f"

#: A recorded payload cannot be upcast, so the letters become words here and
#: never reach an event. SHELVED is absent: no legacy column states it.
LEGACY_STATUS_TO_PLAYER_STATUS: Mapping[LegacyStatus, PlayerGameStatus] = {
    Game.Status.UNPLAYED: PlayerGameStatus.UNPLAYED,
    Game.Status.PLAYED: PlayerGameStatus.PLAYED,
    Game.Status.FINISHED: PlayerGameStatus.COMPLETED,
    Game.Status.RETIRED: PlayerGameStatus.RETIRED,
    Game.Status.ABANDONED: PlayerGameStatus.ABANDONED,
}


class UnmappedLegacyStatus(ValueError):
    """Raised for a legacy letter the map does not know."""


def player_status_for(legacy_status: LegacyStatus) -> PlayerGameStatus:
    """The word a recorded payload carries for one legacy letter."""
    try:
        return LEGACY_STATUS_TO_PLAYER_STATUS[legacy_status]
    except KeyError:
        raise UnmappedLegacyStatus(
            f"{legacy_status!r} is not a legacy status this backfill maps. "
            "Every member of Game.Status names a PlayerGameStatus."
        ) from None


def transition_effective_time(timestamp: datetime | None) -> TemporalValue:
    """When the transition happened, at an honest precision.

    A non-null legacy timestamp is the effective transition time rather than
    a recording time: live signals wrote the moment of the player's action,
    and the original data migration used the earliest Session, the refund or
    drop date, or the PlayEvent completion date. A null one stays unknown, so
    it enters approximate history rather than claiming a day.
    """
    if timestamp is None:
        return TemporalValue.unknown()
    return TemporalValue.from_day(timezone.localtime(timestamp).date())


@dataclass(frozen=True, slots=True)
class BackfillCounts:
    """What one pass did, summable across games and libraries."""

    games: int = 0
    tracked: int = 0
    created_events: int = 0
    status_events: int = 0
    mastered_events: int = 0
    corrective_events: int = 0
    unknown_effective_times: int = 0
    skipped_tombstoned: int = 0

    def __add__(self, other: BackfillCounts) -> BackfillCounts:
        return BackfillCounts(
            games=self.games + other.games,
            tracked=self.tracked + other.tracked,
            created_events=self.created_events + other.created_events,
            status_events=self.status_events + other.status_events,
            mastered_events=self.mastered_events + other.mastered_events,
            corrective_events=self.corrective_events + other.corrective_events,
            unknown_effective_times=(
                self.unknown_effective_times + other.unknown_effective_times
            ),
            skipped_tombstoned=self.skipped_tombstoned + other.skipped_tombstoned,
        )


#: The value an accumulation starts from.
NO_COUNTS = BackfillCounts()


def _append(
    library: UserLibrary,
    event: NewEvent,
    *,
    actor: User,
    idempotency_key: str,
    command_input: dict[str, Any],
    recorded_at: datetime,
    source_metadata: SourceMetadata,
) -> bool:
    """Append one event, or replay its key. True when it appended.

    One append per event, never one append per game: LockedStream.append()
    stamps one recorded_at across every row of a call, and these events carry
    four different dates.

    dispatch() is not used. It needs a Command, and a command validates
    against current state to refuse a duplicate -- SetPlayerGameStatus rejects
    the status a game already has, which is the ordinary case here.
    run_in_transaction is not used either: its retry answers a concurrent
    writer, and a backfill has none.
    """

    def build(stream: LockedStream) -> Sequence[NewEvent]:
        #: The append contract passes it; nothing here consults it.
        del stream
        return [event]

    outcome = idempotent_append(
        library,
        idempotency_key=idempotency_key,
        command_input=command_input,
        build=build,
        actor=actor,
        #: Its own, per event. #685 pairs these with lifecycle facts later, and
        #: adopts these ids rather than mutating an immutable column.
        correlation_id=uuid.uuid7(),
        source_metadata=source_metadata,
        recorded_at=recorded_at,
    )
    return not isinstance(outcome, ReplayedAppend)


def _legacy_changes(game: Game) -> list[GameStatusChange]:
    """One game's status history, oldest first, undated first.

    The order is stated rather than inherited: GameStatusChange.Meta.ordering
    is -timestamp, and a descending fold would end on the oldest fact.
    """
    return list(
        GameStatusChange.objects.filter(game=game).order_by(
            F("timestamp").asc(nulls_first=True), "pk"
        )
    )


def backfill_game(
    game: Game, *, library: UserLibrary, actor: User, run_time: datetime
) -> BackfillCounts:
    """Record the baseline facts for one game this library holds.

    The atomic block is this function's own: lock_stream refuses to take the
    head lock outside a transaction, and one game's facts are recorded whole
    or not at all. Inside a caller's transaction it is a savepoint, so a
    migration still rolls the whole run back.
    """
    metadata: SourceMetadata = {"origin": "backfill", "issue": PGAME_ISSUE}
    counts = BackfillCounts(games=1, tracked=1)

    with transaction.atomic():
        #: Always first. amend() raises ProjectionRowMissing against a row no
        #: creation event made, so every later fact depends on this one.
        if _append(
            library,
            PLAYERGAME_CREATED.new(
                aggregate_id=uuid.uuid7(),
                payload={"game": capture_reference(game)},
            ),
            actor=actor,
            idempotency_key=f"{KEY_PREFIX}:created:{game.pk}",
            command_input={"fact": "created", "game_id": str(game.pk)},
            #: A real recording time: the row was written then, and the
            #: projector takes tracked_at from it.
            recorded_at=game.created_at,
            source_metadata=metadata,
        ):
            counts = replace(counts, created_events=1)

        #: The projector wrote the row synchronously, inside this transaction.
        tracked_id: uuid.UUID = PlayerGame.objects.values_list("pk", flat=True).get(
            library=library, game=game
        )

        if game.mastered and _append(
            library,
            PLAYERGAME_MASTERED_CHANGED.new(
                aggregate_id=tracked_id,
                payload={"mastered": True},
            ),
            actor=actor,
            idempotency_key=f"{KEY_PREFIX}:mastered:{game.pk}",
            command_input={"fact": "mastered", "game_id": str(game.pk)},
            recorded_at=game.created_at,
            source_metadata=metadata,
        ):
            counts = replace(counts, mastered_events=1)

        folded = PlayerGameStatus.UNPLAYED
        for change in _legacy_changes(game):
            status = player_status_for(change.new_status)
            effective_time = transition_effective_time(change.timestamp)
            if _append(
                library,
                PLAYERGAME_STATUS_CHANGED.new(
                    aggregate_id=tracked_id,
                    #: A test pins Literal and choices equal.
                    payload={"status": cast("StatusValue", status.value)},
                    effective_time=effective_time,
                ),
                actor=actor,
                idempotency_key=f"{KEY_PREFIX}:status:{change.pk}",
                command_input={"fact": "status", "status_change_id": str(change.pk)},
                recorded_at=change.timestamp or game.created_at,
                source_metadata={**metadata, "status_change_id": str(change.pk)},
            ):
                counts = replace(counts, status_events=counts.status_events + 1)
                if effective_time.is_unknown:
                    counts = replace(
                        counts,
                        unknown_effective_times=counts.unknown_effective_times + 1,
                    )
            #: old_status is ignored: the fold sets a value rather than
            #: applying a delta, so a broken chain cannot change the result.
            folded = status

        current = player_status_for(game.status)
        if folded != current and _append(
            library,
            PLAYERGAME_STATUS_CHANGED.new(
                aggregate_id=tracked_id,
                payload={"status": cast("StatusValue", current.value)},
                #: Game.updated_at is auto_now -- the last time any field moved
                #: -- so dating this with it would fabricate precision the
                #: charter forbids. The status is known; when it changed is not.
                effective_time=TemporalValue.unknown(),
            ),
            actor=actor,
            idempotency_key=f"{KEY_PREFIX}:status:current:{game.pk}",
            command_input={
                "fact": "status_current",
                "game_id": str(game.pk),
                #: Named, so a changed current status is a loud mismatch.
                "status": current.value,
            },
            recorded_at=run_time,
            source_metadata=metadata,
        ):
            counts = replace(
                counts,
                corrective_events=1,
                unknown_effective_times=counts.unknown_effective_times + 1,
            )

    return counts


def backfill_library(
    library: UserLibrary, *, run_time: datetime | None = None
) -> BackfillCounts:
    """Record baseline facts for every live game this library holds.

    A shared game -- library is null -- is never reached: the query scopes to
    the library, and #677 gives a player the way to track one. A tombstoned
    game is skipped and counted: retention emptied the row and kept it only for
    the events that name it, so there is nothing left to track.
    """
    resolved_run_time = run_time or timezone.now()
    actor = library.user
    counts = NO_COUNTS
    #: Deterministic, so two runs order the stream identically.
    games = Game.objects.filter(library=library).order_by("created_at", "pk")
    for game in games.iterator(chunk_size=200):
        if game.tombstoned_at is not None:
            counts = counts + BackfillCounts(games=1, skipped_tombstoned=1)
            continue
        counts = counts + backfill_game(
            game,
            library=library,
            actor=actor,
            run_time=resolved_run_time,
        )
    return counts


@dataclass(frozen=True, slots=True)
class Mismatch:
    """One reason the backfill must not commit."""

    code: str
    game_id: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "detail": self.detail, "game_id": self.game_id}


def unmapped_statuses(library: UserLibrary) -> list[Mismatch]:
    """Every legacy letter the map does not know, found before any append.

    A pre-flight rather than a KeyError mid-run: an unmapped letter is a
    reconciliation mismatch, reported with its neighbours and rolled back.
    """
    known = set(LEGACY_STATUS_TO_PLAYER_STATUS)
    mismatches = [
        Mismatch(
            code="unmapped_legacy_status",
            game_id=str(game_id),
            detail=f"catalog status {status!r}",
        )
        for game_id, status in Game.objects.filter(library=library)
        .exclude(status__in=known)
        .order_by("pk")
        .values_list("pk", "status")
    ]
    mismatches.extend(
        Mismatch(
            code="unmapped_legacy_status",
            game_id=str(game_id),
            detail=f"status change {change_id} records {status!r}",
        )
        for change_id, game_id, status in GameStatusChange.objects.filter(
            game__library=library
        )
        .exclude(new_status__in=known)
        .order_by("pk")
        .values_list("pk", "game_id", "new_status")
    )
    return mismatches


def reconcile(library: UserLibrary) -> list[Mismatch]:
    """Compare every live game against the row its events folded to."""
    rows = {
        row.game_id: row
        for row in PlayerGame.objects.filter(library=library).only(
            "game_id", "status", "mastered"
        )
    }
    mismatches: list[Mismatch] = []
    live = Game.objects.filter(library=library, tombstoned_at__isnull=True).order_by(
        "pk"
    )
    for game in live.iterator(chunk_size=200):
        row = rows.get(game.pk)
        if row is None:
            mismatches.append(
                Mismatch(
                    code="missing_projection_row",
                    game_id=str(game.pk),
                    detail="the backfill covered this game and no row folded",
                )
            )
            continue
        expected_status = player_status_for(game.status)
        if row.status != expected_status:
            mismatches.append(
                Mismatch(
                    code="status_disagreement",
                    game_id=str(game.pk),
                    detail=f"catalog says {expected_status.value!r}, "
                    f"the fold says {row.status!r}",
                )
            )
        if row.mastered != game.mastered:
            mismatches.append(
                Mismatch(
                    code="mastered_disagreement",
                    game_id=str(game.pk),
                    detail=f"catalog says {game.mastered}, "
                    f"the fold says {row.mastered}",
                )
            )
    return mismatches
