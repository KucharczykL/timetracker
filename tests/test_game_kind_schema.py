from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction

from games.models import Edition, EditionKind, Game, GameKind

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner(db):
    return get_user_model().objects.create_user(username="kind-owner")


@pytest.fixture
def outsider(db):
    return get_user_model().objects.create_user(username="kind-outsider")


def _game(library, name, **columns):
    return Game.objects.create(library=library, name=name, **columns)


def _refused(game, constraint, **columns):
    with pytest.raises(IntegrityError, match=constraint), transaction.atomic():
        Game.objects.filter(pk=game.pk).update(**columns)


def test_a_fresh_game_is_main_and_a_fresh_edition_full(owner):
    game = _game(owner.library, "Fresh")
    edition = Edition.objects.create(game=game)

    game.refresh_from_db()
    edition.refresh_from_db()
    assert game.kind == GameKind.MAIN
    assert game.parent_id is None
    assert edition.kind == EditionKind.FULL


def test_the_database_refuses_an_unknown_game_kind(owner):
    _refused(_game(owner.library, "Odd"), "game_kind_word", kind="remake")


def test_the_database_refuses_a_main_game_with_a_parent(owner):
    parent = _game(owner.library, "Base")
    _refused(
        _game(owner.library, "Other"), "game_parent_exactly_for_addons", parent=parent
    )


def test_the_database_refuses_an_addon_without_a_parent(owner):
    _refused(
        _game(owner.library, "Orphan"),
        "game_parent_exactly_for_addons",
        kind=GameKind.DLC,
    )


def test_the_database_refuses_a_game_its_own_parent(owner):
    game = _game(owner.library, "Loop")
    _refused(game, "game_not_its_own_parent", kind=GameKind.DLC, parent=game)


def test_the_database_refuses_an_unknown_edition_kind(owner):
    edition = Edition.objects.create(game=_game(owner.library, "Edition"))
    with pytest.raises(IntegrityError, match="edition_kind_word"), transaction.atomic():
        Edition.objects.filter(pk=edition.pk).update(kind="beta")


def _audit(user) -> str:
    output = StringIO()
    with pytest.raises(CommandError, match="violation"):
        call_command("audit_library_ownership", "--user", user.username, stdout=output)
    return output.getvalue()


def test_the_audit_reports_a_parent_of_another_library(owner, outsider):
    foreign = _game(outsider.library, "Foreign base")
    addon = _game(owner.library, "Addon")
    Game.objects.filter(pk=addon.pk).update(kind=GameKind.DLC, parent=foreign)

    assert f"Game.parent: game {addon.pk}, parent {foreign.pk}" in _audit(owner)


def test_the_audit_reports_a_shared_game_naming_a_private_parent(owner):
    private = _game(owner.library, "Private base")
    shared = _game(None, "Shared addon")
    Game.objects.filter(pk=shared.pk).update(kind=GameKind.DLC, parent=private)

    assert f"Game.parent: game {shared.pk}, parent {private.pk}" in _audit(owner)


def test_a_purge_removes_a_private_addon_and_its_private_parent(owner):
    parent = _game(owner.library, "Base")
    addon = _game(owner.library, "Addon")
    Game.objects.filter(pk=addon.pk).update(kind=GameKind.DLC, parent=parent)

    call_command(
        "purge_user_library",
        "--user",
        owner.username,
        "--confirm",
        owner.username,
        stdout=StringIO(),
    )

    assert not Game.objects.filter(pk__in=(parent.pk, addon.pk)).exists()
