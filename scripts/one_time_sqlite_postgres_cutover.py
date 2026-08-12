from __future__ import annotations

import dataclasses
import hashlib
import json
import shutil
import subprocess
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from django.apps import apps
from django.core import serializers
from django.core.management import call_command
from django.core.management.color import no_style
from django.db import connections, transaction
from django.db.migrations.loader import MigrationLoader
from django.db.models import Count, Model
from django.db.models.signals import m2m_changed
from django.test import Client
from django.urls import reverse

if TYPE_CHECKING:
    from django.db.backends.base.base import BaseDatabaseWrapper


class CutoverError(RuntimeError):
    pass


@dataclasses.dataclass(frozen=True)
class SourceContract:
    migrations: tuple[tuple[str, str], ...]
    table_columns: dict[str, tuple[str, ...]]
    table_dispositions: dict[str, str]
    required_empty_tables: tuple[str, ...]
    schedule: dict[str, str]


@dataclasses.dataclass(frozen=True)
class SourceStructure:
    migrations: tuple[tuple[str, str], ...]
    table_columns: dict[str, tuple[str, ...]]


@dataclasses.dataclass(frozen=True)
class SnapshotFiles:
    archive: Path
    database: Path
    wal: Path | None
    shm: Path | None
    journal: Path | None
    archive_sha256: str
    durable_member_sha256: dict[str, str]


@dataclasses.dataclass(frozen=True)
class SourceEvidence:
    structure: SourceStructure
    table_counts: dict[str, int]
    quick_check: str
    effective_squash_applied: bool


@dataclasses.dataclass(frozen=True)
class PreparedSource:
    snapshot: SnapshotFiles
    evidence: SourceEvidence
    connection: BaseDatabaseWrapper


SOURCE_ALIAS = "sqlite_source"
SQUASH_MIGRATION = (
    "games",
    "0001_squashed_0036_alter_playevent_days_to_finish",
)
SNAPSHOT_MEMBERS = {
    "db.sqlite3",
    "db.sqlite3-wal",
    "db.sqlite3-shm",
    "db.sqlite3-journal",
}
DURABLE_SNAPSHOT_MEMBERS = {
    "db.sqlite3",
    "db.sqlite3-wal",
    "db.sqlite3-journal",
}
TRANSFER_MODEL_LABELS = (
    "auth.user",
    "games.platform",
    "games.device",
    "games.game",
    "games.exchangerate",
    "games.gamestatuschange",
    "games.playevent",
    "games.purchase",
    "games.session",
    "games.filterpreset",
    "games.sitesetting",
    "games.userpreferences",
)
TRANSFER_CLEAR_ORDER = (
    "games_userpreferences",
    "games_sitesetting",
    "games_filterpreset",
    "games_session",
    "games_purchase_games",
    "games_purchase",
    "games_playevent",
    "games_gamestatuschange",
    "games_game",
    "games_exchangerate",
    "games_device",
    "games_platform",
    "auth_user",
)
MIGRATED_TARGET_TABLES = {
    "django_migrations",
    "django_content_type",
    "auth_permission",
    "games_exchangerate",
}


@dataclasses.dataclass(frozen=True)
class FixtureEvidence:
    path: Path
    sha256: str
    model_counts: dict[str, int]


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_git_ignored_workspace(workspace: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["git", "check-ignore", "--quiet", "--no-index", str(workspace.resolve())],
        cwd=repository,
        check=False,
    )
    if result.returncode != 0:
        raise CutoverError(f"workspace must be Git-ignored: {workspace}")


def _safe_snapshot_destination(workspace: Path, member: zipfile.ZipInfo) -> Path:
    member_path = Path(member.filename)
    if (
        member.is_dir()
        or member_path.is_absolute()
        or len(member_path.parts) != 1
        or member_path.parts[0] in {".", ".."}
    ):
        raise CutoverError(f"unsafe archive member: {member.filename}")
    destination = (workspace / member_path).resolve()
    if not destination.is_relative_to(workspace.resolve()):
        raise CutoverError(f"unsafe archive member: {member.filename}")
    return destination


def extract_snapshot(archive: Path, workspace: Path) -> SnapshotFiles:
    archive = archive.resolve()
    workspace = workspace.resolve()
    require_git_ignored_workspace(workspace)
    if workspace.exists() and any(workspace.iterdir()):
        raise CutoverError(f"workspace must be empty: {workspace}")
    workspace.mkdir(parents=True, exist_ok=True)

    extracted: dict[str, Path] = {}
    with zipfile.ZipFile(archive) as source:
        for member in source.infolist():
            destination = _safe_snapshot_destination(workspace, member)
            name = member.filename
            if name not in SNAPSHOT_MEMBERS:
                raise CutoverError(f"unexpected archive member: {name}")
            if name in extracted:
                raise CutoverError(f"duplicate archive member: {name}")
            with (
                source.open(member) as input_file,
                destination.open("xb") as output_file,
            ):
                shutil.copyfileobj(input_file, output_file)
            extracted[name] = destination

    if "db.sqlite3" not in extracted:
        raise CutoverError("archive is missing db.sqlite3")
    durable_hashes = {
        name: sha256_file(path)
        for name, path in extracted.items()
        if name in DURABLE_SNAPSHOT_MEMBERS
    }
    return SnapshotFiles(
        archive=archive,
        database=extracted["db.sqlite3"],
        wal=extracted.get("db.sqlite3-wal"),
        shm=extracted.get("db.sqlite3-shm"),
        journal=extracted.get("db.sqlite3-journal"),
        archive_sha256=sha256_file(archive),
        durable_member_sha256=durable_hashes,
    )


def sqlite_read_only_uri(database: Path) -> str:
    path = quote(database.resolve().as_posix(), safe="/:")
    return f"file:{path}?mode=ro"


def configure_source_alias(database: Path) -> BaseDatabaseWrapper:
    connections.databases[SOURCE_ALIAS] = {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": sqlite_read_only_uri(database),
        "ATOMIC_REQUESTS": False,
        "AUTOCOMMIT": True,
        "CONN_MAX_AGE": 0,
        "CONN_HEALTH_CHECKS": False,
        "OPTIONS": {},
        "TIME_ZONE": None,
        "USER": "",
        "PASSWORD": "",
        "HOST": "",
        "PORT": "",
        "TEST": {
            "CHARSET": None,
            "COLLATION": None,
            "MIGRATE": True,
            "MIRROR": None,
            "NAME": None,
        },
    }
    return connections[SOURCE_ALIAS]


def remove_source_alias(connection: BaseDatabaseWrapper) -> None:
    connection.close()
    del connections[SOURCE_ALIAS]
    del connections.databases[SOURCE_ALIAS]


def load_source_contract(path: Path) -> SourceContract:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return SourceContract(
        migrations=tuple(tuple(item) for item in raw["migrations"]),
        table_columns={
            key: tuple(value) for key, value in raw["table_columns"].items()
        },
        table_dispositions=dict(raw["table_dispositions"]),
        required_empty_tables=tuple(raw["required_empty_tables"]),
        schedule=dict(raw["schedule"]),
    )


def source_structure(connection: BaseDatabaseWrapper) -> SourceStructure:
    with connection.cursor() as cursor:
        cursor.execute("SELECT app, name FROM django_migrations ORDER BY app, name")
        migrations = tuple(tuple(row) for row in cursor.fetchall())
        tables = sorted(connection.introspection.table_names(cursor))
        table_columns: dict[str, tuple[str, ...]] = {}
        for table in tables:
            cursor.execute(f"PRAGMA table_info({connection.ops.quote_name(table)})")
            table_columns[table] = tuple(str(row[1]) for row in cursor.fetchall())
    return SourceStructure(migrations=migrations, table_columns=table_columns)


def source_table_counts(
    connection: BaseDatabaseWrapper, tables: set[str]
) -> dict[str, int]:
    counts: dict[str, int] = {}
    with connection.cursor() as cursor:
        for table in sorted(tables):
            cursor.execute(f"SELECT COUNT(*) FROM {connection.ops.quote_name(table)}")
            row = cursor.fetchone()
            if row is None:
                raise CutoverError(f"could not count source table: {table}")
            counts[table] = int(row[0])
    return counts


def transfer_models() -> tuple[type[Model], ...]:
    models: list[type[Model]] = []
    for label in TRANSFER_MODEL_LABELS:
        model = apps.get_model(label)
        if model is None:
            raise CutoverError(f"unknown transfer model: {label}")
        models.append(model)
    return tuple(models)


def validate_required_empty_tables(
    connection: BaseDatabaseWrapper, contract: SourceContract
) -> None:
    counts = source_table_counts(connection, set(contract.required_empty_tables))
    nonempty = {table: count for table, count in counts.items() if count}
    if nonempty:
        details = ", ".join(
            f"{table}={count}" for table, count in sorted(nonempty.items())
        )
        raise CutoverError(f"required-empty source tables contain rows: {details}")


def purchase_count_mismatches(alias: str) -> list[tuple[int, int, int]]:
    purchase = apps.get_model("games.purchase")
    return [
        (pk, stored, links)
        for pk, stored, links in purchase._base_manager.using(alias)
        .annotate(link_count=Count("games"))
        .values_list("pk", "num_purchases", "link_count")
        if stored != links
    ]


def validate_purchase_link_counts(alias: str) -> None:
    mismatches = purchase_count_mismatches(alias)
    if mismatches:
        details = ", ".join(
            f"Purchase {pk}: stored={stored}, links={links}"
            for pk, stored, links in mismatches
        )
        raise CutoverError(f"purchase link-count mismatch: {details}")


def strip_generated_fields(record: dict[str, Any]) -> dict[str, Any]:
    model = apps.get_model(record["model"])
    if model is None:
        raise CutoverError(f"unknown fixture model: {record['model']}")
    generated_names = {
        field.name for field in model._meta.concrete_fields if field.generated
    }
    fields = dict(record["fields"])
    for name in generated_names:
        fields.pop(name, None)
    return {**record, "fields": fields}


def write_transfer_fixture(alias: str, path: Path) -> FixtureEvidence:
    records: list[dict[str, Any]] = []
    model_counts: dict[str, int] = {}
    for model in transfer_models():
        label = model._meta.label_lower
        queryset = model._base_manager.using(alias).order_by(model._meta.pk.attname)
        serialized = serializers.serialize("json", queryset)
        model_records = [
            strip_generated_fields(record) for record in json.loads(serialized)
        ]
        records.extend(model_records)
        model_counts[label] = len(model_records)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return FixtureEvidence(
        path=path,
        sha256=sha256_file(path),
        model_counts=model_counts,
    )


def target_table_names(connection: BaseDatabaseWrapper) -> list[str]:
    with connection.cursor() as cursor:
        return sorted(connection.introspection.table_names(cursor))


def require_initially_empty_target(connection: BaseDatabaseWrapper) -> None:
    tables = target_table_names(connection)
    if tables:
        raise CutoverError("target database is not empty: " + ", ".join(tables))


def migrate_target() -> None:
    call_command("migrate", database="default", interactive=False, verbosity=1)
    tables = set(target_table_names(connections["default"]))
    missing = sorted(MIGRATED_TARGET_TABLES - tables)
    if missing:
        raise CutoverError("migrated target is missing tables: " + ", ".join(missing))


def clear_transfer_targets(
    connection: BaseDatabaseWrapper, models: tuple[type[Model], ...]
) -> None:
    expected = {model._meta.db_table for model in models}
    purchase = apps.get_model("games.purchase")
    expected.add(purchase.games.through._meta.db_table)
    if expected != set(TRANSFER_CLEAR_ORDER):
        raise CutoverError("transfer clear order does not match the transfer models")
    with transaction.atomic(using="default"), connection.cursor() as cursor:
        for table in TRANSFER_CLEAR_ORDER:
            cursor.execute(f"DELETE FROM {connection.ops.quote_name(table)}")
        connection.check_constraints()


def load_transfer_fixture(fixture_path: Path) -> None:
    from games.models import Purchase
    from games.signals import update_num_purchases

    disconnected = m2m_changed.disconnect(
        update_num_purchases,
        sender=Purchase.games.through,
    )
    if not disconnected:
        raise CutoverError("Purchase M2M receiver was not connected before load")
    connection = connections["default"]
    try:
        with (
            transaction.atomic(using="default"),
            connection.constraint_checks_disabled(),
            fixture_path.open(encoding="utf-8") as fixture,
        ):
            for deserialized in serializers.deserialize(
                "json", fixture, using="default"
            ):
                deserialized.save(save_m2m=True, using="default")
            connection.check_constraints()
    finally:
        m2m_changed.connect(
            update_num_purchases,
            sender=Purchase.games.through,
        )


def reset_transfer_sequences(
    connection: BaseDatabaseWrapper, models: tuple[type[Model], ...]
) -> None:
    purchase = apps.get_model("games.purchase")
    sql = connection.ops.sequence_reset_sql(
        no_style(), [*models, purchase.games.through]
    )
    if not sql:
        return
    with connection.cursor() as cursor:
        for statement in sql:
            cursor.execute(statement)


def recreate_schedule(contract: SourceContract) -> dict[str, str]:
    schedule_model = apps.get_model("django_q.schedule")
    call_command("schedule_convert_prices")
    schedules = list(
        schedule_model._base_manager.filter(name=contract.schedule["name"]).values(
            "name", "func"
        )
    )
    if schedules != [contract.schedule]:
        raise CutoverError(
            f"scheduled task does not exactly match the source contract: {schedules!r}"
        )
    return schedules[0]


def normalize(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return {"float": value.hex()}
    if isinstance(value, Decimal):
        return {"decimal": format(value, "f")}
    if isinstance(value, datetime):
        return {"datetime": value.astimezone(UTC).isoformat()}
    if isinstance(value, date):
        return {"date": value.isoformat()}
    if isinstance(value, timedelta):
        return {"microseconds": value // timedelta(microseconds=1)}
    if isinstance(value, dict):
        return {key: normalize(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [normalize(item) for item in value]
    raise TypeError(f"Unsupported cutover value type: {type(value).__name__}")


def _canonical_model_records(
    model: type[Model], alias: str, *, exclude_generated: bool
) -> list[dict[str, Any]]:
    fields = sorted(
        (
            field
            for field in model._meta.concrete_fields
            if not exclude_generated or not field.generated
        ),
        key=lambda field: field.name,
    )
    m2m_fields = sorted(model._meta.local_many_to_many, key=lambda field: field.name)
    records: list[dict[str, Any]] = []
    for instance in model._base_manager.using(alias).order_by(model._meta.pk.attname):
        values = {
            field.name: normalize(getattr(instance, field.attname)) for field in fields
        }
        for field in m2m_fields:
            values[field.name] = sorted(
                getattr(instance, field.name)
                .using(alias)
                .values_list(field.remote_field.model._meta.pk.attname, flat=True)
            )
        records.append({"pk": normalize(instance.pk), "fields": values})
    return records


def model_digest(
    model: type[Model], alias: str, *, exclude_generated: bool = True
) -> str:
    return canonical_sha256(
        _canonical_model_records(model, alias, exclude_generated=exclude_generated)
    )


def generated_values(alias: str) -> dict[str, dict[int, Any]]:
    results: dict[str, dict[int, Any]] = {}
    for model in transfer_models():
        generated = sorted(
            (field for field in model._meta.concrete_fields if field.generated),
            key=lambda field: field.name,
        )
        for field in generated:
            key = f"{model._meta.label}.{field.name}"
            results[key] = {
                pk: normalize(value)
                for pk, value in model._base_manager.using(alias)
                .order_by(model._meta.pk.attname)
                .values_list(model._meta.pk.attname, field.attname)
            }
    return results


def reconcile_models(
    source_alias: str, target_alias: str
) -> tuple[dict[str, str], dict[str, dict[str, object]]]:
    mismatches: list[str] = []
    digests: dict[str, str] = {}
    for model in transfer_models():
        label = model._meta.label_lower
        source_digest = model_digest(model, source_alias)
        target_digest = model_digest(model, target_alias)
        digests[label] = target_digest
        if source_digest != target_digest:
            mismatches.append(f"{label}: nongenerated records differ")
    source_generated = generated_values(source_alias)
    target_generated = generated_values(target_alias)
    generated_results: dict[str, dict[str, object]] = {}
    for key in sorted(set(source_generated) | set(target_generated)):
        source = source_generated.get(key, {})
        target = target_generated.get(key, {})
        differing_pks = sorted(
            pk for pk in set(source) | set(target) if source.get(pk) != target.get(pk)
        )
        generated_results[key] = {"count": len(target), "match": not differing_pks}
        if differing_pks:
            mismatches.append(f"{key}: differing PKs {differing_pks}")
    if mismatches:
        raise CutoverError("reconciliation failed:\n- " + "\n- ".join(mismatches))
    return digests, generated_results


def aggregate_evidence(alias: str) -> dict[str, object]:
    from django.db.models import Sum

    game = apps.get_model("games.game")
    purchase = apps.get_model("games.purchase")
    session = apps.get_model("games.session")
    status_change = apps.get_model("games.gamestatuschange")
    user = apps.get_model("auth.user")
    filter_preset = apps.get_model("games.filterpreset")
    site_setting = apps.get_model("games.sitesetting")
    duration_sums = session._base_manager.using(alias).aggregate(
        calculated=Sum("duration_calculated"),
        manual=Sum("duration_manual"),
        total=Sum("duration_total"),
    )
    purchase_sums = purchase._base_manager.using(alias).aggregate(
        price=Sum("price"), converted_price=Sum("converted_price")
    )
    return normalize(
        {
            "session_count": session._base_manager.using(alias).count(),
            "session_duration_sums": duration_sums,
            "game_playtime_digest": model_digest(game, alias),
            "purchase_count": purchase._base_manager.using(alias).count(),
            "purchase_sums": purchase_sums,
            "purchase_link_count": purchase.games.through._base_manager.using(
                alias
            ).count(),
            "status_history_count": status_change._base_manager.using(alias).count(),
            "user_count": user._base_manager.using(alias).count(),
            "filter_preset_count": filter_preset._base_manager.using(alias).count(),
            "site_setting_count": site_setting._base_manager.using(alias).count(),
        }
    )


def sequence_evidence(
    connection: BaseDatabaseWrapper, models: tuple[type[Model], ...]
) -> dict[str, object]:
    purchase = apps.get_model("games.purchase")
    results: dict[str, object] = {}
    for model in [*models, purchase.games.through]:
        table = model._meta.db_table
        pk_column = model._meta.pk.column
        quoted_table = connection.ops.quote_name(table)
        quoted_pk = connection.ops.quote_name(pk_column)
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_get_serial_sequence(%s, %s)", [table, pk_column])
            sequence_row = cursor.fetchone()
            if sequence_row is None or sequence_row[0] is None:
                continue
            sequence = sequence_row[0]
            cursor.execute(f"SELECT MAX({quoted_pk}) FROM {quoted_table}")
            maximum = cursor.fetchone()[0] or 0
            cursor.execute(
                f"SELECT last_value, is_called FROM {connection.ops.quote_name(sequence)}"
            )
            last_value, is_called = cursor.fetchone()
        next_pk = last_value + 1 if is_called else last_value
        if next_pk <= maximum:
            raise CutoverError(
                f"sequence for {table} is behind data: max={maximum}, next={next_pk}"
            )
        results[table] = {"max_pk": maximum, "next_pk": next_pk}
    return results


def run_smoke_checks() -> dict[str, int]:
    user_model = apps.get_model("auth.user")
    user = user_model._base_manager.order_by(user_model._meta.pk.attname).first()
    if user is None:
        raise CutoverError("cannot run smoke checks without a transferred user")
    paths = {
        "games:index": reverse("games:index"),
        "games:list_games": reverse("games:list_games"),
        "games:list_sessions": reverse("games:list_sessions"),
        "games:list_purchases": reverse("games:list_purchases"),
        "games:list_playevents": reverse("games:list_playevents"),
        "games:list_statuschanges": reverse("games:list_statuschanges"),
        "games:settings": reverse("games:settings"),
        "games:stats_alltime": reverse("games:stats_alltime"),
        "games:game_filter": reverse("games:filter_builder", args=["game"]),
    }
    client = Client(HTTP_HOST="localhost")
    client.force_login(user)
    try:
        results = {
            name: client.get(path, follow=True).status_code
            for name, path in paths.items()
        }
    finally:
        client.logout()
    failures = {name: status for name, status in results.items() if status != 200}
    if failures:
        raise CutoverError(f"smoke checks failed: {failures}")
    return results


def verify_git_identity() -> tuple[str, str]:
    repository = Path(__file__).resolve().parents[1]
    script_relative = "scripts/one_time_sqlite_postgres_cutover.py"
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    expected_blob = subprocess.run(
        ["git", "rev-parse", f"HEAD:{script_relative}"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    actual_blob = subprocess.run(
        ["git", "hash-object", script_relative],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if actual_blob != expected_blob:
        raise CutoverError("cutover script differs from the committed Git blob")
    return commit, actual_blob


def build_report(**evidence: Any) -> dict[str, object]:
    return {
        "source": {
            "archive_sha256": evidence["source_archive_sha256"],
            "members": evidence["source_members"],
            "counts": evidence["source_counts"],
            "discarded_counts": evidence["discarded_counts"],
        },
        "git": {
            "commit": evidence["git_commit"],
            "script_blob": evidence["script_blob"],
        },
        "model_digests": evidence["model_digests"],
        "generated": evidence["generated_results"],
        "aggregates": evidence["aggregate_results"],
        "sequences": evidence["sequence_results"],
        "smoke": evidence["smoke_results"],
        "schedule": evidence["schedule_result"],
    }


def write_report(report: dict[str, object], path: Path) -> None:
    require_git_ignored_workspace(path.parent)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def validate_source(
    connection: BaseDatabaseWrapper, contract: SourceContract
) -> SourceEvidence:
    with connection.cursor() as cursor:
        cursor.execute("PRAGMA quick_check")
        row = cursor.fetchone()
    quick_check = "" if row is None else str(row[0])
    if quick_check != "ok":
        raise CutoverError(f"SQLite PRAGMA quick_check failed: {quick_check}")

    loader = MigrationLoader(connection)
    loader.check_consistent_history(connection)
    effective_squash_applied = SQUASH_MIGRATION in loader.applied_migrations
    if not effective_squash_applied:
        raise CutoverError(
            "source does not have the expected squashed migration effectively applied"
        )

    structure = source_structure(connection)
    validate_source_structure(structure, contract)
    return SourceEvidence(
        structure=structure,
        table_counts=source_table_counts(connection, set(structure.table_columns)),
        quick_check=quick_check,
        effective_squash_applied=effective_squash_applied,
    )


def _validate_snapshot_unchanged(snapshot: SnapshotFiles) -> None:
    mismatches: list[str] = []
    if sha256_file(snapshot.archive) != snapshot.archive_sha256:
        mismatches.append(f"{snapshot.archive.name} changed")
    paths = {
        "db.sqlite3": snapshot.database,
        "db.sqlite3-wal": snapshot.wal,
        "db.sqlite3-journal": snapshot.journal,
    }
    for name, expected_hash in snapshot.durable_member_sha256.items():
        path = paths[name]
        if path is None or not path.exists() or sha256_file(path) != expected_hash:
            mismatches.append(f"{name} changed")
    if mismatches:
        raise CutoverError("durable source snapshot changed: " + ", ".join(mismatches))


@contextmanager
def open_validated_source(
    archive: Path, workspace: Path, contract: SourceContract
) -> Iterator[PreparedSource]:
    snapshot = extract_snapshot(archive, workspace)
    connection = configure_source_alias(snapshot.database)
    try:
        evidence = validate_source(connection, contract)
        yield PreparedSource(
            snapshot=snapshot,
            evidence=evidence,
            connection=connection,
        )
    finally:
        remove_source_alias(connection)
        _validate_snapshot_unchanged(snapshot)


def _migration_name(migration: tuple[str, str]) -> str:
    return ".".join(migration)


def validate_source_structure(
    actual: SourceStructure, expected: SourceContract
) -> None:
    mismatches: list[str] = []

    actual_migrations = set(actual.migrations)
    expected_migrations = set(expected.migrations)
    added_migrations = sorted(actual_migrations - expected_migrations)
    missing_migrations = sorted(expected_migrations - actual_migrations)
    if added_migrations:
        mismatches.append(
            "unexpected migrations: "
            + ", ".join(_migration_name(item) for item in added_migrations)
        )
    if missing_migrations:
        mismatches.append(
            "missing migrations: "
            + ", ".join(_migration_name(item) for item in missing_migrations)
        )

    actual_tables = set(actual.table_columns)
    expected_tables = set(expected.table_columns)
    disposition_tables = set(expected.table_dispositions)
    added_tables = sorted(actual_tables - expected_tables)
    missing_tables = sorted(expected_tables - actual_tables)
    if added_tables:
        mismatches.append("unexpected tables: " + ", ".join(added_tables))
    if missing_tables:
        mismatches.append("missing tables: " + ", ".join(missing_tables))

    missing_dispositions = sorted(actual_tables - disposition_tables)
    stale_dispositions = sorted(disposition_tables - actual_tables)
    if missing_dispositions:
        mismatches.append(
            "tables without dispositions: " + ", ".join(missing_dispositions)
        )
    if stale_dispositions:
        mismatches.append(
            "dispositions without source tables: " + ", ".join(stale_dispositions)
        )

    for table in sorted(actual_tables & expected_tables):
        actual_columns = actual.table_columns[table]
        expected_columns = expected.table_columns[table]
        if actual_columns == expected_columns:
            continue
        added_columns = sorted(set(actual_columns) - set(expected_columns))
        missing_columns = sorted(set(expected_columns) - set(actual_columns))
        details = [
            f"expected ordered columns {expected_columns!r}",
            f"found {actual_columns!r}",
        ]
        if added_columns:
            details.append("unexpected " + ", ".join(added_columns))
        if missing_columns:
            details.append("missing " + ", ".join(missing_columns))
        mismatches.append(f"table {table}: " + "; ".join(details))

    if mismatches:
        raise CutoverError("source structure mismatch:\n- " + "\n- ".join(mismatches))
