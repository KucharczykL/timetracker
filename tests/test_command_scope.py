"""Resolving one library-scoped row inside a command."""

import uuid

import pytest
from django.utils import timezone

from games.commands.scope import Refusal, library_row
from games.events.dispatch import CommandContext, CommandRejected, RowNotHeld
from games.models import Game, PlayerGame


class Nowhere(CommandRejected):
    """A family with its own answer."""


@pytest.fixture
def other_user(django_user_model, db):
    return django_user_model.objects.create_user(username="other-owner", password="p")


@pytest.fixture
def other_library(other_user):
    return other_user.library


def refusal(**overrides) -> Refusal:
    stated = {"message": "This library tracks no such game."} | overrides
    return Refusal(**stated)


def test_a_row_this_library_owns_resolves(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    context = CommandContext(library=owned_library, actor=owned_user)

    resolved = library_row(
        context, PlayerGame.objects.all(), refusal(), game_id=game.pk
    )

    assert resolved.game_id == game.pk


def test_another_library_row_and_a_missing_row_refuse_alike(
    owned_user, owned_library, other_user, other_library
):
    """A refusal teaches no id."""
    theirs = Game.objects.create(library=other_library, name="Outer Wilds")
    context = CommandContext(library=owned_library, actor=owned_user)

    with pytest.raises(RowNotHeld) as across:
        library_row(context, PlayerGame.objects.all(), refusal(), game_id=theirs.pk)
    with pytest.raises(RowNotHeld) as absent:
        library_row(context, PlayerGame.objects.all(), refusal(), game_id=uuid.uuid7())

    assert str(across.value) == str(absent.value)


def test_a_row_the_library_does_not_hold_states_no_sentence(owned_user, owned_library):
    """The boundary owns the answer, so nothing shows a sentence."""
    context = CommandContext(library=owned_library, actor=owned_user)

    with pytest.raises(RowNotHeld) as refused:
        library_row(context, PlayerGame.objects.all(), refusal(), game_id=uuid.uuid7())

    assert not hasattr(refused.value, "sentence")
    assert not isinstance(refused.value, CommandRejected)


def test_a_sentence_with_no_rejection_to_carry_it_is_refused():
    with pytest.raises(TypeError):
        refusal(sentence="That game is not available.")


def test_a_rejection_that_states_no_sentence_is_refused():
    with pytest.raises(TypeError):
        refusal(raises=Nowhere)


def test_a_removed_row_still_resolves(owned_user, owned_library):
    """Every restore names a removed row."""
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    tracked = PlayerGame.objects.get(library=owned_library, game=game)
    #: Not remove(): this mark is the projector's.
    PlayerGame.objects.filter(pk=tracked.pk).update(removed_at=timezone.now())
    context = CommandContext(library=owned_library, actor=owned_user)

    resolved = library_row(
        context, PlayerGame.objects.all(), refusal(), game_id=game.pk
    )

    assert resolved.removed_at is not None


def test_the_caller_states_the_class_it_refuses_with(owned_user, owned_library):
    context = CommandContext(library=owned_library, actor=owned_user)

    with pytest.raises(Nowhere) as refused:
        library_row(
            context,
            PlayerGame.objects.all(),
            refusal(raises=Nowhere, sentence="That game is not available."),
            game_id=uuid.uuid7(),
        )

    assert refused.value.sentence == "That game is not available."


def test_the_queryset_the_caller_hands_over_is_the_one_read(
    owned_user, owned_library, django_assert_num_queries
):
    """The helper adds a filter, nothing else."""
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    context = CommandContext(library=owned_library, actor=owned_user)

    resolved = library_row(
        context,
        PlayerGame.objects.select_related("game"),
        refusal(),
        game_id=game.pk,
    )

    with django_assert_num_queries(0):
        assert resolved.game.name == "Outer Wilds"
