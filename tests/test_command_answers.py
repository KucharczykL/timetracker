"""A refused command becomes an answer."""

import importlib
import pkgutil

import pytest
from django.db import DataError, IntegrityError
from django.http import Http404

from games.events.append import StreamSequenceMismatch
from games.events.conflicts import CommandConflict
from games.events.dispatch import CommandNotPermitted, CommandRejected, RowUnreadable
from games.events.idempotency import IdempotencyKeyMismatch
from games.events.retry import RetryBudgetExhausted
from games.writes.answers import (
    ANSWERED_DIRECTLY,
    CONFLICT_ANSWERS,
    CONFLICT_STATUS,
    DEFECT_STATUS,
    NOT_ANSWERED,
    REFUSED,
    REFUSED_BY_AN_UNREADABLE_ROW,
    REFUSED_BY_DATABASE,
    CommandFailed,
    WriteAnswer,
    answer_for,
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
    sentences = [answer.sentence for answer in CONFLICT_ANSWERS.values()]
    for sentence in [
        *sentences,
        REFUSED,
        REFUSED_BY_DATABASE,
        REFUSED_BY_AN_UNREADABLE_ROW,
    ]:
        rendered = sentence.format(subject="probe")
        assert "{" not in rendered and "}" not in rendered


def test_an_actor_who_may_not_command_is_not_found():
    #: Another library's object is absent, not forbidden.
    with pytest.raises(Http404) as refusal, answered("game"):
        raise CommandNotPermitted("That library belongs to another account.")

    assert "No such game." in str(refusal.value)


#: What a raise site writes for a developer, and never for a person.
_FOR_A_DEVELOPER = (
    "This library tracks no game 0192f3d4-0000-7000-8000-000000000000. A "
    "recorded fact belongs to a tracked game, and #676 backfills one."
)


def test_a_rejection_states_the_sentence_a_person_reads():
    with pytest.raises(CommandFailed) as failure, answered("game"):
        raise CommandRejected(
            _FOR_A_DEVELOPER, sentence="That game is not available to track."
        )

    assert failure.value.status_code == 409
    assert failure.value.message == "That game is not available to track."


def test_a_rejection_that_states_none_says_nothing_of_the_program():
    #: The argument names a row by id and an issue by number.
    with pytest.raises(CommandFailed) as failure, answered("game"):
        raise CommandRejected(_FOR_A_DEVELOPER)

    assert failure.value.status_code == 409
    assert "0192f3d4" not in failure.value.message
    assert "#676" not in failure.value.message
    assert failure.value.message == REFUSED.format(subject="game")


def test_the_subject_noun_reaches_a_rejection_that_states_none():
    with pytest.raises(CommandFailed) as failure, answered("playthrough"):
        raise CommandRejected(_FOR_A_DEVELOPER)

    assert "This playthrough" in failure.value.message


def test_the_argument_a_person_never_reads_is_logged(capture_games_logger):
    with (
        capture_games_logger() as caplog,
        pytest.raises(CommandFailed),
        answered("game"),
    ):
        raise CommandRejected(_FOR_A_DEVELOPER)

    #: Dropped from the toast, kept where it helps.
    assert "#676" in caplog.text


def test_an_unreadable_row_is_a_defect():
    """Nothing to restate, so no retry asked."""
    with pytest.raises(CommandFailed) as failure, answered("session"):
        raise RowUnreadable(_FOR_A_DEVELOPER)

    assert failure.value.status_code == DEFECT_STATUS
    assert failure.value.message == REFUSED_BY_AN_UNREADABLE_ROW.format(
        subject="session"
    )


def test_an_unreadable_row_says_nothing_of_the_program():
    with pytest.raises(CommandFailed) as failure, answered("session"):
        raise RowUnreadable(_FOR_A_DEVELOPER)

    assert "0192f3d4" not in failure.value.message
    assert "#676" not in failure.value.message


def test_an_unreadable_row_is_logged_with_its_cause(capture_games_logger):
    """One ERROR record with traceback and causes."""
    with (
        capture_games_logger() as caplog,
        pytest.raises(CommandFailed),
        answered("session"),
    ):
        try:
            raise CommandRejected("the scope miss")
        except CommandRejected as miss:
            raise RowUnreadable(_FOR_A_DEVELOPER) from miss

    (record,) = caplog.records
    assert record.levelname == "ERROR"
    assert record.exc_info is not None
    assert "#676" in record.getMessage()
    assert "the scope miss" in caplog.text


def test_an_unreadable_row_states_no_sentence():
    """A site cannot write one."""
    with pytest.raises(TypeError):
        RowUnreadable("x", sentence="y")  # type: ignore[call-arg]

    assert not hasattr(RowUnreadable("x"), "sentence")


def test_an_unreadable_row_is_no_rejection():
    """A sibling: no rule's handler may take it."""
    assert not issubclass(RowUnreadable, CommandRejected)


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


#: What PostgreSQL says, which names a constraint and the row that hit it.
_FROM_POSTGRESQL = (
    'new row for relation "games_playersession" violates check constraint '
    '"playersession_duration_not_negative"\nDETAIL: Failing row contains '
    "(0192f3d4-0000-7000-8000-000000000000, -3600)."
)


@pytest.mark.parametrize("refusal", [IntegrityError, DataError])
def test_a_database_refusal_becomes_an_answer(refusal):
    """The backstop under every command that forgot a refusal."""
    with pytest.raises(CommandFailed) as failure, answered("session"):
        raise refusal(_FROM_POSTGRESQL)

    assert failure.value.status_code == DEFECT_STATUS
    assert failure.value.message == REFUSED_BY_DATABASE.format(subject="session")


def test_a_database_refusal_says_nothing_of_the_schema():
    #: A person is shown no constraint name and no failing row.
    with pytest.raises(CommandFailed) as failure, answered("session"):
        raise IntegrityError(_FROM_POSTGRESQL)

    assert "playersession_duration_not_negative" not in failure.value.message
    assert "0192f3d4" not in failure.value.message


def test_a_database_refusal_is_logged_where_it_helps(capture_games_logger):
    """Answered civilly, recorded as the defect it is."""
    with (
        capture_games_logger() as caplog,
        pytest.raises(CommandFailed),
        answered("session"),
    ):
        raise IntegrityError(_FROM_POSTGRESQL)

    assert "playersession_duration_not_negative" in caplog.text
    assert caplog.records[-1].levelname == "ERROR"
    #: The traceback, not just the sentence.
    assert caplog.records[-1].exc_info is not None


def test_a_connection_failure_is_answered_too():
    """Every django.db.Error rolled the transaction back."""
    from django.db import InterfaceError

    with pytest.raises(CommandFailed) as failure, answered("session"):
        raise InterfaceError("connection already closed")

    assert failure.value.status_code == DEFECT_STATUS


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

    #: Through the real lookup: a parent's entry answers.
    unanswered = {leaf for leaf in leaves if answer_for(leaf) is None}
    assert not unanswered, (
        f"{sorted(leaf.__name__ for leaf in unanswered)} reach a person as a "
        "500. Add each to CONFLICT_ANSWERS in games/writes/answers.py."
    )


def test_every_boundary_exception_is_classified():
    """A sibling outside the hierarchy is the other way to be missed.

    CommandNotPermitted and CommandRejected are that shape already.
    """
    from games.events import (
        append,
        conflicts,
        dispatch,
        envelope,
        idempotency,
        projection,
        references,
        retry,
        vocabulary,
    )

    #: Every module whose exceptions can reach `answered()`: dispatch
    #: validates a payload, resolves references and projects rows before
    #: it returns. The rebuild path (replay, reconcile, rebuild) is not
    #: here, because nothing wraps it in an answer.
    boundary = (
        conflicts,
        dispatch,
        retry,
        idempotency,
        append,
        vocabulary,
        references,
        envelope,
        projection,
    )
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


def test_a_landed_write_is_truthy_and_a_refused_one_is_not():
    landed = WriteAnswer(None)
    refused = WriteAnswer(CommandFailed("Nothing was recorded.", CONFLICT_STATUS))

    assert landed
    assert not refused
    assert landed.refusal is None
    assert refused.refusal is not None
    assert refused.refusal.status_code == CONFLICT_STATUS
