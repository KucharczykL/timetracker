"""Bounded retries for the failures PostgreSQL resolves by killing a
transaction.

The transaction is opened here, because a killed transaction cannot be repaired
from inside itself.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from random import Random

from games.events.conflicts import CommandConflict
from games.models import LIBRARY_EVENT_SEQUENCE_CONSTRAINT

logger = logging.getLogger("games")

#: Serialization failure and deadlock. Both mean the command may still succeed;
#: neither says anything about the command being wrong.
RETRYABLE_SQLSTATES = frozenset({"40001", "40P01"})

UNIQUE_VIOLATION = "23505"


class NestedTransactionNotSupported(RuntimeError):
    """Raised when a retry is asked for beneath someone else's transaction,
    where a rollback cannot undo what that transaction already did."""


class RetryBudgetExhausted(CommandConflict):
    """Every attempt lost to a concurrent write. Nothing was recorded."""

    def __init__(self, attempts: int) -> None:
        super().__init__(
            f"The command lost to a concurrent write on all {attempts} "
            "attempts. Nothing was recorded; try again."
        )
        self.attempts = attempts


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """How many times, how long between, and who does the waiting.

    `sleep` and `random` are fields so a test can assert on the delays the code
    actually produces instead of on patches of the standard library.
    """

    retries: int = 3
    base_delay: float = 0.025
    max_delay: float = 0.200
    sleep: Callable[[float], None] = time.sleep
    random: Random = field(default_factory=Random)

    def delay_for(self, attempt: int) -> float:
        """Full jitter: uniform over a bound that doubles until it caps."""
        bound = min(self.max_delay, self.base_delay * 2**attempt)
        return self.random.uniform(0, bound)


DEFAULT_RETRY_POLICY = RetryPolicy()


def _sqlstate(error: Exception) -> str | None:
    #: Django's cursor wrapper re-raises driver errors `from` the original, one
    #: level deep, so a failure that reached us through a cursor carries the
    #: psycopg exception as its cause. One raised any other way has no cause and
    #: reads as terminal -- the safe direction.
    return getattr(error.__cause__, "sqlstate", None)


def _constraint_name(error: Exception) -> str | None:
    diagnostic = getattr(error.__cause__, "diag", None)
    return getattr(diagnostic, "constraint_name", None)


def is_retryable(error: Exception) -> bool:
    """Whether running the same transaction again could succeed.

    A unique violation qualifies only on the event sequence constraint. Any
    other one is an application bug, and retrying it four times would spend the
    budget to tell the user to retry something that can never work.
    """
    sqlstate = _sqlstate(error)
    if sqlstate in RETRYABLE_SQLSTATES:
        return True
    if sqlstate == UNIQUE_VIOLATION:
        return _constraint_name(error) == LIBRARY_EVENT_SEQUENCE_CONSTRAINT
    return False
