"""One endpoint stated at today, on many runs."""

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from django.contrib.auth.models import User
from django.http import QueryDict

from common.components import Div, Input, P
from games.bulk_actions import (
    ActTitle,
    AsksNothing,
    BulkAction,
    BulkChoice,
    ChoiceValue,
    Control,
    FieldName,
    Offered,
    PreviewColumn,
    RowOutcome,
)
from games.bulk_runs import RUN_PREVIEW, run_resolution, run_scope
from games.events.dispatch import CommandRejected, RowNotHeld, RowUnreadable
from games.events.idempotency import IdempotencyKey
from games.events.playergame import PLAYERGAME_STATUS_CHANGED
from games.events.playthrough import (
    PLAYTHROUGH_COMPLETED,
    PLAYTHROUGH_COMPLETION_CORRECTED,
    PLAYTHROUGH_COMPLETION_VOIDED,
    PLAYTHROUGH_START_CORRECTED,
    PLAYTHROUGH_START_VOIDED,
    PLAYTHROUGH_STARTED,
)
from games.models import PlayerGameStatus, Playthrough, UserLibrary
from games.reads.calendar import calendar_today
from games.reads.events import aggregate_events
from games.reads.playthrough_endpoints import stated_completion, stated_start
from games.writes.answers import answered
from games.writes.playergame import record_facts
from games.writes.playthrough import void_completion, void_start
from games.writes.playthrough_endpoints import StatedAct, state_completion, state_start
from timetracker.temporal import TemporalValue

logger = logging.getLogger("games")

#: The sentences a person is shown.
NO_DAY = "This batch states no day to record. Start the act again."
DAY_UNREADABLE = "The day this batch records could not be read. Start the act again."

#: What the confirmation says of the act.
STARTED_SENTENCE = (
    "Every playthrough in this batch is started on {day}, the day this page "
    "was drawn. Each game that is not yet played is marked Played."
)
COMPLETED_SENTENCE = (
    "Every playthrough in this batch is completed on {day}, the day this "
    "page was drawn. Each game is marked Completed."
)


@dataclass(frozen=True, slots=True)
class DayStatement:
    """The day a batch records its act on."""

    day: date

    def encode(self) -> ChoiceValue:
        return self.day.isoformat()

    @classmethod
    def decode(cls, raw: ChoiceValue) -> DayStatement:
        """The day stated; a guess is a second day."""
        if not raw:
            raise CommandRejected("no day was posted", sentence=NO_DAY)
        try:
            return cls(date.fromisoformat(raw))
        except ValueError as unreadable:
            raise CommandRejected(
                f"{raw!r} is no ISO day: {unreadable}", sentence=DAY_UNREADABLE
            ) from unreadable


def _offer_the_day(
    rows: Sequence[Playthrough], field_name: FieldName, sentence: str
) -> Offered:
    """The library's day, stamped into the form.

    One confirmation can be posted twice, and each row of the first post
    is dispatched again under one key. Stamped, the payload matches and
    those rows replay; read again per POST, a batch that crosses
    midnight reports every one of them refused.
    """
    if not rows:
        #: The confirmation says so itself.
        return AsksNothing()
    stated = DayStatement(calendar_today(rows[0].library)).encode()
    return Control(
        Div(class_="flex flex-col gap-2")[
            P(class_="text-type-body text-body")[sentence.format(day=stated)],
            Input(type="hidden", name=field_name, value=stated),
        ]
    )


def offer_start_day(
    library: UserLibrary, rows: Sequence[Playthrough], field_name: FieldName
) -> Offered:
    return _offer_the_day(rows, field_name, STARTED_SENTENCE)


def offer_completion_day(
    library: UserLibrary, rows: Sequence[Playthrough], field_name: FieldName
) -> Offered:
    return _offer_the_day(rows, field_name, COMPLETED_SENTENCE)


def settle_day(library: UserLibrary, post: QueryDict) -> ChoiceValue:
    """The stamped day, read back.

    Every chunk settles its own last answer, so decoding and encoding
    again is what makes `settle(settle(x)) == settle(x)`.
    """
    #: Local: the act table imports this module.
    from games.views.bulk import CHOICE_FIELD

    return DayStatement.decode(post.get(CHOICE_FIELD, "")).encode()


START_DAY: BulkChoice[Playthrough] = BulkChoice(
    offer=offer_start_day, settle=settle_day
)
COMPLETION_DAY: BulkChoice[Playthrough] = BulkChoice(
    offer=offer_completion_day, settle=settle_day
)


def _source(name: str) -> dict[str, object]:
    return {"bulk": {"action": name}}


def _stated_day(choice: ChoiceValue | None, run: Playthrough, name: str) -> date:
    """The day every row of this batch records.

    A `None` choice is a defect: the runner settles before it runs.
    Raised under `answered`, because the runner catches `Http404` and
    `CommandFailed` alone, and anything else skips the log that names
    every row it never reached.
    """
    with answered("playthrough"):
        if choice is None:
            raise RowUnreadable(
                f"{name} ran with no day for Playthrough {run.pk} of library "
                f"{run.library_id}. The act declares a choice, so the runner "
                "settles one before a row."
            )
        return DayStatement.decode(choice).day


def _report_a_refused_status(stated: StatedAct, run: Playthrough, name: str) -> None:
    """The endpoint stands; the word it implies did not.

    Logged, not counted: a refusal here would report a stated endpoint
    as refused.
    """
    if stated.status_refusal is None:
        return
    logger.info(
        "[bulk]: %s stated the endpoint of playthrough %s of library %s, and "
        "the game kept its status: %s",
        name,
        run.pk,
        run.library_id,
        stated.status_refusal.message,
    )


def start_one(
    actor: User,
    run: Playthrough,
    *,
    choice: ChoiceValue | None,
    idempotency_key: IdempotencyKey,
    correlation_id: uuid.UUID,
) -> RowOutcome:
    day = _stated_day(choice, run, START_RUNS.name)
    stated = state_start(
        actor,
        run,
        TemporalValue.from_day(day),
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        source_metadata=_source(START_RUNS.name),
    )
    _report_a_refused_status(stated, run, START_RUNS.name)
    return RowOutcome.of(stated.result)


def complete_one(
    actor: User,
    run: Playthrough,
    *,
    choice: ChoiceValue | None,
    idempotency_key: IdempotencyKey,
    correlation_id: uuid.UUID,
) -> RowOutcome:
    day = _stated_day(choice, run, COMPLETE_RUNS.name)
    stated = state_completion(
        actor,
        run,
        TemporalValue.from_day(day),
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        source_metadata=_source(COMPLETE_RUNS.name),
    )
    _report_a_refused_status(stated, run, COMPLETE_RUNS.name)
    return RowOutcome.of(stated.result)


# ── Backward ─────────────────────────────────────────────────────────────────

#: What one row's Undo refuses.
NOT_STATED_BY_THIS_BATCH = (
    "That playthrough was not recorded by this batch, so it was left as it is."
)
CHANGED_SINCE = (
    "That playthrough has been recorded again since this batch, so it was "
    "left as it is. Correct it by hand instead."
)

#: One endpoint's events; the latest of them owns the value.
_START_FAMILY = (
    PLAYTHROUGH_STARTED.event_type,
    PLAYTHROUGH_START_CORRECTED.event_type,
    PLAYTHROUGH_START_VOIDED.event_type,
)
_COMPLETION_FAMILY = (
    PLAYTHROUGH_COMPLETED.event_type,
    PLAYTHROUGH_COMPLETION_CORRECTED.event_type,
    PLAYTHROUGH_COMPLETION_VOIDED.event_type,
)


def _row(actor: User, run_id: uuid.UUID) -> Playthrough:
    """The row an Undo speaks about.

    The plain manager: a run whose catalog game went is still this
    library's to unwind.
    """
    with answered("playthrough"):
        row = (
            Playthrough.objects.filter(library=actor.library, pk=run_id)
            .select_related("player_game__game")
            .first()
        )
        if row is None:
            raise RowNotHeld(
                f"Playthrough {run_id} is not library {actor.library.pk}'s, so "
                "the batch's inverse has no row to take a record back from."
            )
        return row


def _refuse_unless_this_batch_wrote_it(
    run: Playthrough,
    batch_id: uuid.UUID,
    family: tuple[str, ...],
    stated: str,
) -> None:
    """Refuse a value another act wrote after this batch.

    The batch's own event must still be the latest of the family. A
    correction states a day a person typed, and a second statement one
    another act recorded; voiding either destroys a value this batch
    never wrote, and no command puts it back.
    """
    about = [
        event
        for event in aggregate_events(run.library, run.pk)
        if event.event_type in family
    ]
    ours = [
        event
        for event in about
        if event.correlation_id == batch_id and event.event_type == stated
    ]
    if not ours:
        raise CommandRejected(
            f"batch {batch_id} recorded no {stated} of playthrough {run.pk}",
            sentence=NOT_STATED_BY_THIS_BATCH,
        )
    if about[-1].sequence != ours[-1].sequence:
        raise CommandRejected(
            f"playthrough {run.pk} states {about[-1].event_type} at sequence "
            f"{about[-1].sequence}, after batch {batch_id} recorded {stated}",
            sentence=CHANGED_SINCE,
        )


def _status_before(run: Playthrough, batch_id: uuid.UUID) -> PlayerGameStatus | None:
    """The word the game held before the batch.

    None where the batch changed none. Unplayed where the stream states
    no earlier word, which is what a tracked row holds.
    """
    events = [
        event
        for event in aggregate_events(run.library, run.player_game_id)
        if event.event_type == PLAYERGAME_STATUS_CHANGED.event_type
    ]
    ours = next((event for event in events if event.correlation_id == batch_id), None)
    if ours is None:
        return None
    earlier = [event for event in events if event.sequence < ours.sequence]
    if not earlier:
        return PlayerGameStatus.UNPLAYED
    return PlayerGameStatus(earlier[-1].payload["status"])


def _stated_since(run: Playthrough, batch_id: uuid.UUID, undoing: uuid.UUID) -> bool:
    """Whether anybody but this Undo stated it since.

    Two rows at one game share one forward event, so the second row
    would otherwise read the restoration of the first as a change
    somebody made.
    """
    events = [
        event
        for event in aggregate_events(run.library, run.player_game_id)
        if event.event_type == PLAYERGAME_STATUS_CHANGED.event_type
    ]
    ours = next((event for event in events if event.correlation_id == batch_id), None)
    if ours is None:
        return False
    return any(
        event.sequence > ours.sequence and event.correlation_id != undoing
        for event in events
    )


def _put_the_status_back(
    actor: User,
    run: Playthrough,
    *,
    undoes: uuid.UUID,
    idempotency_key: IdempotencyKey,
    correlation_id: uuid.UUID,
    name: str,
) -> None:
    """State the word that stood before the batch."""
    before = _status_before(run, undoes)
    if before is None:
        return
    if _stated_since(run, undoes, correlation_id):
        logger.info(
            "[bulk]: %s left game %s of library %s at %s; %s is what the "
            "batch changed it from",
            name,
            run.player_game.game_id,
            run.library_id,
            run.player_game.status,
            before,
        )
        return
    record_facts(
        actor,
        run.player_game.game,
        status=before,
        correlation_id=correlation_id,
        idempotency_key=f"{idempotency_key}-status",
        source_metadata=_source(name),
    )


def void_start_one(
    actor: User,
    run_id: uuid.UUID,
    *,
    undoes: uuid.UUID,
    idempotency_key: IdempotencyKey,
    correlation_id: uuid.UUID,
) -> RowOutcome:
    """The run states no start; the game as it stood."""
    run = _row(actor, run_id)
    if stated_start(run) is not None:
        with answered("playthrough"):
            _refuse_unless_this_batch_wrote_it(
                run, undoes, _START_FAMILY, PLAYTHROUGH_STARTED.event_type
            )
    outcome = RowOutcome.of(
        void_start(
            actor,
            run,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            source_metadata=_source(START_RUNS.name),
        )
    )
    _put_the_status_back(
        actor,
        run,
        undoes=undoes,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        name=START_RUNS.name,
    )
    return outcome


def void_completion_one(
    actor: User,
    run_id: uuid.UUID,
    *,
    undoes: uuid.UUID,
    idempotency_key: IdempotencyKey,
    correlation_id: uuid.UUID,
) -> RowOutcome:
    """The run states no completion; the game as it stood."""
    run = _row(actor, run_id)
    if stated_completion(run) is not None:
        with answered("playthrough"):
            _refuse_unless_this_batch_wrote_it(
                run, undoes, _COMPLETION_FAMILY, PLAYTHROUGH_COMPLETED.event_type
            )
    outcome = RowOutcome.of(
        void_completion(
            actor,
            run,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            source_metadata=_source(COMPLETE_RUNS.name),
        )
    )
    _put_the_status_back(
        actor,
        run,
        undoes=undoes,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        name=COMPLETE_RUNS.name,
    )
    return outcome


ENDPOINT_PREVIEW: tuple[PreviewColumn[Playthrough], ...] = RUN_PREVIEW


START_RUNS = BulkAction(
    name="playthrough.start",
    label="Started today",
    title=ActTitle(
        one="Record that this playthrough started today",
        many="Record that these playthroughs started today",
    ),
    confirm_label="Record",
    subject="playthrough",
    color="green",
    inverse_aggregate="playthrough",
    inverse_model=Playthrough,
    fallback="games:list_playthroughs",
    scope=run_scope,
    resolve=run_resolution,
    run=start_one,
    inverse=void_start_one,
    preview=ENDPOINT_PREVIEW,
    choice=START_DAY,
)

COMPLETE_RUNS = BulkAction(
    name="playthrough.complete",
    label="Completed today",
    title=ActTitle(
        one="Record that this playthrough was completed today",
        many="Record that these playthroughs were completed today",
    ),
    confirm_label="Record",
    subject="playthrough",
    color="green",
    inverse_aggregate="playthrough",
    inverse_model=Playthrough,
    fallback="games:list_playthroughs",
    scope=run_scope,
    resolve=run_resolution,
    run=complete_one,
    inverse=void_completion_one,
    preview=ENDPOINT_PREVIEW,
    choice=COMPLETION_DAY,
)
