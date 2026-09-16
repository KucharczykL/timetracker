"""Resolving one library-scoped row inside a command."""

import uuid

import pytest
from django.utils import timezone

from games.commands.scope import Refusal, library_row
from games.events.dispatch import CommandContext, CommandRejected
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
    stated = {
        "message": "This library tracks no such game.",
        "sentence": "That game is not available.",
    } | overrides
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

    with pytest.raises(CommandRejected) as across:
        library_row(context, PlayerGame.objects.all(), refusal(), game_id=theirs.pk)
    with pytest.raises(CommandRejected) as absent:
        library_row(context, PlayerGame.objects.all(), refusal(), game_id=uuid.uuid7())

    assert across.value.sentence == absent.value.sentence
    assert str(across.value) == str(absent.value)


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
            refusal(raises=Nowhere),
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
