"""Regression coverage for the schema-only shared catalog ownership migration."""

import pytest
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

pytestmark = pytest.mark.django_db(transaction=True)

BEFORE_SHARED_CATALOG = ("games", "0020_catalog_hierarchy_backfill")
WITH_SHARED_CATALOG = ("games", "0021_alter_game_library")


@pytest.fixture
def shared_catalog_harness():
    leaf_nodes = MigrationExecutor(connection).loader.graph.leaf_nodes()
    executor = MigrationExecutor(connection)
    assert WITH_SHARED_CATALOG in executor.loader.graph.nodes, (
        "the shared catalog ownership migration is missing"
    )
    executor.migrate([BEFORE_SHARED_CATALOG])
    call_command("flush", interactive=False, verbosity=0)
    yield executor.loader.project_state([BEFORE_SHARED_CATALOG]).apps
    MigrationExecutor(connection).migrate(leaf_nodes)


def migrate_to_shared_catalog():
    executor = MigrationExecutor(connection)
    executor.migrate([WITH_SHARED_CATALOG])
    return executor.loader.project_state([WITH_SHARED_CATALOG]).apps


def _snapshot(apps):
    Game = apps.get_model("games", "Game")
    Edition = apps.get_model("games", "Edition")
    Release = apps.get_model("games", "Release")
    return {
        "games": list(Game.objects.order_by("id").values(*_concrete_fields(Game))),
        "editions": list(
            Edition.objects.order_by("id").values(*_concrete_fields(Edition))
        ),
        "releases": list(
            Release.objects.order_by("id").values(*_concrete_fields(Release))
        ),
    }


def _concrete_fields(model):
    return tuple(field.attname for field in model._meta.concrete_fields)


def test_nullable_game_owner_preserves_private_catalog_graphs_without_rewriting(
    shared_catalog_harness,
):
    """A data migration or graph merge would change this exact historic snapshot."""
    old_apps = shared_catalog_harness
    User = old_apps.get_model("auth", "User")
    UserLibrary = old_apps.get_model("games", "UserLibrary")
    Platform = old_apps.get_model("games", "Platform")
    Game = old_apps.get_model("games", "Game")
    Edition = old_apps.get_model("games", "Edition")
    Release = old_apps.get_model("games", "Release")
    user = User.objects.create(username="historic-catalog-owner")
    library = UserLibrary.objects.create(user_id=user.pk, created_at=timezone.now())
    platform = Platform.objects.create(library_id=library.pk, name="Historic platform")
    first_game = Game.objects.create(
        library_id=library.pk,
        name="Historic game",
        sort_name="Historic sort",
        year_released=1999,
        original_year_released=1998,
        original_release_date="1998",
        platform_id=platform.pk,
        wikidata="Q123",
        status="p",
        mastered=True,
    )
    second_game = Game.objects.create(library_id=library.pk, name="Second historic")
    first_edition = Edition.objects.create(game_id=first_game.pk, is_default=True)
    second_edition = Edition.objects.create(game_id=first_game.pk)
    Edition.objects.create(game_id=second_game.pk, is_default=True)
    Release.objects.create(
        edition_id=first_edition.pk,
        is_default=True,
        platform_id=platform.pk,
        release_date="1999",
    )
    Release.objects.create(edition_id=second_edition.pk, release_date="2000")
    before = _snapshot(old_apps)

    new_apps = migrate_to_shared_catalog()
    Game = new_apps.get_model("games", "Game")
    Edition = new_apps.get_model("games", "Edition")
    Release = new_apps.get_model("games", "Release")

    owner = Game._meta.get_field("library")
    assert (owner.null, owner.blank, owner.default) == (True, True, None)
    assert _snapshot(new_apps) == before

    shared_game = Game.objects.create(name="Historic game")
    shared_edition = Edition.objects.create(game_id=shared_game.pk)
    shared_release = Release.objects.create(edition_id=shared_edition.pk)

    assert shared_game.library_id is None
    assert (shared_edition.game_id, shared_release.edition_id) == (
        shared_game.pk,
        shared_edition.pk,
    )
    after_shared_graph = _snapshot(new_apps)
    before_ids = {key: {row["id"] for row in rows} for key, rows in before.items()}
    assert {
        key: [row for row in after_shared_graph[key] if row["id"] in before_ids[key]]
        for key in before
    } == before
