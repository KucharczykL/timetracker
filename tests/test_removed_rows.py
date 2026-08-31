"""What removal does to the reads.

A removed row leaves every library-scoped read and stays for the
callers that resolve it. The column is set by hand here.
"""

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from games.forms import GameForm, PlatformForm
from games.models import Device, Edition, Game, Platform, Release

pytestmark = pytest.mark.django_db

REMOVED = "2026-08-25T12:00:00Z"


@pytest.fixture
def other_library(django_user_model):
    return django_user_model.objects.create_user(
        username="second-owner", password="p"
    ).library


def make_game(library, name="Baldur's Gate 3", **overrides):
    return Game.objects.create(
        library=library, name=name, year_released=2023, **overrides
    )


def remove_row(instance):
    type(instance).objects.filter(pk=instance.pk).update(removed_at=REMOVED)
    instance.refresh_from_db()
    return instance


def restore_row(instance):
    type(instance).objects.filter(pk=instance.pk).update(removed_at=None)
    instance.refresh_from_db()
    return instance


def make_graph(library, name="Baldur's Gate 3"):
    game = make_game(library, name=name)
    edition = Edition.objects.create(game=game, is_default=True)
    release = Release.objects.create(edition=edition, is_default=True)
    return game, edition, release


# --- the row leaves every library-scoped read --------------------------------


def test_a_removed_game_leaves_its_library(owned_library):
    game = remove_row(make_game(owned_library))

    assert not Game.objects.for_library(owned_library).exists()
    assert not Game.objects.visible_to(owned_library).exists()
    assert Game.objects.filter(pk=game.pk).exists()


def test_a_removed_private_platform_leaves_its_library(owned_library):
    platform = remove_row(
        Platform.objects.create(library=owned_library, name="Steam", group="PC")
    )

    assert not Platform.objects.for_library(owned_library).exists()
    assert not Platform.objects.visible_to(owned_library).exists()
    assert Platform.objects.filter(pk=platform.pk).exists()


def test_a_removed_shared_platform_leaves_every_library(owned_library, other_library):
    remove_row(Platform.objects.create(name="Steam", group="PC"))

    assert not Platform.objects.visible_to(owned_library).exists()
    assert not Platform.objects.visible_to(other_library).exists()


def test_a_removed_device_leaves_its_library(owned_library):
    device = remove_row(
        Device.objects.create(
            library=owned_library, name="Steam Deck", type=Device.HANDHELD
        )
    )

    assert not Device.objects.for_library(owned_library).exists()
    assert Device.objects.filter(pk=device.pk).exists()


def test_a_live_row_stays(owned_library):
    game = make_game(owned_library)
    platform = Platform.objects.create(library=owned_library, name="Steam", group="PC")
    device = Device.objects.create(
        library=owned_library, name="Steam Deck", type=Device.HANDHELD
    )

    assert list(Game.objects.for_library(owned_library)) == [game]
    assert list(Platform.objects.for_library(owned_library)) == [platform]
    assert list(Device.objects.for_library(owned_library)) == [device]


def test_alive_is_what_the_plain_manager_adds(owned_library):
    live = make_game(owned_library, name="Live")
    remove_row(make_game(owned_library, name="Removed"))

    assert Game.objects.count() == 2
    assert list(Game.objects.alive()) == [live]


# --- a child holds its own mark, under parents that hold theirs --------------


def test_the_editions_of_a_removed_game_leave_with_it(owned_library):
    game = make_game(owned_library)
    edition = Edition.objects.create(game=game, is_default=True)
    release = Release.objects.create(edition=edition, is_default=True)

    assert list(Edition.objects.for_library(owned_library)) == [edition]
    assert list(Release.objects.for_library(owned_library)) == [release]

    remove_row(game)

    assert not Edition.objects.for_library(owned_library).exists()
    assert not Edition.objects.visible_to(owned_library).exists()
    assert not Release.objects.for_library(owned_library).exists()
    assert not Release.objects.visible_to(owned_library).exists()
    assert Edition.objects.filter(pk=edition.pk).exists()
    assert Release.objects.filter(pk=release.pk).exists()


def test_a_removed_edition_takes_its_releases_with_it(owned_library):
    game, edition, release = make_graph(owned_library)

    remove_row(edition)

    assert not Edition.objects.for_library(owned_library).exists()
    assert not Release.objects.for_library(owned_library).exists()
    assert not Release.objects.visible_to(owned_library).exists()
    assert Game.objects.for_library(owned_library).get() == game
    assert Release.objects.filter(pk=release.pk).exists()


def test_a_removed_release_leaves_its_edition_where_it_was(owned_library):
    game, edition, release = make_graph(owned_library)

    remove_row(release)

    assert not Release.objects.for_library(owned_library).exists()
    assert Edition.objects.for_library(owned_library).get() == edition
    assert Game.objects.for_library(owned_library).get() == game
    assert Release.objects.filter(pk=release.pk).exists()


def test_restoring_a_game_leaves_a_separately_removed_child_out(owned_library):
    """Two marks, two answers. The child keeps its own."""
    game, edition, release = make_graph(owned_library)
    second = Edition.objects.create(game=game)
    remove_row(edition)
    remove_row(game)

    restore_row(game)

    assert Edition.objects.for_library(owned_library).get() == second
    assert not Release.objects.for_library(owned_library).exists()
    assert Release.objects.filter(pk=release.pk).exists()


def test_a_removed_child_stays_for_the_plain_manager(owned_library):
    _, edition, release = make_graph(owned_library)
    remove_row(edition)
    remove_row(release)

    assert Edition.objects.count() == 1
    assert Release.objects.count() == 1
    assert list(Edition.objects.alive()) == []
    assert list(Release.objects.alive()) == []


def test_removing_a_child_in_one_library_leaves_the_other_alone(
    owned_library, other_library
):
    _, mine, _ = make_graph(owned_library, name="Mine")
    _, theirs, their_release = make_graph(other_library, name="Theirs")

    remove_row(mine)

    assert not Edition.objects.for_library(owned_library).exists()
    assert Edition.objects.for_library(other_library).get() == theirs
    assert Release.objects.for_library(other_library).get() == their_release


# --- the name comes back with the row gone -----------------------------------


def test_a_removed_games_name_is_free_again(owned_library):
    platform = Platform.objects.create(library=owned_library, name="Steam", group="PC")
    remove_row(make_game(owned_library, platform=platform))

    remade = make_game(owned_library, platform=platform)

    assert Game.objects.for_library(owned_library).get() == remade


def test_a_removed_platformless_games_name_is_free_again(owned_library):
    remove_row(make_game(owned_library))

    remade = make_game(owned_library)

    assert Game.objects.for_library(owned_library).get() == remade


def test_two_live_games_still_collide(owned_library):
    make_game(owned_library)

    with pytest.raises(IntegrityError), transaction.atomic():
        make_game(owned_library)


def test_a_removed_platforms_name_is_free_again(owned_library):
    remove_row(Platform.objects.create(library=owned_library, name="Steam", group="PC"))

    remade = Platform.objects.create(library=owned_library, name="Steam", group="PC")

    assert Platform.objects.for_library(owned_library).get() == remade


def test_two_live_private_platforms_still_collide(owned_library):
    Platform.objects.create(library=owned_library, name="Steam", group="PC")

    with pytest.raises(IntegrityError), transaction.atomic():
        Platform.objects.create(library=owned_library, name="steam ", group="PC")


def test_a_removed_shared_platform_no_longer_shadows(owned_library):
    """`Platform.clean` reads the constraints' policy."""
    remove_row(Platform.objects.create(name="Steam", group="PC"))

    private = Platform.objects.create(library=owned_library, name="Steam", group="PC")

    assert private.pk is not None


def test_a_live_shared_platform_still_shadows(owned_library):
    Platform.objects.create(name="Steam", group="PC")

    with pytest.raises(ValidationError, match="shadow"):
        Platform.objects.create(library=owned_library, name="Steam", group="PC")


# --- the form layer reads the same policy ------------------------------------


def test_the_add_game_form_accepts_a_removed_duplicate(owned_library):
    """The form and the constraint agree.

    Without the `removed_at` exclusion fix, the form would also
    accept a live duplicate. See `docs/event-retention.md`.
    """
    remove_row(make_game(owned_library, name="Tetris"))

    form = GameForm(
        data={
            "name": "Tetris",
            "platform": "",
            "year_released": 2023,
            "status": "unplayed",
        },
        library=owned_library,
    )

    assert form.is_valid(), form.errors


def test_the_add_platform_form_accepts_a_removed_duplicate(owned_library):
    remove_row(Platform.objects.create(library=owned_library, name="Steam", group="PC"))

    form = PlatformForm(
        data={"name": "Steam", "icon": "", "group": "PC"}, library=owned_library
    )

    assert form.is_valid(), form.errors


# --- one library's removal says nothing about another ----------------------


def test_removal_in_one_library_leaves_the_other_alone(owned_library, other_library):
    remove_row(make_game(owned_library))
    theirs = make_game(other_library)

    assert not Game.objects.for_library(owned_library).exists()
    assert list(Game.objects.for_library(other_library)) == [theirs]
