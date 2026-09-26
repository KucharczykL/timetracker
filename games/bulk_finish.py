"""Finishing running sessions, in bulk.

One act, one instant. The runner fingerprints each command's input, so a
payload that differs between two posts of one chunk raises
`IdempotencyKeyMismatch` and counts every finished row refused.
`timezone.now()` inside `run` is such a payload, which is why the instant
is stamped into the confirmation's HTML and carried in the choice.
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
from games.bulk_sessions import session_of, session_resolution, session_scope
from games.commands.playersession import TimedTiming
from games.events.dispatch import CommandRejected
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
NOT_TIMED_NOW = (
    "That session no longer records a start, so it cannot be put back to "
    "running. It was left as it is."
)

#: What joins the two halves: neither half can hold it.
#:
#: An ISO instant has no `|`, and no IANA zone key has one either. A
#: separator either half can hold splits the wrong string.
_SEPARATOR = "|"


@dataclass(frozen=True, slots=True)
class FinishStatement:
    """The instant a batch ends at, and its zone.

    Named rather than a bare pair: it crosses three boundaries as one
    string — the hidden field, `settle`'s answer, and the waypoint.
    """

    ended_at: datetime
    ended_at_zone: ZoneName | None

    def __post_init__(self) -> None:
        """The two rules `decode` reads, where every caller meets them.

        A naive instant encodes to an offsetless string the next chunk
        refuses, and a zone tzdata lost reaches the database as a defect
        with no sentence. Both are a round trip away from their cause.
        """
        if self.ended_at.tzinfo is None:
            raise ValueError(
                f"{self.ended_at!r} states no offset, so it names no moment."
            )
        if self.ended_at_zone is not None and zone_or_none(self.ended_at_zone) is None:
            raise ValueError(f"{self.ended_at_zone!r} is no zone tzdata knows.")

    def encode(self) -> ChoiceValue:
        return f"{self.ended_at.isoformat()}{_SEPARATOR}{self.ended_at_zone or ''}"

    @classmethod
    def decode(cls, raw: ChoiceValue) -> FinishStatement:
        """The pair a form or a waypoint stated.

        Refuses what it cannot read: a guess is a second instant.
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
        #: An unusable zone settles to none, as Finish does.
        readable = zone_or_none(zone)
        return cls(ended_at, readable.key if readable else None)


def offer_finish(
    library: UserLibrary, rows: Sequence[PlayerSession], field_name: FieldName
) -> Offered:
    """The instant stamped into the form, and the zone.

    The instant is the form's, not the POST's. One confirmation can be
    posted twice, and `ConfirmPage` has no submit-once guard: each row the
    first post ended is dispatched again under the same key. Stamped, the
    payload matches and those rows replay; minted per POST, every one of
    them is reported refused.
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
    """The stamped instant, and whatever zone is at hand.

    Re-run on every chunk over its own last answer: from chunk two the
    waypoint renders hidden pairs alone, so there is no zone field, only
    the choice holding both halves. Taking the zone only where the value
    states none is what makes `settle(settle(x)) == settle(x)`.
    """
    #: Local: the act table imports this module.
    from games.views.bulk import CHOICE_FIELD

    stated = FinishStatement.decode(post.get(CHOICE_FIELD, ""))
    if stated.ended_at_zone is not None:
        return stated.encode()
    browser = zone_or_none(post.get(BROWSER_TIME_ZONE_FIELD, ""))
    return FinishStatement(stated.ended_at, browser.key if browser else None).encode()


#: A reconfirmation stamps a second instant for the rows left.
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
    """The row running again: its start restated, no end.

    It reads the start the row holds now, the hazard every batch Undo
    accepts: a correction between the Finish and the Undo is what the
    row states, and this restates whatever it finds.
    """
    session = session_of(actor, session_id)
    #: A correction since the Finish can have taken both away.
    #:
    #: `CorrectSessionTiming` states a whole timing, and a Duration-only row
    #: holds neither instant nor day zone. A refusal names the row and lets
    #: the batch go on; an assert is neither answer the runner catches, so
    #: every row it never reached would go unnamed in the log.
    if session.started_at is None or session.day_zone is None:
        with answered("session"):
            raise CommandRejected(
                f"PlayerSession {session.pk} is {session.timing_mode} now, so "
                "the batch's inverse has no start to restate.",
                sentence=NOT_TIMED_NOW,
            )
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
    title=ActTitle(one="Finish this session", many="Finish {count} sessions"),
    confirm_label="Finish",
    subject="session",
    color="green",
    inverse_aggregate="playersession",
    inverse_model=PlayerSession,
    fallback="games:list_sessions",
    scope=session_scope,
    resolve=session_resolution,
    run=finish_one,
    inverse=unfinish_one,
    preview=FINISH_PREVIEW,
    choice=FINISH,
)
