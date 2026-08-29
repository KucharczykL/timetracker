"""Turn a refused command into an answer a person reads.

One module for every evented domain, so the sentences and the
status codes cannot drift apart between them.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import NamedTuple

from django.http import Http404

from games.events.append import (
    PayloadNotCanonical,
    StreamSequenceMismatch,
    TransactionRequired,
)
from games.events.conflicts import CommandConflict
from games.events.dispatch import CommandNotPermitted, CommandRejected
from games.events.idempotency import IdempotencyKeyMismatch
from games.events.retry import NestedTransactionNotSupported, RetryBudgetExhausted

#: The record a sentence names.
type SubjectNoun = str  # e.g. "game"

CONFLICT_STATUS = 409


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

#: A mapping rather than clauses, so a test can read it.
CONFLICT_ANSWERS: dict[type[CommandConflict], ConflictAnswer] = {
    RetryBudgetExhausted: ConflictAnswer(_COLLIDED, CONFLICT_STATUS),
    StreamSequenceMismatch: ConflictAnswer(_COLLIDED, CONFLICT_STATUS),
    IdempotencyKeyMismatch: ConflictAnswer(
        "This request cannot be retried, because its key already belongs "
        "to a different one.",
        CONFLICT_STATUS,
    ),
}

#: Answered by a clause of their own. Neither is a CommandConflict.
ANSWERED_DIRECTLY: frozenset[type[Exception]] = frozenset(
    {CommandNotPermitted, CommandRejected}
)

#: A defect in the program, not a conflict a person can act on.
NOT_ANSWERED: frozenset[type[Exception]] = frozenset(
    {NestedTransactionNotSupported, TransactionRequired, PayloadNotCanonical}
)


def answer_for(error: CommandConflict) -> ConflictAnswer | None:
    """The nearest mapped ancestor's answer, or none."""
    for ancestor in type(error).__mro__:
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
        #: Http404 from the write layer is the cost #905 accepted;
        #: the alternative replaces a 404 page with a toast.
        raise Http404(f"No such {subject}.") from error
    except CommandConflict as error:
        answer = answer_for(error)
        if answer is None:
            #: A wrong sentence is worse than a failure.
            raise
        raise CommandFailed(
            answer.sentence.format(subject=subject), answer.status_code
        ) from error
    except CommandRejected as error:
        raise CommandFailed(str(error), CONFLICT_STATUS) from error
