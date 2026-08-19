"""The catalog's UUID becomes its primary key, and the legacy integers go.

Companion to `tests/test_catalog_identity.py`, which covers the additive half:
there the uuid column is created and backfilled, here it is promoted.
"""

import datetime
import json

import pytest
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import Client
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from games.models import Device, Game, Platform, Session

pytestmark = pytest.mark.django_db(transaction=True)

BEFORE_PROMOTION = ("games", "0012_purchase_related_game_uuid")
WITH_PROMOTION = ("games", "0013_catalog_uuid_primary_key")

# Route-shape only; never reaches the database.
GAME_ROUTE_ID = "018f5e66-e800-7000-8000-000000000001"


@pytest.fixture
def promotion_harness():
    # Migrating down to BEFORE_PROMOTION unapplies every later migration too, so
    # the restore target is the graph's leaf nodes rather than WITH_PROMOTION,
    # which would strand this worker's shared database behind head for every
    # later test that reuses it.
    leaf_nodes = MigrationExecutor(connection).loader.graph.leaf_nodes()
    executor = MigrationExecutor(connection)
    executor.migrate([BEFORE_PROMOTION])
    call_command("flush", interactive=False, verbosity=0)
    old_apps = executor.loader.project_state([BEFORE_PROMOTION]).apps
    yield old_apps
    MigrationExecutor(connection).migrate(leaf_nodes)


def migrate_to_promotion():
    executor = MigrationExecutor(connection)
    executor.migrate([WITH_PROMOTION])
    return executor.loader.project_state([WITH_PROMOTION]).apps


def seed_catalog(apps, *, username: str):
    """A library whose games sit on two platforms and none, with purchases
    linked both through the many-to-many and through related_game."""
    User = apps.get_model("auth", "User")
    UserLibrary = apps.get_model("games", "UserLibrary")
    Platform = apps.get_model("games", "Platform")
    Game = apps.get_model("games", "Game")
    Purchase = apps.get_model("games", "Purchase")
    Session = apps.get_model("games", "Session")

    user = User.objects.create(username=username)
    library = UserLibrary.objects.create(user_id=user.pk, created_at=timezone.now())
    # Re-read after every create: `uuid` carries a database default, so the
    # in-memory instance does not hold the generated value.
    first = Platform.objects.get(pk=Platform.objects.create(name="Platform 0").pk)
    second = Platform.objects.get(pk=Platform.objects.create(name="Platform 1").pk)

    # Every platform relation already resolves through Platform.uuid at this
    # point in the graph, while the many-to-many below still names Game pks.
    # year_released is set because both of Game's unique indexes include it, and
    # a NULL never collides in a unique index.
    games = [
        Game.objects.get(
            pk=Game.objects.create(
                library_id=library.pk,
                name=f"Game {suffix}",
                platform_id=platform_uuid,
                year_released=2020,
            ).pk
        )
        for suffix, platform_uuid in (
            ("A", first.uuid),
            ("B", second.uuid),
            ("C", None),
        )
    ]
    bundle = Purchase.objects.create(
        library_id=library.pk,
        platform_id=first.uuid,
        date_purchased=datetime.date(2026, 1, 1),
        price=10,
        price_currency="USD",
    )
    bundle.games.set(games[:2])
    addon = Purchase.objects.create(
        library_id=library.pk,
        platform_id=None,
        related_game_id=games[0].uuid,
        type="dlc",
        date_purchased=datetime.date(2026, 1, 2),
        price=5,
        price_currency="USD",
    )
    session = Session.objects.create(
        game_id=games[0].uuid,
        timestamp_start=timezone.now(),
    )
    return {
        "library": library,
        "platforms": [first, second],
        "games": games,
        "bundle": bundle,
        "addon": addon,
        "session": session,
    }


def catalog_links(table_name: str, column_name: str) -> set:
    with connection.cursor() as cursor:
        cursor.execute(f'SELECT {column_name} FROM "{table_name}"')
        return {row[0] for row in cursor.fetchall()}


def column_type(table_name: str, column_name: str) -> str | None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT domain_name FROM information_schema.columns
            WHERE table_name = %s AND column_name = %s
            """,
            [table_name, column_name],
        )
        row = cursor.fetchone()
    assert row is not None, f"{table_name}.{column_name} does not exist"
    return row[0]


def foreign_key_targets(table_name: str) -> dict[str, tuple[str, str]]:
    """Every foreign key on a table, as column -> (target table, target column)."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT key_usage.column_name, ccu.table_name, ccu.column_name
            FROM information_schema.table_constraints AS constraint_row
            JOIN information_schema.key_column_usage AS key_usage
                ON key_usage.constraint_name = constraint_row.constraint_name
            JOIN information_schema.constraint_column_usage AS ccu
                ON ccu.constraint_name = constraint_row.constraint_name
            WHERE constraint_row.table_name = %s
                AND constraint_row.constraint_type = 'FOREIGN KEY'
            """,
            [table_name],
        )
        return {row[0]: (row[1], row[2]) for row in cursor.fetchall()}


def unique_index_definitions(table_name: str) -> list[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT indexdef FROM pg_indexes WHERE tablename = %s", [table_name]
        )
        return [row[0] for row in cursor.fetchall() if "UNIQUE" in row[0]]


# --- Forward ------------------------------------------------------------------


def test_forward_migration_makes_the_former_uuid_the_primary_key(promotion_harness):
    seeded = seed_catalog(promotion_harness, username="promotion-forward")
    expected_games = {game.uuid for game in seeded["games"]}
    expected_platforms = {platform.uuid for platform in seeded["platforms"]}

    apps = migrate_to_promotion()

    Game = apps.get_model("games", "Game")
    Platform = apps.get_model("games", "Platform")
    assert set(Game.objects.values_list("pk", flat=True)) == expected_games
    assert set(Platform.objects.values_list("pk", flat=True)) == expected_platforms
    assert column_type("games_game", "id") == "uuid_v7"
    assert column_type("games_platform", "id") == "uuid_v7"


def test_forward_migration_preserves_every_many_to_many_link(promotion_harness):
    """By identity, not by count: a conversion that dropped the join and
    re-linked arbitrary rows would keep the count intact."""
    seeded = seed_catalog(promotion_harness, username="promotion-m2m")
    expected = {game.uuid for game in seeded["games"][:2]}

    migrate_to_promotion()

    assert catalog_links("games_purchase_games", "game_id") == expected
    assert column_type("games_purchase_games", "game_id") == "uuid_v7"


def test_forward_migration_repoints_every_catalog_foreign_key(promotion_harness):
    seed_catalog(promotion_harness, username="promotion-fks")

    migrate_to_promotion()

    assert foreign_key_targets("games_purchase_games")["game_id"] == (
        "games_game",
        "id",
    )
    assert foreign_key_targets("games_purchase")["related_game_id"] == (
        "games_game",
        "id",
    )
    assert foreign_key_targets("games_session")["game_id"] == ("games_game", "id")
    assert foreign_key_targets("games_playevent")["game_id"] == ("games_game", "id")
    assert foreign_key_targets("games_gamestatuschange")["game_id"] == (
        "games_game",
        "id",
    )
    assert foreign_key_targets("games_game")["platform_id"] == ("games_platform", "id")
    assert foreign_key_targets("games_purchase")["platform_id"] == (
        "games_platform",
        "id",
    )


def test_forward_migration_retires_the_redundant_unique_index(promotion_harness):
    """`primary_key=True` subsumes `unique=True`, so the old uuid unique index
    must not survive as a second unique index over the same column."""
    seed_catalog(promotion_harness, username="promotion-index")

    migrate_to_promotion()

    for table in ("games_game", "games_platform"):
        over_identity = [
            definition
            for definition in unique_index_definitions(table)
            if definition.endswith("(id)")
        ]
        assert len(over_identity) == 1, over_identity
        assert "_pkey" in over_identity[0] or "_pk" in over_identity[0]


def test_forward_migration_restores_the_through_tables_unique_index(promotion_harness):
    """`DROP COLUMN` cascades the (purchase, game) unique index away while
    Django's migration state still lists it, so nothing else would notice."""
    seed_catalog(promotion_harness, username="promotion-through-index")

    migrate_to_promotion()

    definitions = unique_index_definitions("games_purchase_games")
    assert any(
        "purchase_id" in definition and "game_id" in definition
        for definition in definitions
    ), definitions


# --- Reverse ------------------------------------------------------------------


def test_reverse_migration_restores_the_schema_when_the_catalog_is_empty(
    promotion_harness,
):
    migrate_to_promotion()

    MigrationExecutor(connection).migrate([BEFORE_PROMOTION])

    assert column_type("games_game", "uuid") == "uuid_v7"
    assert column_type("games_game", "id") is None
    assert column_type("games_purchase_games", "game_id") is None


def test_reverse_migration_refuses_a_populated_catalog(promotion_harness):
    """The integer identities cannot be recovered, so a populated rollback has
    to fail loudly rather than invent replacements."""
    seed_catalog(promotion_harness, username="promotion-reverse")
    migrate_to_promotion()

    with pytest.raises(RuntimeError, match="Restore from a backup"):
        MigrationExecutor(connection).migrate([BEFORE_PROMOTION])


# --- Guarantees the promotion could have lost silently ------------------------


@pytest.fixture
def library_client(db, django_user_model):
    user = django_user_model.objects.create_user(username="promoted", password="pw")
    client = Client()
    client.force_login(user)
    return client, user.library


def test_games_uniqueness_guarantees_are_still_enforced(owned_library):
    """`DROP COLUMN` cascades indexes away while Django's migration state keeps
    listing them, so both of Game's guarantees have to be asserted as *enforced*.

    Through `bulk_create`, because `Model.save()` runs `clean()`, which raises in
    Python before PostgreSQL ever sees the row. Every constrained column needs a
    non-NULL value too - a NULL never collides in a unique index.
    """
    platform = Platform.objects.create(name="Shared Platform")
    Game.objects.create(
        library=owned_library, name="Twin", platform=platform, year_released=2020
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        Game.objects.bulk_create(
            [
                Game(
                    library=owned_library,
                    name="Twin",
                    platform=platform,
                    year_released=2020,
                )
            ]
        )

    Game.objects.create(
        library=owned_library, name="Platformless", platform=None, year_released=2021
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        Game.objects.bulk_create(
            [
                Game(
                    library=owned_library,
                    name="Platformless",
                    platform=None,
                    year_released=2021,
                )
            ]
        )


def test_search_endpoints_report_each_entitys_own_identity_type(library_client):
    """Catalog values are UUID strings; Device stays integer until ID-14. Pinning
    all three keeps the mixed window honest instead of assumed."""
    client, library = library_client
    platform = Platform.objects.create(name="Search Platform")
    game = Game.objects.create(library=library, name="Searchable", platform=platform)
    device = Device.objects.create(library=library, name="Searchable Device")

    games = client.get("/api/games/search", {"q": "Search"}).json()
    assert [row["value"] for row in games] == [str(game.pk)]

    platforms = client.get("/api/platforms/search", {"q": "Search"}).json()
    assert [row["value"] for row in platforms] == [str(platform.pk)]

    devices = client.get("/api/devices/search", {"q": "Search"}).json()
    assert [row["value"] for row in devices] == [device.pk]


def test_game_bearing_endpoints_accept_the_new_identity(library_client):
    """The three non-search endpoints that typed a game id as an integer. Each
    fails independently, and none is covered by a search-endpoint test."""
    client, library = library_client
    game = Game.objects.create(library=library, name="Endpoint Game")

    assert (
        client.patch(
            f"/api/games/{game.pk}/status",
            json.dumps({"status": Game.Status.PLAYED}),
            content_type="application/json",
        ).status_code
        == 204
    )

    created = client.post(
        "/api/playevent/",
        json.dumps({"game_id": str(game.pk), "note": "played"}),
        content_type="application/json",
    )
    assert created.status_code == 201

    session = Session.objects.create(game=game, timestamp_start=timezone.now())
    detail = client.get(f"/api/session/{session.pk}").json()
    assert detail["game"]["id"] == str(game.pk)


def test_pages_that_build_filter_links_still_render(library_client):
    """`filter_to_json` is `json.dumps(to_json())`, which cannot represent a
    UUID. Game detail and stats both build catalog filter links server-side, with
    the identity as a criterion value *and* as a label key."""
    client, library = library_client
    platform = Platform.objects.create(name="Link Platform")
    game = Game.objects.create(library=library, name="Linked", platform=platform)
    Session.objects.create(game=game, timestamp_start=timezone.now())

    assert client.get(f"/tracker/game/{game.pk}/view").status_code == 200
    assert client.get("/tracker/stats/").status_code == 200


def test_a_stale_integer_filter_degrades_instead_of_crashing(library_client):
    """The shape a preset or bookmarked URL saved before this slice carries."""
    client, library = library_client
    Game.objects.create(library=library, name="Still Listed")

    response = client.get(
        "/tracker/game/list",
        {"filter": json.dumps({"platform": {"value": [7], "modifier": "INCLUDES"}})},
        follow=True,
    )

    assert response.status_code == 200
    assert b"Still Listed" in response.content


def test_catalog_routes_accept_a_uuid_and_reject_an_integer():
    assert reverse("games:view_game", args=[GAME_ROUTE_ID]).endswith(
        f"{GAME_ROUTE_ID}/view"
    )
    with pytest.raises(NoReverseMatch):
        reverse("games:view_game", args=[1])
