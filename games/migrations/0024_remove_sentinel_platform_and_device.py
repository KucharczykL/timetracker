# Remove the sentinel "Unspecified" Platform and "Unknown" Device (issue #290):
# NULL becomes the single representation of "not set". Sentinels are matched by
# their exact creation attributes, so a sentinel a user has since edited is
# treated as a real user row and left alone:
#
# - Platform: the exact triple get_sentinel_platform() used to get_or_create
#   (name="Unspecified", group="Unspecified", icon="unspecified"). A sentinel
#   whose group/icon was edited survives with its games/purchases intact.
# - Device: name="Unknown" AND type="Unknown". Session.save() historically
#   matched by type only, so a *renamed* Unknown-type device may have served as
#   the de-facto sentinel — it won't match here and keeps its sessions
#   (conservative: it is arguably a real user device). Conversely, Device.type
#   *defaults* to "Unknown", so a genuine user device named "Unknown" with the
#   default type is byte-identical to the sentinel and is removed with it.
#
# The reverse is best-effort, not exact: rows that were legitimately NULL before
# this migration are also coerced onto the recreated sentinel (the old save()
# hooks enforced exactly that invariant anyway), and when a renamed Unknown-type
# device exists, reversing mints a second type-Unknown device.

from django.db import migrations

PLATFORM_SENTINEL = {
    "name": "Unspecified",
    "group": "Unspecified",
    "icon": "unspecified",
}
DEVICE_SENTINEL = {"name": "Unknown", "type": "Unknown"}


def remove_sentinels(apps, schema_editor):
    database = schema_editor.connection.alias
    Game = apps.get_model("games", "Game")
    Purchase = apps.get_model("games", "Purchase")
    Session = apps.get_model("games", "Session")
    Platform = apps.get_model("games", "Platform")
    Device = apps.get_model("games", "Device")

    # .filter(...) + iterate rather than .get(): robust against accidental
    # duplicate sentinel rows, and a clean no-op on fresh databases.
    for sentinel in Platform.objects.using(database).filter(**PLATFORM_SENTINEL):
        Game.objects.using(database).filter(platform=sentinel).update(platform=None)
        Purchase.objects.using(database).filter(platform=sentinel).update(platform=None)
        sentinel.delete()

    for sentinel in Device.objects.using(database).filter(**DEVICE_SENTINEL):
        Session.objects.using(database).filter(device=sentinel).update(device=None)
        sentinel.delete()

    # The conservative skip above is invisible to the operator: an edited
    # near-sentinel survives as a second representation of "not set" with no
    # signal to review it. Print a one-line notice per survivor kind.
    skipped_platforms = (
        Platform.objects.using(database)
        .filter(name=PLATFORM_SENTINEL["name"])
        .exclude(**PLATFORM_SENTINEL)
        .count()
    )
    if skipped_platforms:
        print(
            f"\n  games.0024: kept {skipped_platforms} edited platform(s) named "
            f'"{PLATFORM_SENTINEL["name"]}" (treated as real user rows) — '
            "review whether they still mean 'not set'."
        )
    skipped_devices = (
        Device.objects.using(database)
        .filter(type=DEVICE_SENTINEL["type"])
        .exclude(**DEVICE_SENTINEL)
        .count()
    )
    if skipped_devices:
        print(
            f"\n  games.0024: kept {skipped_devices} renamed device(s) of type "
            f'"{DEVICE_SENTINEL["type"]}" (treated as real user rows) — '
            "review whether they still mean 'not set'."
        )


def restore_sentinels(apps, schema_editor):
    database = schema_editor.connection.alias
    Game = apps.get_model("games", "Game")
    Purchase = apps.get_model("games", "Purchase")
    Session = apps.get_model("games", "Session")
    Platform = apps.get_model("games", "Platform")
    Device = apps.get_model("games", "Device")

    # icon is passed explicitly: historical models don't run Platform.save()'s
    # slugify default.
    platform_sentinel, _ = Platform.objects.using(database).get_or_create(
        **PLATFORM_SENTINEL
    )
    Game.objects.using(database).filter(platform__isnull=True).update(
        platform=platform_sentinel
    )
    Purchase.objects.using(database).filter(platform__isnull=True).update(
        platform=platform_sentinel
    )

    device_sentinel, _ = Device.objects.using(database).get_or_create(**DEVICE_SENTINEL)
    Session.objects.using(database).filter(device__isnull=True).update(
        device=device_sentinel
    )


class Migration(migrations.Migration):
    dependencies = [
        ("games", "0023_alter_game_platform_alter_purchase_platform_and_more"),
    ]

    operations = [
        migrations.RunPython(remove_sentinels, restore_sentinels),
    ]
