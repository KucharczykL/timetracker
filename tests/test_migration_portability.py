"""Reject the SQLite-only constructs PG-07 removed from the migration set.

PostgreSQL verification is a manual, one-shot container run until PG-13 supplies
a harness, so the three defect classes that each aborted a fresh PostgreSQL
build are held out statically in the meantime.

Known blind spot, covered instead by the PostgreSQL build itself: RunSQL nested
inside SeparateDatabaseAndState.
"""

import pathlib

import pytest
from django.conf import settings
from django.db import migrations, models
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.operations.special import RunSQL
from django.db.models import F, Q
from django.db.models.expressions import RawSQL
from django.db.models.fields.generated import GeneratedField

# Excludes date(/datetime(, which collide with datetime.date(...) and
# datetime.datetime(...) field defaults — ordinary Python, not SQLite calls.
SQLITE_ONLY_FUNCTIONS = ("julianday(", "strftime(", "unixepoch(")


def migration_directory():
    directory = pathlib.Path(settings.BASE_DIR) / "games" / "migrations"
    assert directory.is_dir(), f"migration package missing at {directory}"
    return directory


def games_migrations():
    loader = MigrationLoader(connection=None, ignore_no_migrations=True)
    migrations = [
        (name, migration)
        for (app_label, name), migration in loader.disk_migrations.items()
        if app_label == "games"
    ]
    assert migrations, "no games migrations discovered"
    return migrations


def generated_fields(migration):
    """Yield (operation, field name, field) for every GeneratedField declared."""
    for operation in migration.operations:
        field = getattr(operation, "field", None)
        if isinstance(field, GeneratedField):
            yield operation, operation.name, field
        for field_name, field in getattr(operation, "fields", None) or []:
            if isinstance(field, GeneratedField):
                yield operation, field_name, field


def referenced_column_names(expression):
    """Column names an expression reads, including Q lookup left-hand sides."""
    names = set()
    nodes = expression.flatten() if hasattr(expression, "flatten") else [expression]
    for node in nodes:
        if isinstance(node, F):
            names.add(node.name.split("__")[0])
        elif isinstance(node, Q):
            for child in node.children:
                if isinstance(child, tuple):
                    names.add(child[0].split("__")[0])
    return names


def generated_column_references(migration_items):
    generated_names = {
        field_name
        for _, migration in migration_items
        for _, field_name, _ in generated_fields(migration)
    }
    offenders = []
    for migration_name, migration in migration_items:
        for _, field_name, field in generated_fields(migration):
            read = referenced_column_names(field.expression) & (
                generated_names - {field_name}
            )
            if read:
                offenders.append((migration_name, field_name, sorted(read)))
    return offenders


def test_no_run_sql_operations():
    offenders = [
        name
        for name, migration in games_migrations()
        for operation in migration.operations
        if isinstance(operation, RunSQL)
    ]
    assert offenders == [], f"RunSQL is not portable; found in {offenders}"


def test_no_raw_sql_in_generated_columns():
    offenders = [
        name
        for name, migration in games_migrations()
        for _, _, field in generated_fields(migration)
        if any(isinstance(node, RawSQL) for node in field.expression.flatten())
    ]
    assert offenders == [], f"RawSQL in a generated column; found in {offenders}"


def test_generated_column_guard_discovers_new_names():
    synthetic = migrations.Migration("0001_synthetic", "games")
    synthetic.operations = [
        migrations.CreateModel(
            name="Synthetic",
            fields=[
                ("seed", models.IntegerField()),
                (
                    "computed_source",
                    models.GeneratedField(
                        expression=models.Value(1),
                        output_field=models.IntegerField(),
                        db_persist=True,
                    ),
                ),
                (
                    "computed_total",
                    models.GeneratedField(
                        expression=models.F("computed_source"),
                        output_field=models.IntegerField(),
                        db_persist=True,
                    ),
                ),
            ],
        )
    ]

    assert generated_column_references([("0001_synthetic", synthetic)]) == [
        ("0001_synthetic", "computed_total", ["computed_source"])
    ]


def test_no_generated_column_reads_another_generated_column():
    offenders = generated_column_references(games_migrations())
    assert offenders == [], (
        f"PostgreSQL forbids a generated column reading another; found {offenders}"
    )


@pytest.mark.parametrize("function", SQLITE_ONLY_FUNCTIONS)
def test_no_sqlite_only_function_names_in_migration_source(function):
    offenders = [
        path.name
        for path in sorted(migration_directory().glob("0*.py"))
        if function in path.read_text()
    ]
    assert offenders == [], f"{function} is SQLite-only; found in {offenders}"
