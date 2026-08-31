"""The catalog service verbs that write a private Game's graph.

One Game holds many named Editions, and one Edition holds many
Releases. Every verb refuses a write it must not make.
"""

import pytest
from django.core.exceptions import ValidationError

from games.catalog_writes import (
    add_edition,
    add_release,
    remove_edition,
    remove_release,
    save_private_game,
    update_edition,
    update_release,
)
from games.models import Edition, Game, Platform, Release
from games.removal import remove
from timetracker.temporal import TemporalValue

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


def test_add_edition_without_a_name_adds_another_one(owned_library, game):
    """No name is not a name, thus it gives nothing back.

    A Game the legacy form made already holds an unnamed Edition.
    Matching on the empty name would answer every unnamed add with
    that one, and nothing would be added.
    """
    first = add_edition(game=game, library=owned_library)

    second = add_edition(game=game, library=owned_library)

    assert second.pk != first.pk
    assert Edition.objects.filter(game=game).count() == 2
    assert (first.is_default, second.is_default) == (True, False)


def test_add_edition_adds_beside_the_legacy_form_edition(owned_library):
    stored = Game(library=owned_library, name="Thief")
    graph = save_private_game(
        game=stored, original_release_date=None, release_date=None, platform=None
    )

    added = add_edition(game=graph.game, library=owned_library)

    assert added.pk != graph.edition.pk
    assert Edition.objects.for_library(owned_library).count() == 2


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


# --- update_edition ----------------------------------------------------------


def test_update_edition_states_the_whole_row(owned_library, game):
    edition = add_edition(game=game, library=owned_library, name="Original")

    updated = update_edition(
        edition=edition,
        library=owned_library,
        name="  Director's Cut  ",
        is_default=True,
    )

    updated.refresh_from_db()
    assert (updated.pk, updated.name) == (edition.pk, "Director's Cut")
    assert Edition.objects.filter(game=game).count() == 1


def test_update_edition_repeated_changes_nothing(owned_library, game):
    edition = add_edition(game=game, library=owned_library, name="Original")

    for _ in range(2):
        update_edition(
            edition=edition, library=owned_library, name="Original", is_default=True
        )

    assert Edition.objects.filter(game=game).count() == 1
    assert Edition.objects.filter(game=game, is_default=True).count() == 1


def test_update_edition_promotion_steps_the_old_default_down(owned_library, game):
    first = add_edition(game=game, library=owned_library, name="Original")
    second = add_edition(game=game, library=owned_library, name="Director's Cut")

    update_edition(
        edition=second, library=owned_library, name="Director's Cut", is_default=True
    )

    first.refresh_from_db()
    second.refresh_from_db()
    assert (first.is_default, second.is_default) == (False, True)


def test_update_edition_refuses_to_leave_a_game_without_a_default(owned_library, game):
    first = add_edition(game=game, library=owned_library, name="Original")
    add_edition(game=game, library=owned_library, name="Director's Cut")

    with pytest.raises(ValidationError, match="default edition"):
        update_edition(
            edition=first, library=owned_library, name="Original", is_default=False
        )

    first.refresh_from_db()
    assert first.is_default is True


def test_update_edition_refuses_a_siblings_name(owned_library, game):
    add_edition(game=game, library=owned_library, name="Original")
    second = add_edition(game=game, library=owned_library, name="Director's Cut")

    with pytest.raises(ValidationError, match="already has that name"):
        update_edition(
            edition=second, library=owned_library, name="original", is_default=False
        )

    second.refresh_from_db()
    assert second.name == "Director's Cut"


def test_update_edition_refuses_another_librarys_edition(
    owned_library, other_library, game
):
    edition = add_edition(game=game, library=owned_library, name="Original")

    with pytest.raises(ValidationError, match="another library"):
        update_edition(
            edition=edition, library=other_library, name="Theirs", is_default=True
        )

    edition.refresh_from_db()
    assert edition.name == "Original"


def test_update_edition_refuses_a_removed_edition(owned_library, game):
    first = add_edition(game=game, library=owned_library, name="Original")
    add_edition(game=game, library=owned_library, name="Director's Cut")
    remove(first)

    with pytest.raises(ValidationError, match="edition is removed"):
        update_edition(
            edition=first, library=owned_library, name="Renamed", is_default=False
        )


# --- remove_edition ----------------------------------------------------------


def test_remove_edition_takes_a_sibling_out(owned_library, game):
    add_edition(game=game, library=owned_library, name="Original")
    second = add_edition(game=game, library=owned_library, name="Director's Cut")

    remove_edition(edition=second, library=owned_library)

    second.refresh_from_db()
    assert second.removed_at is not None
    assert Edition.objects.for_library(owned_library).count() == 1
    assert Edition.objects.filter(game=game).count() == 2


def test_remove_edition_refuses_the_last_edition(owned_library, game):
    only = add_edition(game=game, library=owned_library, name="Original")

    with pytest.raises(ValidationError, match="keeps one edition"):
        remove_edition(edition=only, library=owned_library)

    only.refresh_from_db()
    assert only.removed_at is None


def test_remove_edition_refuses_the_default_while_a_sibling_lives(owned_library, game):
    first = add_edition(game=game, library=owned_library, name="Original")
    add_edition(game=game, library=owned_library, name="Director's Cut")

    with pytest.raises(ValidationError, match="default edition"):
        remove_edition(edition=first, library=owned_library)

    first.refresh_from_db()
    assert first.removed_at is None


def test_remove_edition_refuses_another_librarys_edition(
    owned_library, other_library, game
):
    add_edition(game=game, library=owned_library, name="Original")
    second = add_edition(game=game, library=owned_library, name="Director's Cut")

    with pytest.raises(ValidationError, match="another library"):
        remove_edition(edition=second, library=other_library)

    second.refresh_from_db()
    assert second.removed_at is None


# --- add_release -------------------------------------------------------------


@pytest.fixture
def edition(owned_library, game):
    return add_edition(game=game, library=owned_library, name="Original")


def test_add_release_marks_the_first_release_default(owned_library, edition):
    platform = Platform.objects.create(name="PC")

    release = add_release(
        edition=edition,
        library=owned_library,
        platform=platform,
        release_date=TemporalValue.from_year(2000),
    )

    release.refresh_from_db()
    assert release.is_default is True
    assert release.platform == platform
    assert release.release_date == TemporalValue.from_year(2000)


def test_add_release_leaves_an_unset_platform_and_date_unset(owned_library, edition):
    """Neither is inferred from the Game or from a sibling."""
    add_release(
        edition=edition,
        library=owned_library,
        platform=Platform.objects.create(name="PC"),
        release_date=TemporalValue.from_year(2000),
    )

    second = add_release(edition=edition, library=owned_library)

    second.refresh_from_db()
    assert second.platform is None
    assert second.release_date is None


def test_add_release_repeated_gives_back_the_same_release(owned_library, edition):
    platform = Platform.objects.create(name="PC")

    first = add_release(
        edition=edition,
        library=owned_library,
        platform=platform,
        release_date=TemporalValue.from_year(2000),
    )
    again = add_release(
        edition=edition,
        library=owned_library,
        platform=platform,
        release_date=TemporalValue.from_year(2000),
    )

    assert again.pk == first.pk
    assert Release.objects.filter(edition=edition).count() == 1


def test_add_release_keeps_one_default_when_the_writer_promotes(owned_library, edition):
    first = add_release(edition=edition, library=owned_library)

    second = add_release(
        edition=edition,
        library=owned_library,
        platform=Platform.objects.create(name="PC"),
        is_default=True,
    )

    first.refresh_from_db()
    assert (first.is_default, second.is_default) == (False, True)
    assert Release.objects.filter(edition=edition, is_default=True).count() == 1


def test_add_release_refuses_another_librarys_platform(
    owned_library, other_library, edition
):
    foreign = Platform.objects.create(library=other_library, name="Foreign")

    with pytest.raises(ValidationError, match="another library"):
        add_release(edition=edition, library=owned_library, platform=foreign)

    assert not Release.objects.filter(edition=edition).exists()


def test_add_release_refuses_a_shared_games_edition(owned_library):
    shared = Game.objects.create(name="Shared work")
    shared_edition = Edition.objects.create(game=shared, is_default=True)

    with pytest.raises(ValidationError, match="shared game"):
        add_release(edition=shared_edition, library=owned_library)

    assert not Release.objects.filter(edition=shared_edition).exists()


def test_add_release_refuses_a_removed_edition(owned_library, game, edition):
    add_edition(game=game, library=owned_library, name="Director's Cut")
    update_edition(
        edition=edition, library=owned_library, name="Original", is_default=True
    )
    remove(edition)

    with pytest.raises(ValidationError, match="edition is removed"):
        add_release(edition=edition, library=owned_library)


# --- update_release ----------------------------------------------------------


def test_update_release_states_the_whole_row(owned_library, edition):
    platform = Platform.objects.create(name="PC")
    release = add_release(
        edition=edition,
        library=owned_library,
        platform=platform,
        release_date=TemporalValue.from_year(2000),
    )

    updated = update_release(
        release=release,
        library=owned_library,
        platform=None,
        release_date=None,
        is_default=True,
    )

    updated.refresh_from_db()
    assert updated.pk == release.pk
    assert updated.platform is None
    assert updated.release_date is None


def test_update_release_repeated_changes_nothing(owned_library, edition):
    release = add_release(edition=edition, library=owned_library)

    for _ in range(2):
        update_release(
            release=release,
            library=owned_library,
            platform=None,
            release_date=TemporalValue.from_year(1999),
            is_default=True,
        )

    assert Release.objects.filter(edition=edition).count() == 1
    assert Release.objects.filter(edition=edition, is_default=True).count() == 1


def test_update_release_promotion_steps_the_old_default_down(owned_library, edition):
    first = add_release(edition=edition, library=owned_library)
    second = add_release(
        edition=edition,
        library=owned_library,
        platform=Platform.objects.create(name="PC"),
    )

    update_release(
        release=second,
        library=owned_library,
        platform=second.platform,
        release_date=None,
        is_default=True,
    )

    first.refresh_from_db()
    second.refresh_from_db()
    assert (first.is_default, second.is_default) == (False, True)


def test_update_release_refuses_to_leave_an_edition_without_a_default(
    owned_library, edition
):
    first = add_release(edition=edition, library=owned_library)
    add_release(
        edition=edition,
        library=owned_library,
        platform=Platform.objects.create(name="PC"),
    )

    with pytest.raises(ValidationError, match="default release"):
        update_release(
            release=first,
            library=owned_library,
            platform=None,
            release_date=None,
            is_default=False,
        )

    first.refresh_from_db()
    assert first.is_default is True


def test_update_release_refuses_another_librarys_release(
    owned_library, other_library, edition
):
    release = add_release(edition=edition, library=owned_library)

    with pytest.raises(ValidationError, match="another library"):
        update_release(
            release=release,
            library=other_library,
            platform=None,
            release_date=TemporalValue.from_year(1999),
            is_default=True,
        )

    release.refresh_from_db()
    assert release.release_date is None


def test_update_release_refuses_a_sibling_platform_and_date(owned_library, edition):
    """The pair that tells two Releases apart stays one row.

    `add_release` gives the standing row back for a repeated pair,
    thus an update must not make a pair it could never add.
    """
    first = add_release(
        edition=edition,
        library=owned_library,
        platform=Platform.objects.create(name="PS4", library=owned_library),
        release_date=TemporalValue.from_year(2001),
    )
    second = add_release(
        edition=edition,
        library=owned_library,
        platform=Platform.objects.create(name="PC", library=owned_library),
        release_date=TemporalValue.from_year(2001),
    )

    with pytest.raises(ValidationError, match="already has that platform and date"):
        update_release(
            release=second,
            library=owned_library,
            platform=first.platform,
            release_date=TemporalValue.from_year(2001),
            is_default=False,
        )

    second.refresh_from_db()
    assert second.platform != first.platform


def test_update_release_states_its_own_platform_and_date_again(owned_library, edition):
    release = add_release(
        edition=edition,
        library=owned_library,
        platform=Platform.objects.create(name="PS4", library=owned_library),
        release_date=TemporalValue.from_year(2001),
    )

    stated = update_release(
        release=release,
        library=owned_library,
        platform=release.platform,
        release_date=TemporalValue.from_year(2001),
        is_default=True,
    )

    assert stated.pk == release.pk


# --- remove_release ----------------------------------------------------------


def test_remove_release_takes_a_sibling_out(owned_library, edition):
    add_release(edition=edition, library=owned_library)
    second = add_release(
        edition=edition,
        library=owned_library,
        platform=Platform.objects.create(name="PC"),
    )

    remove_release(release=second, library=owned_library)

    second.refresh_from_db()
    assert second.removed_at is not None
    assert Release.objects.for_library(owned_library).count() == 1
    assert Release.objects.filter(edition=edition).count() == 2


def test_remove_release_takes_the_last_one_and_its_mark(owned_library, edition):
    """An Edition may hold no Release."""
    only = add_release(edition=edition, library=owned_library)

    remove_release(release=only, library=owned_library)

    only.refresh_from_db()
    assert only.removed_at is not None
    assert not Release.objects.for_library(owned_library).exists()
    assert Edition.objects.for_library(owned_library).get() == edition


def test_remove_release_refuses_the_default_while_a_sibling_lives(
    owned_library, edition
):
    first = add_release(edition=edition, library=owned_library)
    add_release(
        edition=edition,
        library=owned_library,
        platform=Platform.objects.create(name="PC"),
    )

    with pytest.raises(ValidationError, match="default release"):
        remove_release(release=first, library=owned_library)

    first.refresh_from_db()
    assert first.removed_at is None


def test_a_promoted_sibling_frees_the_old_default_for_removal(owned_library, edition):
    first = add_release(edition=edition, library=owned_library)
    second = add_release(
        edition=edition,
        library=owned_library,
        platform=Platform.objects.create(name="PC"),
    )

    update_release(
        release=second,
        library=owned_library,
        platform=second.platform,
        release_date=None,
        is_default=True,
    )
    remove_release(release=first, library=owned_library)

    first.refresh_from_db()
    assert first.removed_at is not None
    assert Release.objects.for_library(owned_library).get() == second


def test_remove_release_refuses_another_librarys_release(
    owned_library, other_library, edition
):
    release = add_release(edition=edition, library=owned_library)

    with pytest.raises(ValidationError, match="another library"):
        remove_release(release=release, library=other_library)

    release.refresh_from_db()
    assert release.removed_at is None
