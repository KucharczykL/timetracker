"""Migration 0049 refuses to run if either legacy table still holds a row."""

import importlib

import pytest
from django.apps import apps as global_apps
from django.db import connection

guard_module = importlib.import_module("games.migrations.0049_guard_legacy_tables_empty")


@pytest.mark.django_db
def test_guard_passes_on_empty_tables():
    guard_module.guard_legacy_tables_empty(global_apps, connection.schema_editor())


@pytest.mark.django_db
def test_guard_raises_when_playevent_holds_a_row(django_user_model):
    from games.models import Game, PlayEvent, UserLibrary

    user = django_user_model.objects.create_user(username="guard-test")
    library = UserLibrary.objects.get(user=user)
    game = Game.objects.create(library=library, name="Guarded")
    PlayEvent.objects.create(game=game)

    with pytest.raises(RuntimeError, match="PlayEvent"):
        guard_module.guard_legacy_tables_empty(global_apps, connection.schema_editor())


@pytest.mark.django_db
def test_guard_raises_when_gamestatuschange_holds_a_row(django_user_model):
    from games.models import Game, GameStatusChange, UserLibrary

    user = django_user_model.objects.create_user(username="guard-test-2")
    library = UserLibrary.objects.get(user=user)
    game = Game.objects.create(library=library, name="Guarded 2")
    GameStatusChange.objects.create(game=game, new_status=Game.Status.UNPLAYED)

    with pytest.raises(RuntimeError, match="GameStatusChange"):
        guard_module.guard_legacy_tables_empty(global_apps, connection.schema_editor())
