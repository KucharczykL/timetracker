import re
import uuid

import pytest
from django.urls import reverse
from django.utils import timezone

from games.catalog_addons import FOREIGN_PARENT_LABEL
from games.models import (
    Game,
    GameKind,
    PlayerGame,
    PlayerGameStatus,
    Playthrough,
    PlaythroughKind,
)
from games.reads.catalog_hierarchy import tracked_addons
from games.reads.game_departures import game_departures
from games.removal import remove
from games.views.game import ADDONS_STAY

pytestmark = pytest.mark.django_db


def _addon(library, name, parent, kind=GameKind.DLC) -> Game:
    game = Game.objects.create(library=library, name=name)
    Game.objects.filter(pk=game.pk).update(kind=kind, parent=parent)
    game.refresh_from_db()
    return game


def _track(library, game: Game) -> None:
    """The seeding hook's rows, for any game."""
    tracked = PlayerGame.objects.create(
        pk=uuid.uuid7(),
        library=library,
        game=game,
        tracked_at=timezone.now(),
        status=PlayerGameStatus.UNPLAYED,
        mastered=False,
    )
    Playthrough.objects.create(
        pk=uuid.uuid7(),
        library=library,
        player_game=tracked,
        kind=PlaythroughKind.ORDINARY,
        created_at=timezone.now(),
    )


def _page(client, user, game: Game) -> str:
    client.force_login(user)
    return client.get(game.get_absolute_url()).content.decode()


def _parent_row(page: str) -> str:
    match = re.search(r"Add-on of</span>(.*?)</div>", page, re.DOTALL)
    assert match is not None, "no Add-on of row"
    return match.group(1)


def test_a_tracked_parent_is_linked(client, owned_user):
    base = Game.objects.create(library=owned_user.library, name="Base")
    addon = _addon(owned_user.library, "Addon", base)

    row = _parent_row(_page(client, owned_user, addon))

    assert f'href="{base.get_absolute_url()}"' in row
    assert "DLC" in row


def test_an_untracked_shared_parent_is_plain(client, owned_user):
    shared = Game.objects.create(library=None, name="Shared base")
    addon = _addon(owned_user.library, "Addon", shared)

    row = _parent_row(_page(client, owned_user, addon))

    assert "Shared base" in row
    assert "href=" not in row


def test_a_removed_parent_is_marked(client, owned_user):
    base = Game.objects.create(library=owned_user.library, name="Base")
    addon = _addon(owned_user.library, "Addon", base)
    remove(base)

    row = _parent_row(_page(client, owned_user, addon))

    assert "Base (removed)" in row
    assert "href=" not in row


def test_a_main_game_has_no_parent_row(client, owned_user):
    base = Game.objects.create(library=owned_user.library, name="Base")

    assert "Add-on of" not in _page(client, owned_user, base)


def test_a_shared_addon_shows_its_row(client, owned_user):
    base = Game.objects.create(library=None, name="Shared base")
    addon = Game.objects.create(library=None, name="Shared addon")
    Game.objects.filter(pk=addon.pk).update(kind=GameKind.EXPANSION, parent=base)
    _track(owned_user.library, addon)
    addon.refresh_from_db()

    row = _parent_row(_page(client, owned_user, addon))

    assert "Shared base" in row
    assert "Expansion" in row


def test_the_addons_section_lists_tracked_addons_only(
    client, owned_user, django_user_model
):
    base = Game.objects.create(library=None, name="Shared base")
    _track(owned_user.library, base)
    tracked = _addon(owned_user.library, "Tracked DLC", base)
    untracked = Game.objects.create(library=None, name="Untracked DLC")
    Game.objects.filter(pk=untracked.pk).update(kind=GameKind.DLC, parent=base)

    other = django_user_model.objects.create_user(username="addons-other")
    foreign = _addon(other.library, "Foreign DLC", base)

    assert list(tracked_addons(owned_user.library, base)) == [tracked]
    page = _page(client, owned_user, base)
    section = page[page.index('id="addons"') :]
    assert f'href="{tracked.get_absolute_url()}"' in section
    assert ">DLC<" in section
    assert PlayerGameStatus.UNPLAYED.label in section
    assert "Untracked DLC" not in page
    assert foreign.name not in page


def test_a_removed_addon_leaves_the_section(owned_user):
    base = Game.objects.create(library=owned_user.library, name="Base")
    remove(_addon(owned_user.library, "Addon", base))

    assert list(tracked_addons(owned_user.library, base)) == []


def test_a_game_with_no_addons_has_no_section(client, owned_user):
    base = Game.objects.create(library=owned_user.library, name="Base")

    assert 'id="addons"' not in _page(client, owned_user, base)


def test_the_removal_confirmation_names_the_addons_that_stay(client, owned_user):
    base = Game.objects.create(library=owned_user.library, name="Base")
    _addon(owned_user.library, "Addon", base)
    client.force_login(owned_user)

    page = client.get(reverse("games:remove_game", args=[base.pk])).content.decode()

    assert ADDONS_STAY.format(count=1) in page
    assert game_departures(owned_user.library, base).addons == 1


def test_a_removed_addon_is_not_counted_as_staying(owned_user):
    base = Game.objects.create(library=owned_user.library, name="Base")
    remove(_addon(owned_user.library, "Addon", base))

    assert game_departures(owned_user.library, base).addons == 0


def test_a_foreign_parent_keeps_its_name_away(client, owned_user, django_user_model):
    """Drift only: says whose, not what."""
    other = django_user_model.objects.create_user(username="parent-drift")
    foreign = Game.objects.create(library=other.library, name="Secret base")
    addon = _addon(owned_user.library, "Addon", foreign)

    row = _parent_row(_page(client, owned_user, addon))

    assert FOREIGN_PARENT_LABEL in row
    assert "Secret base" not in row
