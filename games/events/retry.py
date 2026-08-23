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

from django.db import IntegrityError, OperationalError, router, transaction

from games.events.conflicts import CommandConflict
from games.models import LIBRARY_EVENT_SEQUENCE_CONSTRAINT, LibraryEvent

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


def run_in_transaction[T](
    operation: Callable[[], T],
    *,
    policy: RetryPolicy = DEFAULT_RETRY_POLICY,
) -> T:
    """Run `operation` in a transaction, re-running it when PostgreSQL kills
    the transaction for a reason another attempt could clear.

    `operation` may run up to `policy.retries + 1` times, so it must be
    re-runnable from scratch and must have no effects outside the database: no
    mail, no file writes, no outbound calls. It must not rely on in-memory model
    state surviving a rollback either -- Django leaves `pk` set on an object
    whose insert was rolled back. Callbacks registered with
    `transaction.on_commit` are safe: a failed attempt discards its own.
    """
    #: One alias for the check and the transaction. Unqualified atomic() would
    #: open on the default connection while lock_stream inspects the routed one.
    alias = router.db_for_write(LibraryEvent)
    if transaction.get_connection(alias).in_atomic_block:
        raise NestedTransactionNotSupported(
            "run_in_transaction opens the transaction it retries: rolling back "
            "here could not undo what an enclosing transaction already did, so "
            "its retries would be weaker than they look."
        )

    attempt = 0
    while True:
        try:
            with transaction.atomic(using=alias):
                return operation()
        except (IntegrityError, OperationalError) as error:
            #: A CommandConflict is neither of these, so a key mismatch leaves
            #: by the ordinary route without a case of its own.
            if not is_retryable(error):
                raise
            if attempt == policy.retries:
                raise RetryBudgetExhausted(attempt + 1) from error
            constraint_name = _constraint_name(error)
            logger.warning(
                "Retrying a command after SQLSTATE %s%s (attempt %d of %d).",
                _sqlstate(error),
                f" on {constraint_name}" if constraint_name else "",
                attempt + 1,
                policy.retries + 1,
            )
            policy.sleep(policy.delay_for(attempt))
            attempt += 1
