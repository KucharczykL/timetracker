"""A refused command becomes an answer."""

import importlib
import pkgutil

import pytest
from django.http import Http404

from games.events.append import StreamSequenceMismatch
from games.events.conflicts import CommandConflict
from games.events.dispatch import CommandNotPermitted, CommandRejected
from games.events.idempotency import IdempotencyKeyMismatch
from games.events.retry import RetryBudgetExhausted
from games.writes.answers import (
    ANSWERED_DIRECTLY,
    CONFLICT_ANSWERS,
    NOT_ANSWERED,
    CommandFailed,
    answered,
)


def test_an_exhausted_budget_asks_for_another_attempt():
    with pytest.raises(CommandFailed) as failure, answered("game"):
        raise RetryBudgetExhausted(3)

    assert failure.value.status_code == 409
    assert "try again" in failure.value.message


def test_a_moved_stream_asks_for_another_attempt():
    with pytest.raises(CommandFailed) as failure, answered("game"):
        raise StreamSequenceMismatch(expected=1, actual=2)

    assert failure.value.status_code == 409
    assert "try again" in failure.value.message


def test_a_reused_key_says_a_second_attempt_will_not_help():
    with pytest.raises(CommandFailed) as failure, answered("game"):
        raise IdempotencyKeyMismatch("that key belongs to another request")

    assert failure.value.status_code == 409
    assert "cannot be retried" in failure.value.message


def test_the_subject_noun_reaches_the_sentence():
    with pytest.raises(CommandFailed) as failure, answered("playthrough"):
        raise RetryBudgetExhausted(3)

    assert "this playthrough" in failure.value.message


def test_every_sentence_interpolates_and_leaves_no_brace():
    #: A mistyped placeholder fails here, not later.
    for answer in CONFLICT_ANSWERS.values():
        rendered = answer.sentence.format(subject="probe")
        assert "{" not in rendered and "}" not in rendered


def test_an_actor_who_may_not_command_is_not_found():
    #: Another library's object is absent, not forbidden.
    with pytest.raises(Http404) as refusal, answered("game"):
        raise CommandNotPermitted("That library belongs to another account.")

    assert "No such game." in str(refusal.value)


def test_a_rejected_command_carries_its_own_sentence():
    with pytest.raises(CommandFailed) as failure, answered("game"):
        raise CommandRejected("The library tracks no such game.")

    assert failure.value.status_code == 409
    assert failure.value.message == "The library tracks no such game."


def test_a_subclass_of_a_mapped_leaf_takes_its_parents_answer():
    class NarrowerExhaustion(RetryBudgetExhausted):
        pass

    with pytest.raises(CommandFailed) as failure, answered("game"):
        raise NarrowerExhaustion(3)

    assert "try again" in failure.value.message


def test_an_unmapped_conflict_leaves_unchanged():
    #: A wrong sentence is worse than none.
    class UnmappedConflict(CommandConflict):
        pass

    with pytest.raises(UnmappedConflict), answered("game"):
        raise UnmappedConflict("nobody answers this")


def test_nothing_raised_is_nothing_answered():
    with answered("game"):
        pass


def _import_every_games_module() -> None:
    """__subclasses__ sees a class only once imported."""
    import games

    for module in pkgutil.walk_packages(games.__path__, prefix="games."):
        if ".migrations" in module.name:
            continue
        importlib.import_module(module.name)


def _descendants(root: type) -> set[type]:
    """Every subclass, at any depth."""
    found: set[type] = set()
    for child in root.__subclasses__():
        found.add(child)
        found |= _descendants(child)
    return found


def test_every_conflict_leaf_of_the_application_has_an_answer():
    """The walk is the test.

    Without it this reads only the import graph of the module under
    test, which holds exactly the leaves that module maps, so the
    assertion compares a set with itself and passes whatever the
    code does.
    """
    _import_every_games_module()
    #: A test's subclass is not the application's.
    leaves = {
        leaf
        for leaf in _descendants(CommandConflict)
        if leaf.__module__.startswith("games.")
    }

    unanswered = leaves - set(CONFLICT_ANSWERS)
    assert not unanswered, (
        f"{sorted(leaf.__name__ for leaf in unanswered)} reach a person as a "
        "500. Add each to CONFLICT_ANSWERS in games/writes/answers.py."
    )


def test_every_boundary_exception_is_classified():
    """A sibling outside the hierarchy is the other way to be missed.

    CommandNotPermitted and CommandRejected are that shape already.
    """
    from games.events import append, conflicts, dispatch, idempotency, retry

    boundary = (conflicts, dispatch, retry, idempotency, append)
    #: The base is answered through its leaves.
    classified = set(CONFLICT_ANSWERS) | ANSWERED_DIRECTLY | NOT_ANSWERED
    classified.add(CommandConflict)

    declared = {
        value
        for module in boundary
        for value in vars(module).values()
        if isinstance(value, type)
        and issubclass(value, Exception)
        and value.__module__ == module.__name__
    }

    unclassified = declared - classified
    assert not unclassified, (
        f"{sorted(item.__name__ for item in unclassified)} are raised by the "
        "dispatch boundary and named nowhere in games/writes/answers.py. Put "
        "each in CONFLICT_ANSWERS, ANSWERED_DIRECTLY, or NOT_ANSWERED."
    )
