"""Resolving one library-scoped row inside a command."""

import uuid

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from graphs import default_graph

from games.commands.scope import Refusal, library_row, visible_row
from games.events.dispatch import CommandContext, CommandRejected, RowNotHeld
from games.models import Game, PlayerGame, Release
from games.removal import remove


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


@pytest.fixture
def two_releases(owned_library, other_library):
    """A shared Release and the other library's private one."""
    shared = default_graph(Game(name="Tunic", library=owned_library), owned_library)
    Game.objects.filter(pk=shared.game.pk).update(library=None)
    private = default_graph(Game(name="Hades", library=other_library), other_library)
    return shared.release, private.release


def test_visible_row_answers_a_shared_row(owned_user, owned_library, two_releases):
    shared, _private = two_releases
    context = CommandContext(library=owned_library, actor=owned_user)

    assert (
        visible_row(context, Release.objects.all(), refusal(), pk=shared.pk) == shared
    )


def test_visible_row_answers_the_librarys_own_private_row(owned_user, owned_library):
    own = default_graph(Game(name="Hades", library=owned_library), owned_library)
    context = CommandContext(library=owned_library, actor=owned_user)

    resolved = visible_row(context, Release.objects.all(), refusal(), pk=own.release.pk)

    assert resolved == own.release


def test_visible_row_refuses_another_librarys_private_row_with_the_stated_class(
    owned_user, owned_library, two_releases
):
    _shared, private = two_releases
    context = CommandContext(library=owned_library, actor=owned_user)

    with pytest.raises(RowNotHeld):
        visible_row(context, Release.objects.all(), refusal(), pk=private.pk)
    with pytest.raises(Nowhere) as refused:
        visible_row(
            context,
            Release.objects.all(),
            refusal(sentence="Not yours.", raises=Nowhere),
            pk=private.pk,
        )
    assert refused.value.sentence == "Not yours."


def test_visible_row_reads_removed_rows_when_the_caller_passes_all(
    owned_user, owned_library, two_releases
):
    shared, _private = two_releases
    remove(shared)
    context = CommandContext(library=owned_library, actor=owned_user)

    assert (
        visible_row(context, Release.objects.all(), refusal(), pk=shared.pk) == shared
    )
    with pytest.raises(RowNotHeld):
        visible_row(context, Release.objects.alive(), refusal(), pk=shared.pk)


def test_visible_row_refuses_a_model_reaching_no_library(owned_user, owned_library):
    context = CommandContext(library=owned_library, actor=owned_user)
    with pytest.raises(TypeError, match="reaches no library"):
        visible_row(context, get_user_model().objects.all(), refusal(), pk=1)
