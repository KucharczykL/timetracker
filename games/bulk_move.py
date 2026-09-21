"""Many sessions moved to one playthrough."""

import logging
import uuid
from collections.abc import Sequence

from django.contrib.auth.models import User
from django.db.models import QuerySet
from django.http import Http404, QueryDict

from common.components.core import Fragment
from common.components.primitives import Cell, Div, Label
from common.components.search_select import DEFAULT_PREFETCH, SearchSelect
from games.bulk_actions import (
    BulkAction,
    BulkChoice,
    Cardinality,
    ChoiceValue,
    Control,
    FieldName,
    FilterJson,
    Offered,
    Presentations,
    PreviewColumn,
    Refused,
    RefusedAct,
    Resolution,
    RowOutcome,
)
from games.bulk_narrowing import narrowed
from games.events.dispatch import CommandRejected, RowNotHeld, RowUnreadable
from games.events.idempotency import IdempotencyKey
from games.events.playersession import PLAYERSESSION_CREATED, PLAYERSESSION_MOVED
from games.events.playthrough import PLAYTHROUGH_REMOVED
from games.filters import parse_session_filter
from games.forms import PLAYTHROUGH_CREATE_URL, PLAYTHROUGH_SEARCH_URL
from games.models import (
    PlayerSession,
    Playthrough,
    PlaythroughKind,
    UserLibrary,
)
from games.reads.events import aggregate_events, batch_events
from games.reads.player_sessions import library_sessions
from games.reads.playthrough_referrers import BLOCKING_REFERRERS, rows_naming
from games.reads.playthrough_runs import library_runs
from games.reads.session_run_labels import every_run_label
from games.writes.answers import CONFLICT_STATUS, CommandFailed, answered
from games.writes.playersession import move_session
from games.writes.playthrough import remove_run, restore_run

logger = logging.getLogger("games")

SESSION_GONE = "One of the sessions is no longer available, so it was left as it is."

#: The act asks about one game.
TWO_GAMES = (
    "Those sessions are at {count} different games, and a playthrough "
    "belongs to one. Narrow the list by game and try again."
)

#: What a missing target refuses.
NO_TARGET = "Choose the playthrough to move them to."
TARGET_UNREADABLE = "That playthrough could not be read. Choose one again."
TARGET_GONE = (
    "That playthrough is no longer available. Choose another one, or reload "
    "the list and start again."
)

#: What one row refuses.
ANOTHER_GAME = (
    "That session is at another game, so it cannot go to this playthrough. "
    "It was left as it is."
)

#: What the confirmation asks.
TARGET_LABEL = "Playthrough"

#: The attribute the resolve stamps.
RUN_LABEL_ATTRIBUTE = "run_label"

#: The events that state a session's run.
RUN_STATED = (PLAYERSESSION_CREATED.event_type, PLAYERSESSION_MOVED.event_type)

#: What an Undo refuses.
NOT_MOVED_BY_THIS_BATCH = (
    "That session was not moved by this batch, so it was left as it is."
)
NO_EARLIER_RUN = (
    "Where that session was before cannot be read, so it was left as it is."
)
SOURCE_TAKEN_AWAY = (
    "The playthrough that session came from was removed after this batch, so "
    "it was left as it is. Put that playthrough back first."
)


def _source() -> dict[str, object]:
    return {"bulk": {"action": MOVE.name}}


def move_scope(
    library: UserLibrary, filter_json: FilterJson
) -> QuerySet[PlayerSession]:
    return narrowed(
        library_sessions(library), library, filter_json, parse_session_filter
    )


def move_resolution(
    library: UserLibrary, keys: Sequence[uuid.UUID]
) -> Resolution[PlayerSession]:
    """Keys to rows, each naming its run.

    `display_name` raises for a blank-named run with no
    display number, and a session's own run never has one:
    the number is counted across a game's live ordinary runs.
    A cell that called it would answer a 500 instead.
    """
    wanted = list(dict.fromkeys(keys))
    rows = tuple(
        library_sessions(library)
        .filter(pk__in=wanted)
        .select_related("playthrough__player_game__game", "device")
        .order_by("-sort_instant", "id")
    )
    labels = every_run_label(library, rows)
    for row in rows:
        setattr(row, RUN_LABEL_ATTRIBUTE, labels.get(row.playthrough_id))
    found = {row.pk for row in rows}
    return Resolution(
        rows,
        tuple(
            Refused(str(key), SESSION_GONE, lost=True)
            for key in wanted
            if key not in found
        ),
    )


def _run_label(row: PlayerSession, _presentations: Presentations) -> Cell:
    """What the row's run is called."""
    label = getattr(row, RUN_LABEL_ATTRIBUTE, None)
    if label is None:
        raise RowUnreadable(
            f"PlayerSession {row.pk} of library {row.library_id} reached the "
            "preview with no run label. The label comes from every_run_label, "
            "which names a game's live ordinary runs and its buckets in one "
            "read for the whole set; a row that arrives without one came from "
            "another resolve."
        )
    return label


def _device(row: PlayerSession, _presentations: Presentations) -> Cell:
    return row.device.name if row.device is not None else "No device"


MOVE_PREVIEW: tuple[PreviewColumn[PlayerSession], ...] = (
    PreviewColumn(TARGET_LABEL, _run_label),
    PreviewColumn("Day", lambda row, _: str(row.effective_day)),
    PreviewColumn(
        "Duration",
        lambda row, presentations: presentations.durations.format(
            row.effective_duration
        ),
        align="right",
    ),
    PreviewColumn("Device", _device),
    PreviewColumn("Note", lambda row, _: row.note),
)


def offer_target(
    library: UserLibrary, rows: Sequence[PlayerSession], field_name: FieldName
) -> Offered:
    """The picker, over the one game.

    Every resolved row is read, never the printed sample.
    A count taken from the sample would pass a selection
    spanning two games, and move the unprinted rest to a
    run at another game.
    """
    if not rows:
        #: The confirmation says so itself.
        return Control(Fragment())
    games = {row.playthrough.player_game_id for row in rows}
    if len(games) > 1:
        return RefusedAct(TWO_GAMES.format(count=len(games)))
    game_id = rows[0].playthrough.player_game.game_id
    return Control(
        Div(class_="flex flex-col gap-2")[
            Label(for_=field_name)[TARGET_LABEL],
            SearchSelect(
                name=field_name,
                search_url=PLAYTHROUGH_SEARCH_URL,
                create_url=PLAYTHROUGH_CREATE_URL,
                #: One mapping feeds search and create.
                params={"game_id": {"value": str(game_id)}},
                prefetch=DEFAULT_PREFETCH,
                id=field_name,
            ),
        ]
    )


def settle_target(library: UserLibrary, post: QueryDict) -> ChoiceValue:
    """The posted key the library holds.

    Says nothing about the game. The rows of a continuation
    can span two games, and there is then no one game to
    narrow to. The game is the row's own rule, below.
    """
    #: Local: the view imports this module.
    from games.views.bulk import CHOICE_FIELD

    stated = post.get(CHOICE_FIELD, "")
    if not stated:
        raise CommandRejected("no target was posted", sentence=NO_TARGET)
    try:
        key = uuid.UUID(stated)
    except ValueError as unreadable:
        raise CommandRejected(
            f"{stated!r} is no uuid: {unreadable}", sentence=TARGET_UNREADABLE
        ) from unreadable
    if not library_runs(library).filter(pk=key).exists():
        raise CommandRejected(
            f"playthrough {key} is no live ordinary run of library {library.pk}",
            sentence=TARGET_GONE,
        )
    return stated


def _target(library: UserLibrary, choice: ChoiceValue) -> Playthrough:
    """The run this batch moves rows to."""
    run = library_runs(library).filter(pk=choice).first()
    if run is None:
        raise CommandRejected(
            f"playthrough {choice} left library {library.pk} mid-batch",
            sentence=TARGET_GONE,
        )
    return run


def move_one(
    actor: User,
    session: PlayerSession,
    *,
    choice: ChoiceValue | None,
    idempotency_key: IdempotencyKey,
    correlation_id: uuid.UUID,
) -> RowOutcome:
    """One session moved, and its bucket."""
    with answered("session"):
        if choice is None:
            raise RowUnreadable(
                f"{MOVE.name} ran with no target. The act declares a choice, "
                "so the runner settles one before it reaches a row."
            )
        target = _target(actor.library, choice)
        if session.playthrough.player_game_id != target.player_game_id:
            raise CommandRejected(
                f"session {session.pk} is at game "
                f"{session.playthrough.player_game_id} and playthrough "
                f"{target.pk} at {target.player_game_id}",
                sentence=ANOTHER_GAME,
            )
    outcome = RowOutcome.of(
        move_session(
            actor,
            session,
            target.pk,
            idempotency_key=f"{idempotency_key}-move",
            correlation_id=correlation_id,
            source_metadata=_source(),
        )
    )
    if outcome is RowOutcome.MOVED:
        _remove_the_emptied_bucket(actor, session.pk, idempotency_key, correlation_id)
    return outcome


def _remove_the_emptied_bucket(
    actor: User,
    session_id: uuid.UUID,
    idempotency_key: IdempotencyKey,
    correlation_id: uuid.UUID,
) -> None:
    """Take away the bucket this row emptied.

    The run the row came from, never every bucket the game
    holds: an act that removed a bucket it did not empty
    would remove a row its own inverse never puts back.

    Read from the batch's own events, because a chunk posted
    twice answers `Unchanged` for the move and the row then
    names the target already.

    The answer is swallowed. A refusal would count a moved
    row refused; a defect still ends the batch, as it does
    everywhere else.
    """
    try:
        emptied = run_before(actor.library, session_id, correlation_id)
    except CommandRejected:
        #: This batch moved no such row.
        return
    bucket = Playthrough.objects.filter(
        library=actor.library,
        pk=emptied,
        kind=PlaythroughKind.IMPORTED_HISTORY,
        removed_at__isnull=True,
    ).first()
    if bucket is None:
        return
    if any(rows_naming(referrer, bucket).exists() for referrer in BLOCKING_REFERRERS):
        return
    try:
        remove_run(
            actor,
            bucket,
            idempotency_key=f"{idempotency_key}-bucket",
            correlation_id=correlation_id,
            source_metadata=_source(),
        )
    except CommandFailed as failure:
        if failure.status_code != CONFLICT_STATUS:
            #: Ours, not theirs: the batch ends.
            raise
        logger.info(
            "[bulk]: %s left bucket %s of library %s under %s: %s",
            MOVE.name,
            bucket.pk,
            actor.library.pk,
            correlation_id,
            failure.message,
        )
    except Http404 as absent:
        #: A race, not a defect.
        logger.info(
            "[bulk]: %s met a bucket library %s no longer holds: %s",
            MOVE.name,
            actor.library.pk,
            absent,
        )


# ── Backward ─────────────────────────────────────────────────────────────────


def run_before(
    library: UserLibrary, session_id: uuid.UUID, batch_id: uuid.UUID
) -> uuid.UUID:
    """The run the session sat on before."""
    events = list(aggregate_events(library, session_id))
    moved = next(
        (
            event
            for event in events
            if event.correlation_id == batch_id
            and event.event_type == PLAYERSESSION_MOVED.event_type
        ),
        None,
    )
    if moved is None:
        raise CommandRejected(
            f"batch {batch_id} moved no session {session_id}",
            sentence=NOT_MOVED_BY_THIS_BATCH,
        )
    earlier = [
        event
        for event in events
        if event.sequence < moved.sequence and event.event_type in RUN_STATED
    ]
    if not earlier:
        raise CommandRejected(
            f"session {session_id} states no run before sequence {moved.sequence}",
            sentence=NO_EARLIER_RUN,
        )
    return uuid.UUID(earlier[-1].payload["playthrough"])


def _session_of(actor: User, session_id: uuid.UUID) -> PlayerSession:
    """The row an Undo speaks about."""
    with answered("session"):
        row = PlayerSession.objects.filter(library=actor.library, pk=session_id).first()
        if row is None:
            raise RowNotHeld(
                f"PlayerSession {session_id} is not library {actor.library.pk}'s, "
                "so the batch's inverse has no row to state a fact about."
            )
    return row


def _put_back_the_run(
    actor: User,
    batch_id: uuid.UUID,
    run_id: uuid.UUID,
    idempotency_key: IdempotencyKey,
    correlation_id: uuid.UUID,
) -> None:
    """Restore the run this batch emptied.

    Only that one. `RestorePlaythrough` puts back a run of
    any kind, so an inverse restoring whatever it found
    removed would also resurrect an ordinary run somebody
    removed by hand after the batch emptied it.

    Before the move, because a move onto a removed run is
    refused.
    """
    with answered("session"):
        run = Playthrough.objects.filter(library=actor.library, pk=run_id).first()
        if run is None:
            raise CommandRejected(
                f"playthrough {run_id} is not library {actor.library.pk}'s",
                sentence=NO_EARLIER_RUN,
            )
        ours = (
            batch_events(actor.library, batch_id)
            .filter(aggregate_id=run_id, event_type=PLAYTHROUGH_REMOVED.event_type)
            .exists()
        )
        if not ours and run.removed_at is not None:
            raise CommandRejected(
                f"playthrough {run_id} was removed outside batch {batch_id}",
                sentence=SOURCE_TAKEN_AWAY,
            )
    if not ours:
        return
    restore_run(
        actor,
        run,
        idempotency_key=f"{idempotency_key}-restore",
        correlation_id=correlation_id,
        source_metadata=_source(),
    )


def move_back(
    actor: User,
    session_id: uuid.UUID,
    *,
    choice: ChoiceValue | None,
    idempotency_key: IdempotencyKey,
    correlation_id: uuid.UUID,
) -> RowOutcome:
    """One session back to its earlier run."""
    with answered("session"):
        if choice is None:
            raise RowUnreadable(
                f"{MOVE.name}'s inverse ran with no batch. The undo leg states "
                "the correlation id it undoes."
            )
        batch_id = uuid.UUID(choice)
        earlier = run_before(actor.library, session_id, batch_id)
    _put_back_the_run(actor, batch_id, earlier, idempotency_key, correlation_id)
    return RowOutcome.of(
        move_session(
            actor,
            _session_of(actor, session_id),
            earlier,
            idempotency_key=f"{idempotency_key}-move",
            correlation_id=correlation_id,
            source_metadata=_source(),
        )
    )


TARGET: BulkChoice[PlayerSession] = BulkChoice(offer=offer_target, settle=settle_target)

MOVE = BulkAction(
    name="session.move",
    label="Move to playthrough…",
    title="Move these sessions to a playthrough",
    confirm_label="Move",
    subject="session",
    cardinality=Cardinality.MANY,
    color="blue",
    inverse_aggregate="playersession",
    fallback="games:list_sessions",
    scope=move_scope,
    resolve=move_resolution,
    run=move_one,
    inverse=move_back,
    preview=MOVE_PREVIEW,
    choice=TARGET,
)
