"""Many sessions moved to one playthrough.

The act asks before it runs: which run the sessions go to. One
question, answered once and settled on every request that acts.

Its inverse is in the second half of this module: a session's
earlier run is no column, so the batch's own events say it.
"""

import logging
import uuid
from collections.abc import Sequence

from django.contrib.auth.models import User
from django.db.models import QuerySet
from django.http import Http404, QueryDict

from common.components.core import Fragment, Node
from common.components.primitives import Cell, Div, Label
from common.components.search_select import DEFAULT_PREFETCH, SearchSelect
from games.bulk_actions import (
    BulkAction,
    BulkChoice,
    Cardinality,
    ChoiceValue,
    FieldName,
    FilterJson,
    Presentations,
    PreviewColumn,
    Refused,
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
from games.models import PlayerSession, Playthrough, UserLibrary
from games.reads.events import aggregate_events, batch_events
from games.reads.player_sessions import library_sessions
from games.reads.playthrough_referrers import BLOCKING_REFERRERS, rows_naming
from games.reads.playthrough_runs import buckets_of, library_runs
from games.reads.session_run_labels import every_run_label
from games.writes.answers import CommandFailed, answered
from games.writes.playersession import move_session
from games.writes.playthrough import remove_run, restore_run

logger = logging.getLogger("games")

SESSION_GONE = "One of the sessions is no longer available, so it was left as it is."

#: The act asks about one game, because a run belongs to one.
TWO_GAMES = (
    "Those sessions are at {count} different games, and a playthrough "
    "belongs to one. Narrow the list by game and try again."
)

#: What a settle refuses.
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

#: The column the resolve fills in.
RUN_LABEL_ATTRIBUTE = "run_label"

#: The two events that state which run a session sits on.
RUN_STATED = (PLAYERSESSION_CREATED.event_type, PLAYERSESSION_MOVED.event_type)

#: What an Undo refuses.
NOT_MOVED_BY_THIS_BATCH = (
    "That session was not moved by this batch, so it was left as it is."
)
NO_EARLIER_RUN = (
    "Where that session was before cannot be read, so it was left as it is."
)
TARGET_TAKEN_AWAY = (
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
    """Keys to rows, each carrying the name of the run it sits on.

    The label is attached here because `display_name` raises for a
    blank-named run carrying no number, and a session's own run never
    carries one: the number is counted across a game's live ordinary
    runs, which one read states for the whole page.
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
    """What the row's run is called, as the resolve read it."""
    label = getattr(row, RUN_LABEL_ATTRIBUTE, None)
    if label is None:
        raise RowUnreadable(
            f"PlayerSession {row.pk} of library {row.library_id} reached the "
            "preview with no run label. The label is counted across a game's "
            "live ordinary runs, which move_resolution reads once for every "
            "row; a row that arrives without one came from another resolve."
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
) -> Node | str:
    """The picker, over the one game the rows are at.

    Every resolved row is read, never the printed sample: a page that
    asked about the first fifty would move the rest to a run at
    another game.

    The widget states no CSRF token of its own: the confirmation's
    form renders one, which is where its create row reads it.
    """
    if not rows:
        #: The confirmation says so itself, and offers no press.
        return Fragment()
    games = {row.playthrough.player_game_id for row in rows}
    if len(games) > 1:
        return TWO_GAMES.format(count=len(games))
    game_id = rows[0].playthrough.player_game.game_id
    return Div(class_="flex flex-col gap-2")[
        Label(for_=field_name)[TARGET_LABEL],
        SearchSelect(
            name=field_name,
            search_url=PLAYTHROUGH_SEARCH_URL,
            create_url=PLAYTHROUGH_CREATE_URL,
            #: One mapping feeds the search and the create alike, and
            #: the key is the one the creation body names.
            params={"game_id": {"value": str(game_id)}},
            prefetch=DEFAULT_PREFETCH,
            id=field_name,
        ),
    ]


def settle_target(library: UserLibrary, post: QueryDict) -> ChoiceValue:
    """The posted key, if it is a run this library can be given.

    Says nothing about the game: a continuation whose rows span two
    games has no one game to narrow to, and re-resolving every
    remaining key on every chunk would cost the batch its budget. The
    game is the row's own rule.
    """
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
    """The run this batch moves rows to.

    Read again per row, because the game comparison needs its parent.
    A run that left between the settle and this row is the settle's
    own sentence, so the batch says the same thing either way.
    """
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
    choice: ChoiceValue,
    idempotency_key: IdempotencyKey,
    correlation_id: uuid.UUID,
) -> RowOutcome:
    """One session onto the batch's run, and the bucket it emptied."""
    with answered("session"):
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
    _remove_emptied_buckets(actor, target, idempotency_key, correlation_id)
    return outcome


def _remove_emptied_buckets(
    actor: User,
    target: Playthrough,
    idempotency_key: IdempotencyKey,
    correlation_id: uuid.UUID,
) -> None:
    """Take away every bucket of the game that nothing names now.

    Asked about the game, not about the run the row came from: a
    chunk posted twice answers `Unchanged` for the move, and a
    question about the earlier run would never be asked again.

    Plural, because nothing holds a tracked game to one bucket. A
    removed or foreign row naming one is a reason to leave it: the
    first is restorable, the second is drift.

    Its answer is swallowed. A refusal here would count a moved row
    refused, and `RowUnreadable` would end the whole batch.
    """
    for bucket in buckets_of(actor.library, target.player_game):
        if any(
            rows_naming(referrer, bucket).exists() for referrer in BLOCKING_REFERRERS
        ):
            continue
        try:
            remove_run(
                actor,
                bucket,
                idempotency_key=f"{idempotency_key}-bucket-{bucket.pk}",
                correlation_id=correlation_id,
                source_metadata=_source(),
            )
        except (CommandFailed, Http404) as refusal:
            logger.info(
                "[bulk]: %s left bucket %s of library %s under %s: %s",
                MOVE.name,
                bucket.pk,
                actor.library.pk,
                correlation_id,
                refusal,
            )


# ── Backward ─────────────────────────────────────────────────────────────────


def run_before(
    library: UserLibrary, session_id: uuid.UUID, batch_id: uuid.UUID
) -> uuid.UUID:
    """The run the session sat on before this batch moved it.

    No column keeps it: the projection holds where the row is now. The
    row's own events do, and a sequence counts within one library's
    stream, so the comparison over them is total.
    """
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
    """The row an Undo states a fact about, by key.

    A plain manager scoped on the library: the move left the row live,
    and every command re-resolves it under the lock anyway.
    """
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
    """Restore the target, but only where this batch took it away.

    `RestorePlaythrough` puts back a run of any kind, so an inverse
    restoring whatever it found removed would also put back an
    ordinary run somebody removed by hand after the batch emptied it.

    Restoring first, because a move onto a removed run is refused.
    Once the run is live the restore answers `Unchanged`, so later
    rows of the same batch cost one silent dispatch.
    """
    with answered("session"):
        run = Playthrough.objects.filter(library=actor.library, pk=run_id).first()
        if run is None:
            raise CommandRejected(
                f"playthrough {run_id} is not library {actor.library.pk}'s",
                sentence=NO_EARLIER_RUN,
            )
        ours = batch_events(actor.library, batch_id).filter(
            aggregate_id=run_id, event_type=PLAYTHROUGH_REMOVED.event_type
        )
        if not ours.exists() and run.removed_at is not None:
            raise CommandRejected(
                f"playthrough {run_id} was removed outside batch {batch_id}",
                sentence=TARGET_TAKEN_AWAY,
            )
    if not ours.exists():
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
    choice: ChoiceValue,
    idempotency_key: IdempotencyKey,
    correlation_id: uuid.UUID,
) -> RowOutcome:
    """One session back to the run the batch found it on.

    The choice is the batch being undone. A run the batch created
    ahead of the move is not the batch's to take away, so nothing
    here reaches it.
    """
    batch_id = uuid.UUID(choice)
    with answered("session"):
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
