"""Round-trip test for the sentinel-removal data migration (0024, issue #290).

Runs the real migration graph both ways with MigrationExecutor:
head → 0023 (sentinels recreated by the reverse), fixture rows attached, then
forward to 0025 (sentinel FKs → NULL, sentinel rows deleted) and back again
(best-effort reverse: NULL FKs — including a pre-existing leaked NULL —
coerced onto the recreated sentinel). transaction=True is required (schema and
recorder operations cannot run inside the test's atomic wrapper), and the test
must always end at head: the django_migrations recorder is not flushed by
teardown, so leaving it mid-graph would poison the rest of the run.
"""

from datetime import timedelta

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

APP = "games"
BEFORE = (APP, "0023_alter_game_platform_alter_purchase_platform_and_more")
AFTER = (APP, "0025_game_unique_platformless_game_name_year")

PLATFORM_SENTINEL = {
    "name": "Unspecified",
    "group": "Unspecified",
    "icon": "unspecified",
}
DEVICE_SENTINEL = {"name": "Unknown", "type": "Unknown"}


def _migrate(targets):
    """Fresh executor per step: build_graph state goes stale after a migrate."""
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(targets)
    return executor.loader.project_state(targets).apps


@pytest.mark.django_db(transaction=True)
def test_sentinel_data_migration_round_trip():
    try:
        old_apps = _migrate([BEFORE])
        Game = old_apps.get_model(APP, "Game")
        Purchase = old_apps.get_model(APP, "Purchase")
        Session = old_apps.get_model(APP, "Session")
        Platform = old_apps.get_model(APP, "Platform")
        Device = old_apps.get_model(APP, "Device")

        # Unapplying 0024 already ran the reverse (get_or_create on an empty
        # DB), so the sentinels exist here.
        platform_sentinel = Platform.objects.get(**PLATFORM_SENTINEL)
        device_sentinel = Device.objects.get(**DEVICE_SENTINEL)

        sentinel_game = Game.objects.create(
            name="Sentinel Game", platform=platform_sentinel
        )
        leaked_null_game = Game.objects.create(name="Leaked Null Game", platform=None)
        purchase = Purchase.objects.create(
            date_purchased=timezone.now().date(),
            platform=platform_sentinel,
            num_purchases=1,
        )
        session = Session.objects.create(
            game=sentinel_game,
            device=device_sentinel,
            timestamp_start=timezone.now(),
            duration_manual=timedelta(0),
        )

        new_apps = _migrate([AFTER])
        Game = new_apps.get_model(APP, "Game")
        Purchase = new_apps.get_model(APP, "Purchase")
        Session = new_apps.get_model(APP, "Session")
        Platform = new_apps.get_model(APP, "Platform")
        Device = new_apps.get_model(APP, "Device")

        assert not Platform.objects.filter(**PLATFORM_SENTINEL).exists()
        assert not Device.objects.filter(**DEVICE_SENTINEL).exists()
        assert Game.objects.get(pk=sentinel_game.pk).platform_id is None
        assert Game.objects.get(pk=leaked_null_game.pk).platform_id is None
        assert Purchase.objects.get(pk=purchase.pk).platform_id is None
        assert Session.objects.get(pk=session.pk).device_id is None

        old_apps = _migrate([BEFORE])
        Game = old_apps.get_model(APP, "Game")
        Purchase = old_apps.get_model(APP, "Purchase")
        Session = old_apps.get_model(APP, "Session")
        Platform = old_apps.get_model(APP, "Platform")
        Device = old_apps.get_model(APP, "Device")

        platform_sentinel = Platform.objects.get(**PLATFORM_SENTINEL)
        device_sentinel = Device.objects.get(**DEVICE_SENTINEL)
        assert Game.objects.get(pk=sentinel_game.pk).platform_id == platform_sentinel.pk
        # Best-effort reverse: the leaked NULL is coerced too (the old save()
        # hooks enforced exactly that invariant).
        assert (
            Game.objects.get(pk=leaked_null_game.pk).platform_id == platform_sentinel.pk
        )
        assert Purchase.objects.get(pk=purchase.pk).platform_id == platform_sentinel.pk
        assert Session.objects.get(pk=session.pk).device_id == device_sentinel.pk
    finally:
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes(APP))
