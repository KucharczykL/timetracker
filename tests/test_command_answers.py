"""A refused command becomes an answer."""

import pytest
from django.http import Http404

from games.events.append import StreamSequenceMismatch
from games.events.conflicts import CommandConflict
from games.events.dispatch import CommandNotPermitted, CommandRejected
from games.events.idempotency import IdempotencyKeyMismatch
from games.events.retry import RetryBudgetExhausted
from games.writes.answers import CONFLICT_ANSWERS, CommandFailed, answered


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
    #: A mistyped placeholder fails here, not in a request.
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
    #: A wrong sentence is worse than a reported failure.
    class UnmappedConflict(CommandConflict):
        pass

    with pytest.raises(UnmappedConflict), answered("game"):
        raise UnmappedConflict("nobody answers this")


def test_nothing_raised_is_nothing_answered():
    with answered("game"):
        pass
