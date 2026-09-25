"""Rows taken out of the lists, in bulk.

Five acts, one for each row a selectable table holds. Each states the
list's own read as its base, and refuses nothing of its own: every rule
is the command's, so one row's refusal is a sentence and the batch goes
on.
"""

import uuid
from collections.abc import Sequence

from django.contrib.auth.models import User
from django.db.models import Exists, Model, OuterRef, QuerySet

from common.temporal_presentation import TemporalText
from games.bulk_actions import (
    ActTitle,
    BulkAction,
    ChoiceValue,
    FilterJson,
    PreviewColumn,
    Refused,
    Resolution,
    RowOutcome,
)
from games.bulk_narrowing import narrowed
from games.bulk_runs import RUN_PREVIEW, run_resolution, run_scope
from games.bulk_sessions import lost, session_resolution, session_scope
from games.events.dispatch import RowNotHeld
from games.events.idempotency import IdempotencyKey
from games.filters import (
    parse_device_filter,
    parse_game_filter,
    parse_historical_playtime_filter,
)
from games.models import (
    Device,
    Game,
    HistoricalPlaytime,
    PlayerGame,
    PlayerSession,
    Playthrough,
    UserLibrary,
)
from games.reads.device_departures import naming_sessions_of, with_naming_sessions
from games.reads.game_departures import departures_of, with_departures
from games.reads.historical_playtime_records import library_records
from games.writes.answers import SubjectNoun, answered
from games.writes.device import remove_device, restore_device
from games.writes.historical_playtime import (
    remove_historical_playtime,
    restore_historical_playtime,
)
from games.writes.playergame import remove_from_library, restore_to_library
from games.writes.playersession import remove_session, restore_session
from games.writes.playthrough import remove_run, restore_run

#: What `answered` calls a record; the confirmation says "record".
RECORD_SUBJECT: SubjectNoun = "historical playtime"

RECORD_GONE = "One of the records is no longer available, so it was left as it is."
GAME_GONE = "One of the games is no longer available, so it was left as it is."
DEVICE_GONE = "One of the devices is no longer available, so it was left as it is."


def _removed_row[RowT: Model](
    rows: QuerySet[RowT], actor: User, key: uuid.UUID, subject: SubjectNoun
) -> RowT:
    """The row an inverse puts back, by key.

    A plain manager, because the row is removed by now and every scoped
    read reads that mark. The library is still stated.

    Under `answered`, and raising its own absence: the manager's
    `DoesNotExist` is neither of the two the runner catches, so it
    would leave the batch through the view, and every row the batch
    never reached would go unnamed in the log.
    """
    with answered(subject):
        row = rows.filter(library=actor.library, pk=key).first()
        if row is None:
            raise RowNotHeld(
                f"{rows.model.__name__} {key} is not library "
                f"{actor.library.pk}'s, so the batch's inverse has no row to "
                "state a fact about."
            )
    return row


# ── Sessions ─────────────────────────────────────────────────────────────────


def remove_one_session(
    actor: User,
    session: PlayerSession,
    *,
    choice: ChoiceValue | None,
    idempotency_key: IdempotencyKey,
    correlation_id: uuid.UUID,
) -> RowOutcome:
    return RowOutcome.of(
        remove_session(
            actor,
            session,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            source_metadata=_source(REMOVE_SESSION.name),
        )
    )


def restore_one_session(
    actor: User,
    session_id: uuid.UUID,
    *,
    undoes: uuid.UUID,
    idempotency_key: IdempotencyKey,
    correlation_id: uuid.UUID,
) -> RowOutcome:
    return RowOutcome.of(
        restore_session(
            actor,
            _removed_row(PlayerSession.objects.all(), actor, session_id, "session"),
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            source_metadata=_source(REMOVE_SESSION.name),
        )
    )


SESSION_PREVIEW: tuple[PreviewColumn[PlayerSession], ...] = (
    PreviewColumn("Game", lambda row, _: row.playthrough.player_game.game.name),
    PreviewColumn("Day", lambda row, _: str(row.effective_day)),
    PreviewColumn(
        "Duration",
        lambda row, presentations: presentations.durations.format(
            row.effective_duration
        ),
        align="right",
    ),
)


# ── Runs ─────────────────────────────────────────────────────────────────────


def remove_one_run(
    actor: User,
    run: Playthrough,
    *,
    choice: ChoiceValue | None,
    idempotency_key: IdempotencyKey,
    correlation_id: uuid.UUID,
) -> RowOutcome:
    return RowOutcome.of(
        remove_run(
            actor,
            run,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            source_metadata=_source(REMOVE_RUN.name),
        )
    )


def restore_one_run(
    actor: User,
    run_id: uuid.UUID,
    *,
    undoes: uuid.UUID,
    idempotency_key: IdempotencyKey,
    correlation_id: uuid.UUID,
) -> RowOutcome:
    return RowOutcome.of(
        restore_run(
            actor,
            _removed_row(Playthrough.objects.all(), actor, run_id, "playthrough"),
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            source_metadata=_source(REMOVE_RUN.name),
        )
    )


# ── Records ──────────────────────────────────────────────────────────────────


def record_scope(
    library: UserLibrary, filter_json: FilterJson
) -> QuerySet[HistoricalPlaytime]:
    return narrowed(
        library_records(library),
        library,
        filter_json,
        parse_historical_playtime_filter,
    )


def record_resolution(
    library: UserLibrary, keys: Sequence[uuid.UUID]
) -> Resolution[HistoricalPlaytime]:
    wanted = list(dict.fromkeys(keys))
    rows = tuple(
        library_records(library)
        .filter(pk__in=wanted)
        .select_related("player_game__game")
        .order_by("-when_lower", "id")
    )
    return Resolution(rows, tuple(lost(wanted, {row.pk for row in rows}, RECORD_GONE)))


def remove_one_record(
    actor: User,
    record: HistoricalPlaytime,
    *,
    choice: ChoiceValue | None,
    idempotency_key: IdempotencyKey,
    correlation_id: uuid.UUID,
) -> RowOutcome:
    return RowOutcome.of(
        remove_historical_playtime(
            actor,
            record,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            source_metadata=_source(REMOVE_RECORD.name),
        )
    )


def restore_one_record(
    actor: User,
    record_id: uuid.UUID,
    *,
    undoes: uuid.UUID,
    idempotency_key: IdempotencyKey,
    correlation_id: uuid.UUID,
) -> RowOutcome:
    return RowOutcome.of(
        restore_historical_playtime(
            actor,
            _removed_row(
                HistoricalPlaytime.objects.all(),
                actor,
                record_id,
                RECORD_SUBJECT,
            ),
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            source_metadata=_source(REMOVE_RECORD.name),
        )
    )


RECORD_PREVIEW: tuple[PreviewColumn[HistoricalPlaytime], ...] = (
    PreviewColumn("Game", lambda row, _: row.player_game.game.name),
    PreviewColumn(
        "When", lambda row, presentations: TemporalText(row.when, presentations.dates)
    ),
    PreviewColumn(
        "Duration",
        lambda row, presentations: presentations.durations.format(row.duration),
        align="right",
    ),
)


# ── Games ────────────────────────────────────────────────────────────────────


def game_scope(library: UserLibrary, filter_json: FilterJson) -> QuerySet[Game]:
    """The list's own read: shared catalog games it tracks included."""
    return narrowed(
        Game.objects.tracked_by(library), library, filter_json, parse_game_filter
    )


def _partly_removed(
    library: UserLibrary, keys: Sequence[uuid.UUID]
) -> dict[uuid.UUID, str]:
    """The keys of games a removal stopped between its two writes.

    Such a game is untracked and unstamped: off `tracked_by`, so the
    act cannot reach it, and off the list, so nobody can select it
    again. It is not gone, and saying it is would send whoever reads
    the tally looking for a row that is sitting there.

    The act still cannot finish it. A stamp with no event of its own
    is a row this batch's Undo cannot see, which is the whole reason
    the helper refuses an untracked game. So the tally names the
    remedy that does work, the per-row Remove.
    """
    if not keys:
        return {}
    stranded = (
        Game.objects.alive()
        .filter(
            Exists(
                PlayerGame.objects.filter(
                    game=OuterRef("pk"),
                    library=library,
                    removed_at__isnull=False,
                )
            ),
            library=library,
            pk__in=keys,
        )
        .values_list("pk", "name")
    )
    return {
        key: (
            f"{name} was only partly removed by an earlier act. Open it and "
            "remove it again to finish."
        )
        for key, name in stranded
    }


def game_resolution(
    library: UserLibrary, keys: Sequence[uuid.UUID]
) -> Resolution[Game]:
    """Keys to games, each carrying what leaves beside it.

    Refuses no key it finds: every rule is the helper's and the
    command's. A key it does not find is lost, under the sentence
    that names which of the two states it is in.
    """
    wanted = list(dict.fromkeys(keys))
    rows = tuple(
        with_departures(Game.objects.tracked_by(library).filter(pk__in=wanted), library)
        .select_related("platform")
        .order_by("sort_name", "id")
    )
    found = {row.pk for row in rows}
    missing = [key for key in wanted if key not in found]
    stranded = _partly_removed(library, missing)
    refused = tuple(
        Refused(str(key), stranded.get(key, GAME_GONE), lost=True) for key in missing
    )
    return Resolution(rows, refused)


def remove_one_game(
    actor: User,
    game: Game,
    *,
    choice: ChoiceValue | None,
    idempotency_key: IdempotencyKey,
    correlation_id: uuid.UUID,
) -> RowOutcome:
    return RowOutcome.of(
        remove_from_library(
            actor,
            game,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            source_metadata=_source(REMOVE_GAME.name),
        )
    )


def restore_one_game(
    actor: User,
    player_game_id: uuid.UUID,
    *,
    undoes: uuid.UUID,
    idempotency_key: IdempotencyKey,
    correlation_id: uuid.UUID,
) -> RowOutcome:
    """The batch names PlayerGames; the helper takes their Game.

    A PlayerGame key is not a Game key, so the removed row is read
    first, and its game through it.
    """
    tracked = _removed_row(
        PlayerGame.objects.select_related("game"), actor, player_game_id, "game"
    )
    return RowOutcome.of(
        restore_to_library(
            actor,
            tracked.game,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            source_metadata=_source(REMOVE_GAME.name),
        )
    )


GAME_PREVIEW: tuple[PreviewColumn[Game], ...] = (
    PreviewColumn("Game", lambda row, _: row.name),
    PreviewColumn(
        "Sessions", lambda row, _: str(departures_of(row).sessions), align="right"
    ),
    PreviewColumn(
        "Purchases", lambda row, _: str(departures_of(row).purchases), align="right"
    ),
    PreviewColumn(
        "Playthroughs", lambda row, _: str(departures_of(row).runs), align="right"
    ),
)


# ── Devices ──────────────────────────────────────────────────────────────────


def device_scope(library: UserLibrary, filter_json: FilterJson) -> QuerySet[Device]:
    """The list's own read."""
    return narrowed(
        Device.objects.for_library(library), library, filter_json, parse_device_filter
    )


def device_resolution(
    library: UserLibrary, keys: Sequence[uuid.UUID]
) -> Resolution[Device]:
    """Keys to devices, with naming sessions."""
    wanted = list(dict.fromkeys(keys))
    rows = tuple(
        with_naming_sessions(
            Device.objects.for_library(library).filter(pk__in=wanted), library
        ).order_by("name", "id")
    )
    return Resolution(rows, tuple(lost(wanted, {row.pk for row in rows}, DEVICE_GONE)))


def remove_one_device(
    actor: User,
    device: Device,
    *,
    choice: ChoiceValue | None,
    idempotency_key: IdempotencyKey,
    correlation_id: uuid.UUID,
) -> RowOutcome:
    return RowOutcome.of(
        remove_device(
            actor,
            device,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            source_metadata=_source(REMOVE_DEVICE.name),
        )
    )


def restore_one_device(
    actor: User,
    device_id: uuid.UUID,
    *,
    undoes: uuid.UUID,
    idempotency_key: IdempotencyKey,
    correlation_id: uuid.UUID,
) -> RowOutcome:
    return RowOutcome.of(
        restore_device(
            actor,
            _removed_row(Device.objects.all(), actor, device_id, "device"),
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            source_metadata=_source(REMOVE_DEVICE.name),
        )
    )


DEVICE_PREVIEW: tuple[PreviewColumn[Device], ...] = (
    PreviewColumn("Device", lambda row, _: row.name),
    PreviewColumn("Type", lambda row, _: row.get_type_display()),
    PreviewColumn(
        "Sessions", lambda row, _: str(naming_sessions_of(row)), align="right"
    ),
)


def _source(name: str) -> dict[str, object]:
    return {"bulk": {"action": name}}


REMOVE_SESSION = BulkAction(
    name="session.remove",
    label="Remove",
    title=ActTitle(one="Remove this session", many="Remove these sessions"),
    confirm_label="Remove",
    subject="session",
    color="red",
    inverse_aggregate="playersession",
    inverse_model=PlayerSession,
    fallback="games:list_sessions",
    scope=session_scope,
    resolve=session_resolution,
    run=remove_one_session,
    inverse=restore_one_session,
    preview=SESSION_PREVIEW,
)

REMOVE_RUN = BulkAction(
    name="playthrough.remove",
    label="Remove",
    title=ActTitle(one="Remove this playthrough", many="Remove these playthroughs"),
    confirm_label="Remove",
    subject="playthrough",
    color="red",
    inverse_aggregate="playthrough",
    inverse_model=Playthrough,
    fallback="games:list_playthroughs",
    scope=run_scope,
    resolve=run_resolution,
    run=remove_one_run,
    inverse=restore_one_run,
    preview=RUN_PREVIEW,
)

REMOVE_RECORD = BulkAction(
    name="historicalplaytime.remove",
    label="Remove",
    title=ActTitle(one="Remove this record", many="Remove these records"),
    confirm_label="Remove",
    #: The word the lists use, and the one that counts: three
    #: "historical playtimes" is nobody's sentence.
    subject="record",
    color="red",
    inverse_aggregate="historicalplaytime",
    inverse_model=HistoricalPlaytime,
    fallback="games:list_historical_playtime",
    scope=record_scope,
    resolve=record_resolution,
    run=remove_one_record,
    inverse=restore_one_record,
    preview=RECORD_PREVIEW,
)

REMOVE_GAME = BulkAction(
    name="playergame.remove",
    label="Remove",
    title=ActTitle(one="Remove this game", many="Remove these games"),
    confirm_label="Remove",
    subject="game",
    color="red",
    inverse_aggregate="playergame",
    inverse_model=PlayerGame,
    fallback="games:list_games",
    scope=game_scope,
    resolve=game_resolution,
    run=remove_one_game,
    inverse=restore_one_game,
    preview=GAME_PREVIEW,
)

REMOVE_DEVICE = BulkAction(
    name="device.remove",
    label="Remove",
    title=ActTitle(one="Remove this device", many="Remove these devices"),
    confirm_label="Remove",
    subject="device",
    color="red",
    inverse_aggregate="device",
    inverse_model=Device,
    fallback="games:list_devices",
    scope=device_scope,
    resolve=device_resolution,
    run=remove_one_device,
    inverse=restore_one_device,
    preview=DEVICE_PREVIEW,
)
