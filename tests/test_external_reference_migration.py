import json
import uuid
from datetime import timedelta
from importlib import import_module

import pytest
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder
from django.utils import timezone

pytestmark = pytest.mark.django_db(transaction=True)

BEFORE_EXTERNAL_REFERENCES = ("games", "0021_alter_game_library")
WITH_EXTERNAL_REFERENCES = ("games", "0022_external_references")

PRESERVED_GAME_FIELDS = (
    "library_id",
    "name",
    "sort_name",
    "original_year_released",
    "year_released",
    "original_release_date",
    "platform_id",
    "status",
    "mastered",
    "playtime",
    "created_at",
    "updated_at",
)


@pytest.fixture
def external_reference_migration_harness():
    leaf_nodes = MigrationExecutor(connection).loader.graph.leaf_nodes()
    executor = MigrationExecutor(connection)
    executor.migrate([BEFORE_EXTERNAL_REFERENCES])
    call_command("flush", interactive=False, verbosity=0)
    old_apps = executor.loader.project_state([BEFORE_EXTERNAL_REFERENCES]).apps
    yield old_apps
    call_command("flush", interactive=False, verbosity=0)
    MigrationExecutor(connection).migrate(leaf_nodes)


def migrate_to_external_references():
    executor = MigrationExecutor(connection)
    executor.migrate([WITH_EXTERNAL_REFERENCES])
    return executor.loader.project_state([WITH_EXTERNAL_REFERENCES]).apps


def seed_mixed_source_world(apps):
    User = apps.get_model("auth", "User")
    UserLibrary = apps.get_model("games", "UserLibrary")
    Platform = apps.get_model("games", "Platform")
    Game = apps.get_model("games", "Game")
    Edition = apps.get_model("games", "Edition")
    Release = apps.get_model("games", "Release")
    Session = apps.get_model("games", "Session")
    PlayEvent = apps.get_model("games", "PlayEvent")
    GameStatusChange = apps.get_model("games", "GameStatusChange")
    Purchase = apps.get_model("games", "Purchase")

    user_a = User.objects.create(username="external-reference-a")
    user_b = User.objects.create(username="external-reference-b")
    library_a = UserLibrary.objects.create(user_id=user_a.pk, created_at=timezone.now())
    library_b = UserLibrary.objects.create(user_id=user_b.pk, created_at=timezone.now())
    shared_platform = Platform.objects.create(name="Shared reference Platform")
    private_platform = Platform.objects.create(
        library_id=library_a.pk,
        name="Private reference Platform",
    )

    canonical_game = Game.objects.create(
        id=uuid.uuid7(),
        library_id=library_a.pk,
        name="Canonical",
        sort_name="Canonical, The",
        original_year_released=1999,
        year_released=2000,
        original_release_date="1999-12-31",
        platform_id=shared_platform.pk,
        wikidata="Q123",
        status="p",
        mastered=True,
        playtime=timedelta(hours=12, minutes=34),
    )
    padded_game = Game.objects.create(
        id=uuid.uuid7(),
        library_id=library_b.pk,
        name="Padded",
        sort_name="Padded",
        original_year_released=2001,
        year_released=2002,
        original_release_date="2001",
        platform_id=None,
        wikidata=" q456 ",
        status="u",
        mastered=False,
        playtime=timedelta(hours=2),
    )
    blank_game = Game.objects.create(
        id=uuid.uuid7(),
        library_id=library_a.pk,
        name="Blank",
        sort_name="Blank",
        original_year_released=None,
        year_released=None,
        original_release_date=None,
        platform_id=private_platform.pk,
        wikidata="   ",
        status="f",
        mastered=True,
        playtime=timedelta(),
    )

    canonical_default_edition = Edition.objects.create(
        game_id=canonical_game.pk,
        is_default=True,
    )
    canonical_default_release = Release.objects.create(
        edition_id=canonical_default_edition.pk,
        platform_id=shared_platform.pk,
        release_date="2000",
        is_default=True,
    )
    canonical_other_edition = Edition.objects.create(game_id=canonical_game.pk)
    canonical_other_release = Release.objects.create(
        edition_id=canonical_other_edition.pk,
        platform_id=private_platform.pk,
        release_date="2000-06",
    )
    padded_default_edition = Edition.objects.create(
        game_id=padded_game.pk,
        is_default=True,
    )
    padded_default_release = Release.objects.create(
        edition_id=padded_default_edition.pk,
        platform_id=None,
        release_date="2002",
        is_default=True,
    )
    blank_default_edition = Edition.objects.create(
        game_id=blank_game.pk,
        is_default=True,
    )
    blank_default_release = Release.objects.create(
        edition_id=blank_default_edition.pk,
        platform_id=private_platform.pk,
        release_date=None,
        is_default=True,
    )

    session = Session.objects.create(
        game_id=canonical_game.pk,
        timestamp_start=timezone.now(),
    )
    play_event = PlayEvent.objects.create(
        game_id=padded_game.pk,
        started=timezone.now().date(),
    )
    status_change = GameStatusChange.objects.create(
        game_id=blank_game.pk,
        old_status="u",
        new_status="f",
        timestamp=timezone.now(),
    )
    purchase = Purchase.objects.create(
        library_id=library_a.pk,
        date_purchased=timezone.now().date(),
        price_currency="USD",
        related_game_id=canonical_game.pk,
    )
    purchase.games.add(padded_game, blank_game)

    games = (canonical_game, padded_game, blank_game)
    editions = (
        canonical_default_edition,
        canonical_other_edition,
        padded_default_edition,
        blank_default_edition,
    )
    releases = (
        canonical_default_release,
        canonical_other_release,
        padded_default_release,
        blank_default_release,
    )
    return {
        "game_ids": tuple(game.pk for game in games),
        "canonical_game_id": canonical_game.pk,
        "padded_game_id": padded_game.pk,
        "blank_game_id": blank_game.pk,
        "preserved_games": {
            game.pk: tuple(
                getattr(Game.objects.get(pk=game.pk), field)
                for field in PRESERVED_GAME_FIELDS
            )
            for game in games
        },
        "platform_rows": (
            (shared_platform.pk, shared_platform.library_id),
            (private_platform.pk, private_platform.library_id),
        ),
        "edition_rows": tuple(
            (edition.pk, edition.game_id, edition.is_default) for edition in editions
        ),
        "release_rows": tuple(
            (
                release.pk,
                release.edition_id,
                release.platform_id,
                release.is_default,
            )
            for release in releases
        ),
        "session_row": (session.pk, session.game_id),
        "play_event_row": (play_event.pk, play_event.game_id),
        "status_change_row": (status_change.pk, status_change.game_id),
        "purchase_row": (purchase.pk, purchase.related_game_id),
        "purchase_game_rows": tuple(
            sorted(purchase.games.values_list("pk", flat=True), key=str)
        ),
    }


def test_forward_migration_maps_wikidata_to_the_same_games_exactly(
    external_reference_migration_harness,
    capsys,
):
    seeded = seed_mixed_source_world(external_reference_migration_harness)
    capsys.readouterr()

    apps = migrate_to_external_references()
    Game = apps.get_model("games", "Game")
    Platform = apps.get_model("games", "Platform")
    Edition = apps.get_model("games", "Edition")
    Release = apps.get_model("games", "Release")
    Session = apps.get_model("games", "Session")
    PlayEvent = apps.get_model("games", "PlayEvent")
    GameStatusChange = apps.get_model("games", "GameStatusChange")
    Purchase = apps.get_model("games", "Purchase")
    ExternalReference = apps.get_model("games", "ExternalReference")

    assert tuple(sorted(Game.objects.values_list("pk", flat=True), key=str)) == tuple(
        sorted(seeded["game_ids"], key=str)
    )
    for game_id, expected in seeded["preserved_games"].items():
        game = Game.objects.get(pk=game_id)
        assert (
            tuple(getattr(game, field) for field in PRESERVED_GAME_FIELDS) == expected
        )
    assert tuple(Game.objects.order_by("name").values_list("name", "wikidata")) == (
        ("Blank", ""),
        ("Canonical", "Q123"),
        ("Padded", "Q456"),
    )

    assert set(Platform.objects.values_list("pk", "library_id")) == set(
        seeded["platform_rows"]
    )
    assert set(Edition.objects.values_list("pk", "game_id", "is_default")) == set(
        seeded["edition_rows"]
    )
    assert set(
        Release.objects.values_list("pk", "edition_id", "platform_id", "is_default")
    ) == set(seeded["release_rows"])
    assert Session.objects.values_list("pk", "game_id").get() == seeded["session_row"]
    assert (
        PlayEvent.objects.values_list("pk", "game_id").get() == seeded["play_event_row"]
    )
    assert (
        GameStatusChange.objects.values_list("pk", "game_id").get()
        == seeded["status_change_row"]
    )
    assert (
        Purchase.objects.values_list("pk", "related_game_id").get()
        == seeded["purchase_row"]
    )
    assert (
        tuple(
            sorted(Purchase.objects.get().games.values_list("pk", flat=True), key=str)
        )
        == seeded["purchase_game_rows"]
    )

    assert tuple(
        ExternalReference.objects.order_by(
            "provider", "entity_kind", "provider_key", "game_id"
        ).values_list("provider", "entity_kind", "provider_key", "game_id")
    ) == (
        ("wikidata", "game", "Q123", seeded["canonical_game_id"]),
        ("wikidata", "game", "Q456", seeded["padded_game_id"]),
    )
    assert ExternalReference.objects.exclude(game_id__isnull=False).count() == 0
    assert ExternalReference.objects.filter(edition_id__isnull=False).count() == 0
    assert ExternalReference.objects.filter(release_id__isnull=False).count() == 0
    assert ExternalReference.objects.filter(platform_id__isnull=False).count() == 0

    lines = capsys.readouterr().out.splitlines()
    machine_lines = [
        line
        for line in lines
        if line.startswith("EXTERNAL_REFERENCE_RECONCILIATION_JSON=")
    ]
    assert len(machine_lines) == 1
    assert json.loads(machine_lines[0].split("=", 1)[1]) == {
        "mismatches": [],
        "schema_version": 1,
        "summary": {
            "games": 3,
            "inserted_references": 2,
            "legacy_blank": 1,
            "legacy_nonblank": 2,
            "mismatches": 0,
            "normalized_legacy_values": 2,
            "wikidata_edition_references": 0,
            "wikidata_game_references": 2,
            "wikidata_platform_references": 0,
            "wikidata_references": 2,
            "wikidata_release_references": 0,
        },
    }
    assert (
        "CAT external reference reconciliation: games=3 legacy_nonblank=2 "
        "legacy_blank=1 normalized_legacy_values=2 inserted_references=2 "
        "wikidata_references=2 wikidata_game_references=2 "
        "wikidata_edition_references=0 wikidata_release_references=0 "
        "wikidata_platform_references=0 mismatches=0"
    ) in lines


def test_preflight_reports_all_mismatches_and_rolls_back_schema_and_data(
    external_reference_migration_harness,
    capsys,
):
    apps = external_reference_migration_harness
    User = apps.get_model("auth", "User")
    UserLibrary = apps.get_model("games", "UserLibrary")
    Game = apps.get_model("games", "Game")
    user = User.objects.create(username="external-reference-preflight")
    library = UserLibrary.objects.create(user_id=user.pk, created_at=timezone.now())
    source_rows = (
        (uuid.uuid7(), "Padded duplicate", " q7 "),
        (uuid.uuid7(), "Canonical duplicate", "Q7"),
        (uuid.uuid7(), "Zero", "Q0"),
        (uuid.uuid7(), "Malformed", "not-an-id"),
    )
    for game_id, name, wikidata in source_rows:
        Game.objects.create(
            id=game_id,
            library_id=library.pk,
            name=name,
            wikidata=wikidata,
        )
    original_spellings = {
        str(game_id): wikidata for game_id, _, wikidata in source_rows
    }
    duplicate_ids = sorted(str(source_rows[index][0]) for index in (0, 1))
    malformed_rows = sorted(
        (source_rows[index] for index in (2, 3)),
        key=lambda row: str(row[0]),
    )
    expected_mismatches = [
        {
            "code": "duplicate_normalized_wikidata",
            "provider_key": "Q7",
            "game_ids": duplicate_ids,
        },
        *[
            {
                "code": "malformed_wikidata",
                "game_id": str(game_id),
                "field": "wikidata",
                "expected": "Q[1-9][0-9]* or blank",
                "actual": wikidata,
            }
            for game_id, _, wikidata in malformed_rows
        ],
    ]
    capsys.readouterr()

    with pytest.raises(
        RuntimeError,
        match=(
            r"CAT external reference reconciliation failed with "
            r"3 mismatch\(es\)\."
        ),
    ):
        MigrationExecutor(connection).migrate([WITH_EXTERNAL_REFERENCES])

    lines = capsys.readouterr().out.splitlines()
    machine_lines = [
        line
        for line in lines
        if line.startswith("EXTERNAL_REFERENCE_RECONCILIATION_JSON=")
    ]
    assert len(machine_lines) == 1
    assert json.loads(machine_lines[0].split("=", 1)[1]) == {
        "mismatches": expected_mismatches,
        "schema_version": 1,
        "summary": {
            "games": 4,
            "inserted_references": 0,
            "legacy_blank": 0,
            "legacy_nonblank": 4,
            "mismatches": 3,
            "normalized_legacy_values": 2,
            "wikidata_edition_references": 0,
            "wikidata_game_references": 0,
            "wikidata_platform_references": 0,
            "wikidata_references": 0,
            "wikidata_release_references": 0,
        },
    }
    assert (
        "CAT external reference reconciliation: games=4 legacy_nonblank=4 "
        "legacy_blank=0 normalized_legacy_values=2 inserted_references=0 "
        "wikidata_references=0 wikidata_game_references=0 "
        "wikidata_edition_references=0 wikidata_release_references=0 "
        "wikidata_platform_references=0 mismatches=3"
    ) in lines
    assert (
        "CAT external reference mismatch: "
        "code=duplicate_normalized_wikidata "
        f"game_ids={json.dumps(duplicate_ids, separators=(',', ':'))} "
        "provider_key=Q7"
    ) in lines
    for game_id, _, wikidata in malformed_rows:
        assert (
            "CAT external reference mismatch: code=malformed_wikidata "
            f"actual={wikidata} expected=Q[1-9][0-9]* or blank "
            f"field=wikidata game_id={game_id}"
        ) in lines

    executor = MigrationExecutor(connection)
    assert (
        WITH_EXTERNAL_REFERENCES
        not in MigrationRecorder(connection).applied_migrations()
    )
    restored_apps = executor.loader.project_state([BEFORE_EXTERNAL_REFERENCES]).apps
    RestoredGame = restored_apps.get_model("games", "Game")
    assert {
        str(game_id): wikidata
        for game_id, wikidata in RestoredGame.objects.values_list("pk", "wikidata")
    } == original_spellings
    assert "games_externalreference" not in connection.introspection.table_names()


def test_postwrite_reconciliation_failure_rolls_back_schema_and_data(
    external_reference_migration_harness,
    capsys,
    monkeypatch,
):
    apps = external_reference_migration_harness
    User = apps.get_model("auth", "User")
    UserLibrary = apps.get_model("games", "UserLibrary")
    Game = apps.get_model("games", "Game")
    user = User.objects.create(username="external-reference-postwrite")
    library = UserLibrary.objects.create(user_id=user.pk, created_at=timezone.now())
    game = Game.objects.create(
        id=uuid.uuid7(),
        library_id=library.pk,
        name="Post-write rollback",
        wikidata=" q123 ",
    )
    forced_mismatch = {
        "code": "forced_postwrite_mismatch",
        "game_id": str(game.pk),
        "expected": "Q123",
        "actual": None,
    }
    migration = import_module("games.migrations.0022_external_references")
    capsys.readouterr()

    with monkeypatch.context() as patch:
        patch.setattr(
            migration,
            "_result_mismatches",
            lambda *args, **kwargs: [forced_mismatch],
        )
        with pytest.raises(
            RuntimeError,
            match=(
                r"CAT external reference reconciliation failed with "
                r"1 mismatch\(es\)\."
            ),
        ):
            MigrationExecutor(connection).migrate([WITH_EXTERNAL_REFERENCES])

    lines = capsys.readouterr().out.splitlines()
    machine_line = next(
        line
        for line in lines
        if line.startswith("EXTERNAL_REFERENCE_RECONCILIATION_JSON=")
    )
    assert json.loads(machine_line.split("=", 1)[1]) == {
        "mismatches": [forced_mismatch],
        "schema_version": 1,
        "summary": {
            "games": 1,
            "inserted_references": 1,
            "legacy_blank": 0,
            "legacy_nonblank": 1,
            "mismatches": 1,
            "normalized_legacy_values": 1,
            "wikidata_edition_references": 0,
            "wikidata_game_references": 1,
            "wikidata_platform_references": 0,
            "wikidata_references": 1,
            "wikidata_release_references": 0,
        },
    }
    assert (
        "CAT external reference reconciliation: games=1 legacy_nonblank=1 "
        "legacy_blank=0 normalized_legacy_values=1 inserted_references=1 "
        "wikidata_references=1 wikidata_game_references=1 "
        "wikidata_edition_references=0 wikidata_release_references=0 "
        "wikidata_platform_references=0 mismatches=1"
    ) in lines
    assert (
        "CAT external reference mismatch: code=forced_postwrite_mismatch "
        f"actual=null expected=Q123 game_id={game.pk}"
    ) in lines

    executor = MigrationExecutor(connection)
    assert (
        WITH_EXTERNAL_REFERENCES
        not in MigrationRecorder(connection).applied_migrations()
    )
    restored_apps = executor.loader.project_state([BEFORE_EXTERNAL_REFERENCES]).apps
    RestoredGame = restored_apps.get_model("games", "Game")
    assert RestoredGame.objects.get(pk=game.pk).wikidata == " q123 "
    assert "games_externalreference" not in connection.introspection.table_names()


def test_forward_function_is_idempotent_and_preserves_reference_uuids(
    external_reference_migration_harness,
    capsys,
):
    seed_mixed_source_world(external_reference_migration_harness)
    apps = migrate_to_external_references()
    ExternalReference = apps.get_model("games", "ExternalReference")
    before_rows = tuple(
        ExternalReference.objects.order_by("provider_key").values_list(
            "pk",
            "provider",
            "entity_kind",
            "provider_key",
            "game_id",
        )
    )
    capsys.readouterr()

    migration = import_module("games.migrations.0022_external_references")
    migration.backfill_external_references(apps, None)

    assert (
        tuple(
            ExternalReference.objects.order_by("provider_key").values_list(
                "pk",
                "provider",
                "entity_kind",
                "provider_key",
                "game_id",
            )
        )
        == before_rows
    )
    lines = capsys.readouterr().out.splitlines()
    machine_lines = [
        line
        for line in lines
        if line.startswith("EXTERNAL_REFERENCE_RECONCILIATION_JSON=")
    ]
    assert len(machine_lines) == 1
    assert json.loads(machine_lines[0].split("=", 1)[1]) == {
        "mismatches": [],
        "schema_version": 1,
        "summary": {
            "games": 3,
            "inserted_references": 0,
            "legacy_blank": 1,
            "legacy_nonblank": 2,
            "mismatches": 0,
            "normalized_legacy_values": 0,
            "wikidata_edition_references": 0,
            "wikidata_game_references": 2,
            "wikidata_platform_references": 0,
            "wikidata_references": 2,
            "wikidata_release_references": 0,
        },
    }
    assert (
        "CAT external reference reconciliation: games=3 legacy_nonblank=2 "
        "legacy_blank=1 normalized_legacy_values=0 inserted_references=0 "
        "wikidata_references=2 wikidata_game_references=2 "
        "wikidata_edition_references=0 wikidata_release_references=0 "
        "wikidata_platform_references=0 mismatches=0"
    ) in lines


def test_empty_database_emits_exact_zero_report(
    external_reference_migration_harness,
    capsys,
):
    capsys.readouterr()

    apps = migrate_to_external_references()

    ExternalReference = apps.get_model("games", "ExternalReference")
    assert ExternalReference.objects.count() == 0
    lines = capsys.readouterr().out.splitlines()
    machine_lines = [
        line
        for line in lines
        if line.startswith("EXTERNAL_REFERENCE_RECONCILIATION_JSON=")
    ]
    assert len(machine_lines) == 1
    assert machine_lines[0] == (
        "EXTERNAL_REFERENCE_RECONCILIATION_JSON="
        '{"mismatches":[],"schema_version":1,"summary":'
        '{"games":0,"inserted_references":0,"legacy_blank":0,'
        '"legacy_nonblank":0,"mismatches":0,"normalized_legacy_values":0,'
        '"wikidata_edition_references":0,"wikidata_game_references":0,'
        '"wikidata_platform_references":0,"wikidata_references":0,'
        '"wikidata_release_references":0}}'
    )
    assert (
        "CAT external reference reconciliation: games=0 legacy_nonblank=0 "
        "legacy_blank=0 normalized_legacy_values=0 inserted_references=0 "
        "wikidata_references=0 wikidata_game_references=0 "
        "wikidata_edition_references=0 wikidata_release_references=0 "
        "wikidata_platform_references=0 mismatches=0"
    ) in lines


def test_reverse_refuses_before_deleting_a_populated_reference_table(
    external_reference_migration_harness,
):
    seeded = seed_mixed_source_world(external_reference_migration_harness)
    apps = migrate_to_external_references()
    ExternalReference = apps.get_model("games", "ExternalReference")
    before_rows = tuple(
        ExternalReference.objects.order_by("provider_key").values_list(
            "pk", "provider_key", "game_id"
        )
    )

    with pytest.raises(
        RuntimeError,
        match=r"Cannot reverse external references while reference rows exist\.",
    ):
        MigrationExecutor(connection).migrate([BEFORE_EXTERNAL_REFERENCES])

    assert (
        WITH_EXTERNAL_REFERENCES in MigrationRecorder(connection).applied_migrations()
    )
    executor = MigrationExecutor(connection)
    preserved_apps = executor.loader.project_state([WITH_EXTERNAL_REFERENCES]).apps
    PreservedGame = preserved_apps.get_model("games", "Game")
    PreservedReference = preserved_apps.get_model("games", "ExternalReference")
    assert set(PreservedGame.objects.values_list("pk", flat=True)) == set(
        seeded["game_ids"]
    )
    assert (
        tuple(
            PreservedReference.objects.order_by("provider_key").values_list(
                "pk", "provider_key", "game_id"
            )
        )
        == before_rows
    )
    assert "games_externalreference" in connection.introspection.table_names()


def test_empty_reference_table_can_reverse_and_migrate_forward_again(
    external_reference_migration_harness,
    capsys,
):
    apps = migrate_to_external_references()
    ExternalReference = apps.get_model("games", "ExternalReference")
    assert ExternalReference.objects.count() == 0
    assert "games_externalreference" in connection.introspection.table_names()

    executor = MigrationExecutor(connection)
    executor.migrate([BEFORE_EXTERNAL_REFERENCES])

    assert (
        WITH_EXTERNAL_REFERENCES
        not in MigrationRecorder(connection).applied_migrations()
    )
    assert "games_externalreference" not in connection.introspection.table_names()

    capsys.readouterr()
    apps = migrate_to_external_references()
    ExternalReference = apps.get_model("games", "ExternalReference")
    assert ExternalReference.objects.count() == 0
    assert (
        WITH_EXTERNAL_REFERENCES in MigrationRecorder(connection).applied_migrations()
    )
    assert "games_externalreference" in connection.introspection.table_names()
    machine_lines = [
        line
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("EXTERNAL_REFERENCE_RECONCILIATION_JSON=")
    ]
    assert len(machine_lines) == 1
    assert json.loads(machine_lines[0].split("=", 1)[1])["summary"] == {
        "games": 0,
        "inserted_references": 0,
        "legacy_blank": 0,
        "legacy_nonblank": 0,
        "mismatches": 0,
        "normalized_legacy_values": 0,
        "wikidata_edition_references": 0,
        "wikidata_game_references": 0,
        "wikidata_platform_references": 0,
        "wikidata_references": 0,
        "wikidata_release_references": 0,
    }
