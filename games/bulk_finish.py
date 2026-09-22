"""Finishing running sessions, in bulk.

One act, and one instant. The runner keys each row from the batch's token
and fingerprints the command's input, so a payload that differs between two
posts of one chunk raises `IdempotencyKeyMismatch` and every already-finished
row is counted refused. `timezone.now()` inside `run` is such a payload, which
is why the instant is stamped once, into the confirmation's own HTML, and
carried in the choice from there.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from django.contrib.auth.models import User
from django.http import QueryDict
from django.utils import timezone

from common.components import BrowserTimeZoneInput, Div, Input, P
from common.components.domain import BROWSER_TIME_ZONE_FIELD
from common.components.primitives import Cell
from common.date_time_presentation import zone_or_none
from games.bulk_actions import (
    ActTitle,
    AsksNothing,
    BulkAction,
    BulkChoice,
    ChoiceValue,
    Control,
    FieldName,
    Offered,
    Presentations,
    PreviewColumn,
    RowOutcome,
)
from games.bulk_removal import session_resolution, session_scope
from games.commands.playersession import TimedTiming
from games.events.dispatch import CommandRejected, RowNotHeld
from games.events.idempotency import IdempotencyKey
from games.events.playersession import ZoneName
from games.models import PlayerSession, UserLibrary
from games.writes.answers import answered
from games.writes.playersession import correct_session, end_session

#: The sentences a person is shown.
INSTANT_UNREADABLE = (
    "The moment this batch finishes at could not be read. Start the act again."
)
NO_INSTANT = "This batch states no moment to finish at. Start the act again."

#: What the encoding joins the two halves with. Neither half can hold it: an
#: ISO instant has none, and no IANA zone key does either.
_SEPARATOR = "|"


@dataclass(frozen=True, slots=True)
class FinishStatement:
    """The one instant a batch ends at, and the zone it was read in.

    A named type rather than a bare pair, because it crosses three boundaries
    as one string: the confirmation's hidden field, `settle`'s answer, and the
    waypoint that round-trips that answer to every later chunk.
    """

    ended_at: datetime
    ended_at_zone: ZoneName | None

    def encode(self) -> ChoiceValue:
        return f"{self.ended_at.isoformat()}{_SEPARATOR}{self.ended_at_zone or ''}"

    @classmethod
    def decode(cls, raw: ChoiceValue) -> FinishStatement:
        """The pair a form or a waypoint stated.

        Refuses what it cannot read: the field is a person's to edit, and an
        instant guessed here would be a second instant for the batch.
        """
        if not raw:
            raise CommandRejected("no instant was posted", sentence=NO_INSTANT)
        instant, _, zone = raw.partition(_SEPARATOR)
        try:
            ended_at = datetime.fromisoformat(instant)
        except ValueError as unreadable:
            raise CommandRejected(
                f"{instant!r} is no ISO instant: {unreadable}",
                sentence=INSTANT_UNREADABLE,
            ) from unreadable
        if ended_at.tzinfo is None:
            raise CommandRejected(
                f"{instant!r} states no offset, so it names no moment",
                sentence=INSTANT_UNREADABLE,
            )
        #: An unusable zone settles to no zone, as the row's own Finish does.
        readable = zone_or_none(zone)
        return cls(ended_at, readable.key if readable else None)


def offer_finish(
    library: UserLibrary, rows: Sequence[PlayerSession], field_name: FieldName
) -> Offered:
    """The instant, stamped into the form, and the browser's zone beside it.

    The instant is a function of *the form*, not of the moment a POST arrives.
    The same confirmation can be posted twice — a double submit, or Back onto a
    bfcached page — and `ConfirmPage` has no submit-once guard. A second post
    carries the same token and the same tally, so every row the first post
    ended is dispatched again under the same key. Baked into the HTML the
    payload is identical and those rows replay cleanly; minted per POST, every
    one of them would raise `IdempotencyKeyMismatch` and be reported refused.
    """
    if not rows:
        #: The confirmation says so itself.
        return AsksNothing()
    stamped = FinishStatement(timezone.now(), None).encode()
    return Control(
        Div(class_="flex flex-col gap-2")[
            P(class_="text-type-body text-body")[
                "Every session in this batch is finished at one moment, "
                "the moment this page was drawn."
            ],
            Input(type="hidden", name=field_name, value=stamped),
            BrowserTimeZoneInput(),
        ]
    )


def settle_finish(library: UserLibrary, post: QueryDict) -> ChoiceValue:
    """The stamped instant, merged with whatever zone is at hand.

    Re-run on every chunk, over its own last answer: the waypoint renders
    hidden pairs alone, so from chunk two there is no `<browser-time-zone>`
    and no zone field — only the choice holding both halves already. Composing
    the zone only where the value states none is what makes
    `settle(settle(x)) == settle(x)`.
    """
    #: Local: the act table imports this module.
    from games.views.bulk import CHOICE_FIELD

    stated = FinishStatement.decode(post.get(CHOICE_FIELD, ""))
    if stated.ended_at_zone is not None:
        return stated.encode()
    browser = zone_or_none(post.get(BROWSER_TIME_ZONE_FIELD, ""))
    return FinishStatement(stated.ended_at, browser.key if browser else None).encode()


#: A reconfirmation calls `offer` again and stamps a second instant for the
#: rows that remain. Reachable only by hand-editing the hidden field into
#: something `settle` refuses, and the rows already done have left the tally by
#: then, so nothing mismatches. Widening `offer` to see the POST for it would
#: change the runner's own interface for a path nobody reaches.
FINISH: BulkChoice[PlayerSession] = BulkChoice(offer=offer_finish, settle=settle_finish)


def _source(name: str) -> dict[str, object]:
    return {"bulk": {"action": name}}


def _stated(choice: ChoiceValue | None) -> FinishStatement:
    """The pair every row of this batch is finished on.

    A `None` choice is a defect: the runner settles before it runs, so the act
    cannot reach a row without one. `CommandRejected` under `answered` and not
    a bare exception — `_run_a_chunk` catches only `Http404` and
    `CommandFailed`, and anything else skips the log that names every row the
    batch never reached.
    """
    with answered("session"):
        if choice is None:
            raise CommandRejected(
                "the finish act was handed no choice, so it has no instant",
                sentence=NO_INSTANT,
            )
        return FinishStatement.decode(choice)


def finish_one(
    actor: User,
    session: PlayerSession,
    *,
    choice: ChoiceValue | None,
    idempotency_key: IdempotencyKey,
    correlation_id: uuid.UUID,
) -> RowOutcome:
    stated = _stated(choice)
    return RowOutcome.of(
        end_session(
            actor,
            session,
            ended_at=stated.ended_at,
            ended_at_zone=stated.ended_at_zone,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            source_metadata=_source(FINISH_SESSION.name),
        )
    )


def unfinish_one(
    actor: User,
    session_id: uuid.UUID,
    *,
    undoes: uuid.UUID,
    idempotency_key: IdempotencyKey,
    correlation_id: uuid.UUID,
) -> RowOutcome:
    """The row running again: its own start restated, with no end.

    It reads the start the row holds when the Undo runs, which is the hazard
    every batch Undo accepts. A library whose calendar zone changed between the
    Finish and the Undo has every row refused, because the correction checks
    the calendar before it compares.
    """
    session = _row(actor, session_id)
    #: Both non-null on a Timed row by CHECK alone, and this act finished one,
    #: so it is one. Asserted as `reset_session` states its own.
    assert session.started_at is not None
    assert session.day_zone is not None
    return RowOutcome.of(
        correct_session(
            actor,
            session,
            TimedTiming(
                started_at=session.started_at,
                day_zone=session.day_zone,
                started_at_zone=session.started_at_zone,
            ),
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            source_metadata=_source(FINISH_SESSION.name),
        )
    )


def _row(actor: User, session_id: uuid.UUID) -> PlayerSession:
    """The row an Undo puts back to running.

    `library_sessions` reads the catalog mark as well, and this act must not:
    a session whose catalog game was removed is still this library's to unwind.
    """
    with answered("session"):
        row = (
            PlayerSession.objects.filter(library=actor.library, pk=session_id)
            .select_related("playthrough")
            .first()
        )
        if row is None:
            raise RowNotHeld(
                f"PlayerSession {session_id} is not library {actor.library.pk}'s, "
                "so the batch's inverse has no row to put back to running."
            )
        return row


def _started(session: PlayerSession, presentations: Presentations) -> Cell:
    """When the row started, where it states one.

    A selection can hold a row this act will refuse — a Duration-only row
    states no instant — and the confirmation prints every row it resolved,
    refusals included.
    """
    if session.started_at is None:
        return "—"
    return presentations.dates.format(session.started_at, "datetime")


FINISH_PREVIEW: tuple[PreviewColumn[PlayerSession], ...] = (
    PreviewColumn("Game", lambda row, _: row.playthrough.player_game.game.name),
    PreviewColumn("Day", lambda row, _: str(row.effective_day)),
    PreviewColumn("Started", _started),
)


FINISH_SESSION = BulkAction(
    name="session.finish",
    label="Finish",
    title=ActTitle(one="Finish this session", many="Finish these sessions"),
    confirm_label="Finish",
    subject="session",
    color="green",
    inverse_aggregate="playersession",
    fallback="games:list_sessions",
    scope=session_scope,
    resolve=session_resolution,
    run=finish_one,
    inverse=unfinish_one,
    preview=FINISH_PREVIEW,
    choice=FINISH,
)
