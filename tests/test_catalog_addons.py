import pytest
from django.contrib.auth import get_user_model
from django.db import transaction

from games.catalog_addons import (
    ADDON_WITHOUT_PARENT,
    FOREIGN_PARENT,
    HAS_ADDONS,
    OWN_PARENT,
    PARENT_NOT_MAIN,
    PARENT_ON_MAIN,
    REMOVED_PARENT,
    AddonRefused,
    state_addon,
)
from games.events.dispatch import RowNotHeld
from games.models import Game, GameKind
from games.removal import remove

pytestmark = pytest.mark.django_db


@pytest.fixture
def library(db):
    return get_user_model().objects.create_user(username="addon-owner").library


@pytest.fixture
def other_library(db):
    return get_user_model().objects.create_user(username="addon-other").library


def _game(library, name, **columns):
    return Game.objects.create(library=library, name=name, **columns)


def _addon(library, name, parent, kind=GameKind.DLC):
    game = _game(library, name)
    Game.objects.filter(pk=game.pk).update(kind=kind, parent=parent)
    game.refresh_from_db()
    return game


def _refusal(game, *, kind, parent, library) -> AddonRefused:
    with pytest.raises(AddonRefused) as refused:
        state_addon(game, kind=kind, parent=parent, library=library)
    return refused.value


def test_a_main_game_with_a_parent_is_refused(library):
    parent = _game(library, "Base")
    refusal = _refusal(
        _game(library, "Other"), kind=GameKind.MAIN, parent=parent, library=library
    )
    assert (refusal.messages[0], refusal.field) == (PARENT_ON_MAIN, "parent")


def test_an_addon_without_a_parent_is_refused(library):
    refusal = _refusal(
        _game(library, "Orphan"), kind=GameKind.DLC, parent=None, library=library
    )
    assert (refusal.messages[0], refusal.field) == (ADDON_WITHOUT_PARENT, "parent")


def test_a_game_its_own_parent_is_refused_and_left_untouched(library):
    game = _game(library, "Loop")
    refusal = _refusal(game, kind=GameKind.DLC, parent=game, library=library)

    assert (refusal.messages[0], refusal.field) == (OWN_PARENT, "parent")
    assert (game.kind, game.parent_id) == (GameKind.MAIN, None)


def test_a_parent_of_another_library_is_refused(library, other_library):
    foreign = _game(other_library, "Foreign")
    refusal = _refusal(
        _game(library, "Addon"), kind=GameKind.DLC, parent=foreign, library=library
    )
    assert (refusal.messages[0], refusal.field) == (FOREIGN_PARENT, "parent")


def test_a_newly_named_removed_parent_is_refused(library):
    parent = _game(library, "Base")
    remove(parent)
    refusal = _refusal(
        _game(library, "Addon"), kind=GameKind.DLC, parent=parent, library=library
    )
    assert (refusal.messages[0], refusal.field) == (REMOVED_PARENT, "parent")


def test_an_unchanged_removed_parent_passes(library):
    parent = _game(library, "Base")
    addon = _addon(library, "Addon", parent)
    remove(parent)

    state_addon(addon, kind=GameKind.EXPANSION, parent=parent, library=library)

    assert (addon.kind, addon.parent_id) == (GameKind.EXPANSION, parent.pk)


def test_an_addon_as_parent_is_refused(library):
    base = _game(library, "Base")
    addon = _addon(library, "Addon", base)
    refusal = _refusal(
        _game(library, "Nested"), kind=GameKind.DLC, parent=addon, library=library
    )
    assert (refusal.messages[0], refusal.field) == (PARENT_NOT_MAIN, "parent")


def test_a_main_game_with_addons_cannot_become_one(library):
    game = _game(library, "Base")
    _addon(library, "Addon", game)
    other = _game(library, "Other")

    refusal = _refusal(game, kind=GameKind.DLC, parent=other, library=library)

    assert refusal.field == "kind"
    assert refusal.messages[0] == HAS_ADDONS.format(count=1, plural="")


def test_a_removed_addon_still_holds_its_parent_main(library):
    game = _game(library, "Base")
    addon = _addon(library, "Addon", game)
    remove(addon)

    refusal = _refusal(
        game, kind=GameKind.DLC, parent=_game(library, "Other"), library=library
    )

    assert refusal.field == "kind"
    assert game.kind == GameKind.MAIN


def test_the_count_names_every_addon(library):
    game = _game(library, "Base")
    _addon(library, "First", game)
    _addon(library, "Second", game)

    refusal = _refusal(
        game, kind=GameKind.DLC, parent=_game(library, "Other"), library=library
    )

    assert refusal.messages[0] == HAS_ADDONS.format(count=2, plural="s")


def test_the_parent_s_stored_kind_decides_not_the_instance(library):
    """The locked row decides, not the instance."""
    parent = _game(library, "Base")
    Game.objects.filter(pk=parent.pk).update(
        kind=GameKind.DLC, parent=_game(library, "Root")
    )

    refusal = _refusal(
        _game(library, "Addon"), kind=GameKind.DLC, parent=parent, library=library
    )

    assert parent.kind == GameKind.MAIN
    assert refusal.messages[0] == PARENT_NOT_MAIN


def test_the_stored_parent_decides_what_is_unchanged(library):
    """The stored key decides, not the instance's."""
    stored_parent = _game(library, "Stored")
    removed = _game(library, "Removed")
    addon = _addon(library, "Addon", stored_parent)
    remove(removed)
    addon.parent_id = removed.pk

    refusal = _refusal(addon, kind=GameKind.DLC, parent=removed, library=library)

    assert refusal.messages[0] == REMOVED_PARENT


def test_an_addon_becomes_main_and_drops_its_parent(library):
    addon = _addon(library, "Addon", _game(library, "Base"))

    state_addon(addon, kind=GameKind.MAIN, parent=None, library=library)

    assert (addon.kind, addon.parent) == (GameKind.MAIN, None)


def test_a_shared_parent_passes_and_nothing_is_saved(library):
    shared = _game(None, "Shared base")
    addon = _game(library, "Addon")

    state_addon(addon, kind=GameKind.DLC, parent=shared, library=library)

    assert (addon.kind, addon.parent) == (GameKind.DLC, shared)
    addon.refresh_from_db()
    assert addon.kind == GameKind.MAIN


def test_an_unsaved_game_takes_a_parent(library):
    parent = _game(library, "Base")
    game = Game(library=library, name="New")

    state_addon(game, kind=GameKind.DLC, parent=parent, library=library)
    game.save()

    game.refresh_from_db()
    assert game.parent_id == parent.pk


@pytest.mark.django_db(transaction=True)
def test_it_refuses_to_run_outside_a_transaction(library):
    game = _game(library, "Outside")
    assert not transaction.get_connection().in_atomic_block
    with pytest.raises(RuntimeError):
        state_addon(game, kind=GameKind.MAIN, parent=None, library=library)


@pytest.mark.untracked_games
@pytest.mark.parametrize("kind", [GameKind.MAIN, GameKind.DLC])
def test_a_game_gone_since_the_fetch_is_not_held(library, kind):
    parent = _game(library, "Parent")
    fetched = _game(library, "Gone")
    Game.objects.filter(pk=fetched.pk).delete()
    stated_parent = None if kind == GameKind.MAIN else parent

    with pytest.raises(RowNotHeld, match=str(fetched.pk)), transaction.atomic():
        state_addon(fetched, kind=kind, parent=stated_parent, library=library)


@pytest.mark.untracked_games
@pytest.mark.parametrize("persisted", [False, True])
def test_a_parent_gone_since_the_clean_is_not_held(library, persisted):
    """Add Game reaches this too: the parent is in the body."""
    parent = _game(library, "Parent")
    game = _game(library, "Add-on") if persisted else Game(library=library, name="New")
    Game.objects.filter(pk=parent.pk).delete()

    with pytest.raises(RowNotHeld, match=str(parent.pk)), transaction.atomic():
        state_addon(game, kind=GameKind.DLC, parent=parent, library=library)
