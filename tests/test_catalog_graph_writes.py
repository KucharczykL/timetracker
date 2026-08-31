"""The catalog service verbs that write a private Game's graph.

One Game holds many named Editions, and one Edition holds many
Releases. Every verb refuses a write it must not make.
"""

import pytest
from django.core.exceptions import ValidationError

from games.catalog_writes import add_edition
from games.models import Edition, Game
from games.removal import remove

pytestmark = pytest.mark.django_db


@pytest.fixture
def other_library(django_user_model):
    return django_user_model.objects.create_user(username="second-owner").library


@pytest.fixture
def game(owned_library):
    return Game.objects.create(library=owned_library, name="Deus Ex")


# --- add_edition -------------------------------------------------------------


def test_add_edition_names_the_first_edition_and_marks_it_default(owned_library, game):
    edition = add_edition(game=game, library=owned_library, name="Game of the Year")

    assert edition.name == "Game of the Year"
    assert edition.is_default is True
    assert Edition.objects.for_library(owned_library).get() == edition


def test_add_edition_leaves_the_standing_default_alone(owned_library, game):
    first = add_edition(game=game, library=owned_library, name="Original")

    second = add_edition(game=game, library=owned_library, name="Director's Cut")

    first.refresh_from_db()
    assert (first.is_default, second.is_default) == (True, False)


def test_add_edition_promotes_when_the_writer_asks(owned_library, game):
    first = add_edition(game=game, library=owned_library, name="Original")

    second = add_edition(
        game=game, library=owned_library, name="Director's Cut", is_default=True
    )

    first.refresh_from_db()
    assert (first.is_default, second.is_default) == (False, True)
    assert Edition.objects.filter(game=game, is_default=True).count() == 1


def test_add_edition_repeated_gives_back_the_same_edition(owned_library, game):
    first = add_edition(game=game, library=owned_library, name="Original")

    again = add_edition(game=game, library=owned_library, name=" original ")

    assert again.pk == first.pk
    assert Edition.objects.filter(game=game).count() == 1


def test_add_edition_without_a_name_gives_back_the_unnamed_edition(owned_library, game):
    first = add_edition(game=game, library=owned_library)

    again = add_edition(game=game, library=owned_library)

    assert again.pk == first.pk
    assert Edition.objects.filter(game=game).count() == 1


def test_add_edition_marks_a_default_when_the_old_one_is_removed(owned_library, game):
    first = add_edition(game=game, library=owned_library, name="Original")
    remove(first)

    second = add_edition(game=game, library=owned_library, name="Director's Cut")

    assert second.is_default is True


def test_add_edition_refuses_a_shared_game(owned_library):
    shared = Game.objects.create(name="Shared work")

    with pytest.raises(ValidationError, match="shared game"):
        add_edition(game=shared, library=owned_library, name="Original")

    assert not Edition.objects.filter(game=shared).exists()


def test_add_edition_refuses_another_librarys_game(other_library, game):
    with pytest.raises(ValidationError, match="another library"):
        add_edition(game=game, library=other_library, name="Original")

    assert not Edition.objects.filter(game=game).exists()


def test_add_edition_refuses_a_removed_game(owned_library, game):
    remove(game)

    with pytest.raises(ValidationError, match="removed"):
        add_edition(game=game, library=owned_library, name="Original")

    assert not Edition.objects.filter(game=game).exists()


def test_add_edition_leaves_the_other_librarys_graph_alone(
    owned_library, other_library, game
):
    theirs = Game.objects.create(library=other_library, name="Deus Ex")
    add_edition(game=theirs, library=other_library, name="Original")

    add_edition(game=game, library=owned_library, name="Original")

    assert Edition.objects.for_library(owned_library).count() == 1
    assert Edition.objects.for_library(other_library).count() == 1
