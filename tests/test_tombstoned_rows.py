"""What tombstoning does to the reads.

A tombstoned row leaves every library-scoped read and stays for the
callers that resolve it. The column is set by hand here.
"""

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from games.forms import GameForm, PlatformForm
from games.models import Device, Edition, Game, Platform, Release

pytestmark = pytest.mark.django_db

TOMBSTONED = "2026-08-25T12:00:00Z"


@pytest.fixture
def other_library(django_user_model):
    return django_user_model.objects.create_user(
        username="second-owner", password="p"
    ).library


def make_game(library, name="Baldur's Gate 3", **overrides):
    return Game.objects.create(
        library=library, name=name, year_released=2023, **overrides
    )


def tombstone(instance):
    type(instance).objects.filter(pk=instance.pk).update(tombstoned_at=TOMBSTONED)
    instance.refresh_from_db()
    return instance


# --- the row leaves every library-scoped read --------------------------------


def test_a_tombstoned_game_leaves_its_library(owned_library):
    game = tombstone(make_game(owned_library))

    assert not Game.objects.for_library(owned_library).exists()
    assert not Game.objects.visible_to(owned_library).exists()
    assert Game.objects.filter(pk=game.pk).exists()


def test_a_tombstoned_private_platform_leaves_its_library(owned_library):
    platform = tombstone(
        Platform.objects.create(library=owned_library, name="Steam", group="PC")
    )

    assert not Platform.objects.for_library(owned_library).exists()
    assert not Platform.objects.visible_to(owned_library).exists()
    assert Platform.objects.filter(pk=platform.pk).exists()


def test_a_tombstoned_shared_platform_leaves_every_library(
    owned_library, other_library
):
    tombstone(Platform.objects.create(name="Steam", group="PC"))

    assert not Platform.objects.visible_to(owned_library).exists()
    assert not Platform.objects.visible_to(other_library).exists()


def test_a_tombstoned_device_leaves_its_library(owned_library):
    device = tombstone(
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
    tombstone(make_game(owned_library, name="Tombstoned"))

    assert Game.objects.count() == 2
    assert list(Game.objects.alive()) == [live]


# --- Edition and Release inherit it, having no column of their own -----------


def test_the_editions_of_a_tombstoned_game_leave_with_it(owned_library):
    game = make_game(owned_library)
    edition = Edition.objects.create(game=game, is_default=True)
    release = Release.objects.create(edition=edition, is_default=True)

    assert list(Edition.objects.for_library(owned_library)) == [edition]
    assert list(Release.objects.for_library(owned_library)) == [release]

    tombstone(game)

    assert not Edition.objects.for_library(owned_library).exists()
    assert not Edition.objects.visible_to(owned_library).exists()
    assert not Release.objects.for_library(owned_library).exists()
    assert not Release.objects.visible_to(owned_library).exists()
    assert Edition.objects.filter(pk=edition.pk).exists()
    assert Release.objects.filter(pk=release.pk).exists()


# --- the name comes back with the row gone -----------------------------------


def test_a_tombstoned_games_name_is_free_again(owned_library):
    platform = Platform.objects.create(library=owned_library, name="Steam", group="PC")
    tombstone(make_game(owned_library, platform=platform))

    remade = make_game(owned_library, platform=platform)

    assert Game.objects.for_library(owned_library).get() == remade


def test_a_tombstoned_platformless_games_name_is_free_again(owned_library):
    tombstone(make_game(owned_library))

    remade = make_game(owned_library)

    assert Game.objects.for_library(owned_library).get() == remade


def test_two_live_games_still_collide(owned_library):
    make_game(owned_library)

    with pytest.raises(IntegrityError), transaction.atomic():
        make_game(owned_library)


def test_a_tombstoned_platforms_name_is_free_again(owned_library):
    tombstone(Platform.objects.create(library=owned_library, name="Steam", group="PC"))

    remade = Platform.objects.create(library=owned_library, name="Steam", group="PC")

    assert Platform.objects.for_library(owned_library).get() == remade


def test_two_live_private_platforms_still_collide(owned_library):
    Platform.objects.create(library=owned_library, name="Steam", group="PC")

    with pytest.raises(IntegrityError), transaction.atomic():
        Platform.objects.create(library=owned_library, name="steam ", group="PC")


def test_a_tombstoned_shared_platform_no_longer_shadows(owned_library):
    """`Platform.clean` reads the constraints' policy."""
    tombstone(Platform.objects.create(name="Steam", group="PC"))

    private = Platform.objects.create(library=owned_library, name="Steam", group="PC")

    assert private.pk is not None


def test_a_live_shared_platform_still_shadows(owned_library):
    Platform.objects.create(name="Steam", group="PC")

    with pytest.raises(ValidationError, match="shadow"):
        Platform.objects.create(library=owned_library, name="Steam", group="PC")


# --- the form layer reads the same policy ------------------------------------


def test_the_add_game_form_accepts_a_tombstoned_duplicate(owned_library):
    """The form and the constraint agree.

    Without the `tombstoned_at` exclusion fix, the form would also
    accept a live duplicate. See `docs/event-retention.md`.
    """
    tombstone(make_game(owned_library, name="Tetris"))

    form = GameForm(
        data={"name": "Tetris", "platform": "", "year_released": 2023, "status": "u"},
        library=owned_library,
    )

    assert form.is_valid(), form.errors


def test_the_add_platform_form_accepts_a_tombstoned_duplicate(owned_library):
    tombstone(Platform.objects.create(library=owned_library, name="Steam", group="PC"))

    form = PlatformForm(
        data={"name": "Steam", "icon": "", "group": "PC"}, library=owned_library
    )

    assert form.is_valid(), form.errors


# --- one library's tombstone says nothing about another ----------------------


def test_tombstoning_in_one_library_leaves_the_other_alone(
    owned_library, other_library
):
    tombstone(make_game(owned_library))
    theirs = make_game(other_library)

    assert not Game.objects.for_library(owned_library).exists()
    assert list(Game.objects.for_library(other_library)) == [theirs]
