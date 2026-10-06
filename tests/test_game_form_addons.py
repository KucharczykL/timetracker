import re
from html import escape
from typing import get_args
from zoneinfo import ZoneInfo

import pytest
from django.urls import reverse
from pickers import held

from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DateTimePresentation,
)
from games.catalog_addons import (
    ADDON_WITHOUT_PARENT,
    FOREIGN_PARENT,
    FOREIGN_PARENT_LABEL,
    HAS_ADDONS,
    OWN_PARENT,
    PARENT_NOT_MAIN,
    PARENT_ON_MAIN,
    AddonField,
)
from games.forms import GameForm
from games.models import Game, GameKind
from games.removal import remove

pytestmark = pytest.mark.django_db(transaction=True)

PRESENTATION = DateTimePresentation(
    DEFAULT_DATE_TIME_FORMAT_PROFILE, "en-us", ZoneInfo("UTC")
)


def _addon(library, name, parent, kind=GameKind.DLC) -> Game:
    game = Game.objects.create(library=library, name=name)
    Game.objects.filter(pk=game.pk).update(kind=kind, parent=parent)
    game.refresh_from_db()
    return game


def _field_row(content: str, field: str) -> str:
    """One form row's markup."""
    start = content.index(f'data-field-row="{field}"')
    end = content.find("data-field-row=", start + 1)
    return content[start : end if end != -1 else None]


def _refused_on(response, field: str, sentence: str) -> None:
    assert response.status_code == 200
    assert escape(sentence) in _field_row(response.content.decode(), field)


@pytest.fixture
def logged_in(client, owned_user):
    client.force_login(owned_user)
    return client


def test_add_game_states_a_dlc_with_its_parent(logged_in, owned_user, game_post):
    base = Game.objects.create(library=owned_user.library, name="Base")

    response = logged_in.post(
        reverse("games:add_game"),
        data=game_post("Expansion Pass", kind="dlc", parent=str(base.pk)),
    )

    assert response.status_code == 302
    added = Game.objects.get(name="Expansion Pass")
    assert (added.kind, added.parent_id) == (GameKind.DLC, base.pk)


def test_a_post_naming_no_kind_saves_a_main_game(logged_in, game_post):
    response = logged_in.post(reverse("games:add_game"), data=game_post("Plain"))

    assert response.status_code == 302
    assert Game.objects.get(name="Plain").kind == GameKind.MAIN


def test_a_main_game_with_a_parent_is_refused_on_the_parent(
    logged_in, owned_user, game_post
):
    base = Game.objects.create(library=owned_user.library, name="Base")

    response = logged_in.post(
        reverse("games:add_game"),
        data=game_post("Plain", kind="main", parent=str(base.pk)),
    )

    _refused_on(response, "parent", PARENT_ON_MAIN)
    assert not Game.objects.filter(name="Plain").exists()


def test_an_addon_without_a_parent_is_refused_on_the_parent(logged_in, game_post):
    response = logged_in.post(
        reverse("games:add_game"), data=game_post("Orphan", kind="dlc")
    )

    _refused_on(response, "parent", ADDON_WITHOUT_PARENT)
    assert not Game.objects.filter(name="Orphan").exists()


def test_an_addon_as_parent_is_refused_on_the_parent(logged_in, owned_user, game_post):
    addon = _addon(
        owned_user.library,
        "Addon",
        Game.objects.create(library=owned_user.library, name="Base"),
    )

    response = logged_in.post(
        reverse("games:add_game"),
        data=game_post("Nested", kind="dlc", parent=str(addon.pk)),
    )

    _refused_on(response, "parent", PARENT_NOT_MAIN)


def test_a_game_with_addons_is_refused_on_the_kind(logged_in, owned_user, game_post):
    base = Game.objects.create(library=owned_user.library, name="Base")
    _addon(owned_user.library, "Addon", base)
    other = Game.objects.create(library=owned_user.library, name="Other")

    response = logged_in.post(
        reverse("games:edit_game", args=[base.pk]),
        data=game_post("Base", kind="dlc", parent=str(other.pk)),
    )

    _refused_on(response, "kind", HAS_ADDONS.format(count=1, plural=""))
    base.refresh_from_db()
    assert (base.name, base.kind) == ("Base", GameKind.MAIN)


def test_a_game_its_own_parent_is_refused_on_the_parent(
    logged_in, owned_user, game_post
):
    game = Game.objects.create(library=owned_user.library, name="Loop")

    response = logged_in.post(
        reverse("games:edit_game", args=[game.pk]),
        data=game_post("Loop renamed", kind="dlc", parent=str(game.pk)),
    )

    _refused_on(response, "parent", OWN_PARENT)
    game.refresh_from_db()
    assert game.name == "Loop"


def test_an_addon_becomes_a_main_game_on_edit(logged_in, owned_user, game_post):
    addon = _addon(
        owned_user.library,
        "Addon",
        Game.objects.create(library=owned_user.library, name="Base"),
    )

    response = logged_in.post(
        reverse("games:edit_game", args=[addon.pk]),
        data=game_post("Addon", kind="main", parent=""),
    )

    assert response.status_code == 302
    addon.refresh_from_db()
    assert (addon.kind, addon.parent_id) == (GameKind.MAIN, None)


@pytest.mark.parametrize("state", ["foreign", "removed"])
def test_a_parent_outside_the_picker_is_refused_on_the_parent(
    logged_in, owned_user, django_user_model, game_post, state
):
    if state == "foreign":
        other = django_user_model.objects.create_user(username="parent-other")
        parent = Game.objects.create(library=other.library, name="Elsewhere")
    else:
        parent = Game.objects.create(library=owned_user.library, name="Gone")
        remove(parent)

    response = logged_in.post(
        reverse("games:add_game"),
        data=game_post("Addon", kind="dlc", parent=str(parent.pk)),
    )

    assert response.status_code == 200
    assert "valid choice" in _field_row(response.content.decode(), "parent")
    assert not Game.objects.filter(name="Addon").exists()


def test_a_removed_parent_is_labelled_in_the_picker(logged_in, owned_user):
    base = Game.objects.create(library=owned_user.library, name="Base")
    addon = _addon(owned_user.library, "Addon", base)
    remove(base)

    row = _field_row(
        logged_in.get(reverse("games:edit_game", args=[addon.pk])).content.decode(),
        "parent",
    )

    assert re.search(r"Base[^<]*\(removed\)", row)
    assert f'value="{base.pk}"' in row


def test_a_live_parent_carries_no_removed_label(logged_in, owned_user):
    base = Game.objects.create(library=owned_user.library, name="Base")
    addon = _addon(owned_user.library, "Addon", base)

    row = _field_row(
        logged_in.get(reverse("games:edit_game", args=[addon.pk])).content.decode(),
        "parent",
    )

    assert "Base" in row
    assert "(removed)" not in row


def test_a_foreign_stored_parent_keeps_its_name_away(
    logged_in, owned_user, django_user_model, game_post
):
    """Drift only; resubmit names the cause."""
    other = django_user_model.objects.create_user(username="drift-other")
    foreign = Game.objects.create(library=other.library, name="Secret base")
    addon = _addon(owned_user.library, "Addon", foreign)
    url = reverse("games:edit_game", args=[addon.pk])

    row = _field_row(logged_in.get(url).content.decode(), "parent")
    response = logged_in.post(
        url, data=game_post("Addon", kind="dlc", parent=str(foreign.pk))
    )

    assert "Secret base" not in row
    assert escape(FOREIGN_PARENT_LABEL) in row
    _refused_on(response, "parent", FOREIGN_PARENT)


def test_every_refused_field_is_a_game_form_field():
    assert set(get_args(AddonField.__value__)) <= set(GameForm.base_fields)


def test_edit_game_reads_the_stored_kind_and_parent(owned_user):
    base = Game.objects.create(library=owned_user.library, name="Base")
    addon = _addon(owned_user.library, "Addon", base)

    form = GameForm(
        instance=addon, library=owned_user.library, presentation=PRESENTATION
    )

    assert form.initial["kind"] == GameKind.DLC
    assert form.initial["parent"] == base.pk


def test_edit_game_resubmitted_keeps_a_dlc_under_a_removed_parent(
    logged_in, owned_user, game_post
):
    base = Game.objects.create(library=owned_user.library, name="Base")
    addon = _addon(owned_user.library, "Addon", base)
    remove(base)

    response = logged_in.post(
        reverse("games:edit_game", args=[addon.pk]),
        data=game_post("Addon renamed", kind="dlc", parent=str(base.pk)),
    )

    assert response.status_code == 302
    addon.refresh_from_db()
    assert (addon.name, addon.kind, addon.parent_id) == (
        "Addon renamed",
        GameKind.DLC,
        base.pk,
    )


def test_the_edit_page_renders_the_two_fields(logged_in, owned_user):
    base = Game.objects.create(library=owned_user.library, name="Base")
    addon = _addon(owned_user.library, "Addon", base)

    content = logged_in.get(reverse("games:edit_game", args=[addon.pk])).content
    page = content.decode()

    assert held(_field_row(page, "kind"), "kind") == "dlc"
    assert "Base" in _field_row(page, "parent")
    assert "<game-addon" in page


def test_the_search_narrows_to_one_kind(logged_in, owned_user):
    base = Game.objects.create(library=owned_user.library, name="Search base")
    _addon(owned_user.library, "Search addon", base)

    main = logged_in.get("/api/games/search", {"q": "Search", "kind": "main"})
    every = logged_in.get("/api/games/search", {"q": "Search"})

    assert [option["label"] for option in main.json()] == [base.search_label]
    assert len(every.json()) == 2


def test_the_search_refuses_an_unknown_kind(logged_in):
    response = logged_in.get("/api/games/search", {"kind": "remake"})

    assert response.status_code == 422
