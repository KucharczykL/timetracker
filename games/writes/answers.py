"""Turn a refused command into an answer a person reads.

One module for every evented domain, so the sentences and the
status codes cannot drift apart between them.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import NamedTuple

from django.db import Error as DatabaseRefusal
from django.http import Http404

from games.events.append import (
    PayloadNotCanonical,
    StreamSequenceMismatch,
    TransactionRequired,
)
from games.events.conflicts import CommandConflict
from games.events.dispatch import CommandNotPermitted, CommandRejected, RowInconsistent
from games.events.envelope import DeferredRowRefused
from games.events.idempotency import IdempotencyKeyMismatch
from games.events.projection import ProjectionRowMissing
from games.events.references import (
    ReferenceFieldUnsupported,
    UnknownReferenceKind,
    UnmappedReferenceModel,
)
from games.events.retry import NestedTransactionNotSupported, RetryBudgetExhausted
from games.events.vocabulary import (
    EventNameInvalid,
    PayloadInvalid,
    SchemaNotConfigured,
    UnregisteredEventType,
    VersionNotUpcastable,
)

logger = logging.getLogger("games")

#: The record a sentence names.
type SubjectNoun = str  # e.g. "game"

CONFLICT_STATUS = 409

#: What a defect of ours answers with. Not 409: nothing the person
#: stated was wrong, and no retry of it can succeed.
DEFECT_STATUS = 500


class CommandFailed(Exception):
    """A stated fact could not be recorded.

    It carries a status code as well as a sentence, because the
    conflict leaves disagree about what to do next.
    """

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class ConflictAnswer(NamedTuple):
    """A sentence for a person, and the status that carries it."""

    sentence: str
    status_code: int


_COLLIDED = (
    "Another change reached this {subject} first. Nothing was recorded; try again."
)

#: What a rejection that states no sentence of its own says.
REFUSED = "This {subject} cannot take that change. Reload the page and try again."

#: What a database refusal says. Every command admits a subset of what
#: the schema does, so a constraint that fires is a refusal the command
#: forgot -- a defect, reached after the stream head was locked. The
#: person is told nothing was recorded; the constraint name and the
#: failing row go to the log, where they are worth reading.
REFUSED_BY_DATABASE = (
    "This {subject} could not be recorded. Nothing was saved, and the "
    "problem has been reported."
)

#: What an inconsistent row says. Worded about the reading, not the
#: row: where the installation's tzdata lost a zone name the row is
#: right, and a sentence calling it inconsistent would send an
#: administrator to the wrong place.
REFUSED_BY_AN_INCONSISTENT_ROW = (
    "This {subject}'s record could not be read, so nothing was changed. "
    "The problem has been reported."
)

#: Not clauses: a test reads a mapping.
CONFLICT_ANSWERS: dict[type[CommandConflict], ConflictAnswer] = {
    RetryBudgetExhausted: ConflictAnswer(_COLLIDED, CONFLICT_STATUS),
    StreamSequenceMismatch: ConflictAnswer(_COLLIDED, CONFLICT_STATUS),
    IdempotencyKeyMismatch: ConflictAnswer(
        "This request cannot be retried, because its key already belongs "
        "to a different one.",
        CONFLICT_STATUS,
    ),
}

#: Own clause each. Not CommandConflict subclasses.
ANSWERED_DIRECTLY: frozenset[type[Exception]] = frozenset(
    {CommandNotPermitted, CommandRejected, RowInconsistent}
)

#: Defects in the program, not conflicts. Each one means a command
#: built something the boundary cannot carry, so there is no sentence
#: to write: nothing the person states differently would change it.
NOT_ANSWERED: frozenset[type[Exception]] = frozenset(
    {
        NestedTransactionNotSupported,
        TransactionRequired,
        PayloadNotCanonical,
        DeferredRowRefused,
        ProjectionRowMissing,
        ReferenceFieldUnsupported,
        UnknownReferenceKind,
        UnmappedReferenceModel,
        EventNameInvalid,
        PayloadInvalid,
        SchemaNotConfigured,
        UnregisteredEventType,
        VersionNotUpcastable,
    }
)


def answer_for(conflict: type[CommandConflict]) -> ConflictAnswer | None:
    """The nearest mapped ancestor's answer, or none.

    Takes the type, so a guard can ask about a class it never raises.
    """
    for ancestor in conflict.__mro__:
        answer = CONFLICT_ANSWERS.get(ancestor)
        if answer is not None:
            return answer
    return None


@contextmanager
def answered(subject: SubjectNoun) -> Iterator[None]:
    """Turn a refused command into an answer."""
    try:
        yield
    except CommandNotPermitted as error:
        #: Absent, not forbidden: a refusal discloses nothing.
        #: The layering cost #905 weighed and accepted.
        raise Http404(f"No such {subject}.") from error
    except CommandConflict as error:
        answer = answer_for(type(error))
        if answer is None:
            #: A wrong sentence is worse than none.
            raise
        raise CommandFailed(
            answer.sentence.format(subject=subject), answer.status_code
        ) from error
    except RowInconsistent as error:
        #: Ahead of its parent, which would answer it as a rule.
        #: The traceback carries the argument and every cause.
        logger.exception("[answers]: a command refused an inconsistent %s.", subject)
        raise CommandFailed(
            REFUSED_BY_AN_INCONSISTENT_ROW.format(subject=subject), DEFECT_STATUS
        ) from error
    except CommandRejected as error:
        #: Never str(error): the argument is written for a developer
        #: and names ids and issues. A raise site that states no
        #: sentence gets a plain one, so a new one cannot leak.
        if error.sentence is None:
            logger.warning("[answers]: a rejection stated no sentence: %s", error)
        sentence = error.sentence or REFUSED.format(subject=subject)
        raise CommandFailed(sentence, CONFLICT_STATUS) from error
    except DatabaseRefusal as error:
        #: The backstop, never the path a refusal should take. Caught
        #: here rather than deeper because dispatch owns the
        #: transaction and has already rolled it back: nothing was
        #: recorded, whichever of the errors this was.
        #:
        #: The text PostgreSQL wrote names a constraint and prints the
        #: failing row, so it is logged and never shown.
        logger.exception(
            "[answers]: the database refused a %s a command admitted.", subject
        )
        raise CommandFailed(
            REFUSED_BY_DATABASE.format(subject=subject), DEFECT_STATUS
        ) from error
