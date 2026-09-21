"""Rows taken out of the lists, in bulk.

Three acts, one for each row a selectable table holds. Each states the
list's own read as its base, and refuses nothing of its own: every rule
is the command's, so one row's refusal is a sentence and the batch goes
on.
"""

import uuid
from collections.abc import Sequence

from django.contrib.auth.models import User
from django.db.models import Model, QuerySet

from common.components.primitives import Cell
from common.temporal_presentation import TemporalText
from games.bulk_actions import (
    BulkAction,
    Cardinality,
    ChoiceValue,
    FilterJson,
    Presentations,
    PreviewColumn,
    Refused,
    Resolution,
    RowOutcome,
)
from games.bulk_narrowing import narrowed
from games.events.dispatch import RowNotHeld
from games.events.idempotency import IdempotencyKey
from games.filters import (
    parse_historical_playtime_filter,
    parse_playthrough_filter,
    parse_session_filter,
)
from games.models import (
    HistoricalPlaytime,
    PlayerSession,
    Playthrough,
    UserLibrary,
)
from games.reads.historical_playtime_records import library_records
from games.reads.player_sessions import library_sessions
from games.reads.playthrough_endpoints import (
    StatedEndpoint,
    stated_completion,
    stated_start,
)
from games.reads.playthrough_numbering import display_name, numbered_for
from games.reads.playthrough_runs import library_runs, runs_with_condition
from games.writes.answers import SubjectNoun, answered
from games.writes.historical_playtime import (
    remove_historical_playtime,
    restore_historical_playtime,
)
from games.writes.playersession import remove_session, restore_session
from games.writes.playthrough import remove_run, restore_run

#: What `answered` calls a record; the confirmation says "record".
RECORD_SUBJECT: SubjectNoun = "historical playtime"

SESSION_GONE = "One of the sessions is no longer available, so it was left as it is."
RUN_GONE = "One of the playthroughs is no longer available, so it was left as it is."
RECORD_GONE = "One of the records is no longer available, so it was left as it is."


def _lost(
    keys: Sequence[uuid.UUID], found: set[uuid.UUID], sentence: str
) -> list[Refused]:
    """Gone since the confirmation, or never this library's."""
    return [Refused(str(key), sentence, lost=True) for key in keys if key not in found]


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


def session_scope(
    library: UserLibrary, filter_json: FilterJson
) -> QuerySet[PlayerSession]:
    return narrowed(
        library_sessions(library), library, filter_json, parse_session_filter
    )


def session_resolution(
    library: UserLibrary, keys: Sequence[uuid.UUID]
) -> Resolution[PlayerSession]:
    wanted = list(dict.fromkeys(keys))
    rows = tuple(
        library_sessions(library)
        .filter(pk__in=wanted)
        .select_related("playthrough__player_game__game", "device")
        .order_by("-sort_instant", "id")
    )
    return Resolution(
        rows, tuple(_lost(wanted, {row.pk for row in rows}, SESSION_GONE))
    )


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
    choice: ChoiceValue | None,
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


def run_scope(library: UserLibrary, filter_json: FilterJson) -> QuerySet[Playthrough]:
    """The list's own read, which carries the condition aliases.

    `runs_with_condition`, not `library_runs`: `activity` is a quick
    facet of this mode, and a statement carrying it would not compile
    over a queryset no clock reached.
    """
    return narrowed(
        runs_with_condition(library), library, filter_json, parse_playthrough_filter
    )


def run_resolution(
    library: UserLibrary, keys: Sequence[uuid.UUID]
) -> Resolution[Playthrough]:
    """Keys to rows, each carrying the number a screen calls it.

    The number is counted across every live ordinary run of the games
    the keys name, never across the selection: a partition narrowed to
    what a person ticked would call each of them the first. So the
    rows the act offers are read off the numbered queryset, and the
    list's own scope says which of them are offered.
    """
    wanted = list(dict.fromkeys(keys))
    offered = library_runs(library).filter(pk__in=wanted)
    live = set(offered.values_list("pk", flat=True))
    games = set(offered.values_list("player_game_id", flat=True))
    rows = tuple(
        sorted(
            (
                run
                for run in numbered_for(library, games).select_related(
                    "player_game__game"
                )
                if run.pk in live
            ),
            #: A stable sort keeps the numbering order inside a game.
            key=lambda run: run.player_game.game.name,
        )
    )
    return Resolution(rows, tuple(_lost(wanted, live, RUN_GONE)))


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
    choice: ChoiceValue | None,
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


def _start_cell(row: Playthrough, presentations: Presentations) -> Cell:
    return _endpoint_cell(stated_start(row), presentations)


def _completion_cell(row: Playthrough, presentations: Presentations) -> Cell:
    return _endpoint_cell(stated_completion(row), presentations)


def _endpoint_cell(stated: StatedEndpoint | None, presentations: Presentations) -> Cell:
    """No act reads a dash, as the list writes it."""
    if stated is None:
        return "-"
    return TemporalText(stated.when, presentations.dates)


RUN_PREVIEW: tuple[PreviewColumn[Playthrough], ...] = (
    PreviewColumn("Playthrough", lambda row, _: display_name(row)),
    PreviewColumn("Game", lambda row, _: row.player_game.game.name),
    PreviewColumn("Started", _start_cell),
    PreviewColumn("Completed", _completion_cell),
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
    return Resolution(rows, tuple(_lost(wanted, {row.pk for row in rows}, RECORD_GONE)))


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
    choice: ChoiceValue | None,
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


def _source(name: str) -> dict[str, object]:
    return {"bulk": {"action": name}}


REMOVE_SESSION = BulkAction(
    name="session.remove",
    label="Remove",
    title="Remove these sessions",
    confirm_label="Remove",
    subject="session",
    cardinality=Cardinality.MANY,
    color="red",
    inverse_aggregate="playersession",
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
    title="Remove these playthroughs",
    confirm_label="Remove",
    subject="playthrough",
    cardinality=Cardinality.MANY,
    color="red",
    inverse_aggregate="playthrough",
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
    title="Remove these records",
    confirm_label="Remove",
    #: The word the lists use, and the one that counts: three
    #: "historical playtimes" is nobody's sentence.
    subject="record",
    cardinality=Cardinality.MANY,
    color="red",
    inverse_aggregate="historicalplaytime",
    fallback="games:list_historical_playtime",
    scope=record_scope,
    resolve=record_resolution,
    run=remove_one_record,
    inverse=restore_one_record,
    preview=RECORD_PREVIEW,
)
