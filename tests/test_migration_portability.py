"""Reject the SQLite-only constructs PG-07 removed from the migration set.

PostgreSQL verification is a manual, one-shot container run until PG-13 supplies
a harness, so the three defect classes that each aborted a fresh PostgreSQL
build are held out statically in the meantime.

Known blind spots, covered instead by the PostgreSQL build itself: RunSQL nested
inside SeparateDatabaseAndState, and lookups inside a Q object, whose left-hand
side Q.flatten() discards.
"""

import pathlib

import pytest
from django.conf import settings
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.operations.special import RunSQL
from django.db.models import F, Q
from django.db.models.expressions import RawSQL
from django.db.models.fields.generated import GeneratedField

# Excludes date(/datetime(, which collide with datetime.date(...) and
# datetime.datetime(...) field defaults — ordinary Python, not SQLite calls.
SQLITE_ONLY_FUNCTIONS = ("julianday(", "strftime(", "unixepoch(")

GENERATED_COLUMNS = frozenset(
    {"duration_calculated", "duration_total", "price_per_game", "days_to_finish"}
)


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
    """Yield (operation, field) for every GeneratedField the operation declares."""
    for operation in migration.operations:
        entries = [(None, getattr(operation, "field", None))]
        entries += list(getattr(operation, "fields", None) or [])
        for _, field in entries:
            if isinstance(field, GeneratedField):
                yield operation, field


def referenced_column_names(expression):
    """Column names an expression reads, including Q lookup left-hand sides."""
    names = set()
    for node in expression.flatten():
        if isinstance(node, F):
            names.add(node.name.split("__")[0])
        elif isinstance(node, Q):
            for child in node.children:
                if isinstance(child, tuple):
                    names.add(child[0].split("__")[0])
    return names


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
        for _, field in generated_fields(migration)
        if any(isinstance(node, RawSQL) for node in field.expression.flatten())
    ]
    assert offenders == [], f"RawSQL in a generated column; found in {offenders}"


def test_no_generated_column_reads_another_generated_column():
    offenders = []
    for name, migration in games_migrations():
        for operation, field in generated_fields(migration):
            # AddField/AlterField.name is the field; CreateModel.name is the
            # model, which merely widens the forbidden set for that operation.
            own = getattr(operation, "name", None)
            read = referenced_column_names(field.expression) & (
                GENERATED_COLUMNS - {own}
            )
            if read:
                offenders.append((name, own, sorted(read)))
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
