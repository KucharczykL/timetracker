"""Verify that the integer-to-UUID identity map is complete and consistent.

Pure computation: every check takes already-read inputs (or a cursor) and returns
a `CheckReport`. Presentation and the non-zero exit belong to the management
command, mirroring the `stats_data` / `stats_content` split.

Expectations are derived from Django's model metadata rather than declared, so a
relation added later is audited without touching this module. Only the *residual*
integer set is pinned, because "still integer, and deliberately so" is not
derivable from the schema - it is a statement about which slice owns the
conversion.
"""

from collections.abc import Callable
from typing import NamedTuple

from django.apps import apps
from django.db import connection
from django.db.models import Field, ForeignObject, Model

type TableName = str  # e.g. "games_purchase_games"
type TableColumn = tuple[TableName, str]  # e.g. ("games_purchase_games", "game_id")
type OwnerLabel = str  # e.g. "ID-11 (#646)"
type ColumnType = str  # e.g. "uuid_v7", "bigint"


def _converted_by(slice_name: str) -> OwnerLabel:
    return f"converted by {slice_name}"


NEVER_CONVERTS = "never converts: auth.User is not a converted model"
_THROUGH_PK_IS_PERMANENT = (
    "never converts: an auto-created through table keeps its own key"
)
_NOT_A_CONVERTED_MODEL = "never converts: not part of the UUID identity cutover"

# Relation columns that are still integer on purpose, and the slice that owns
# converting each. Equality is asserted in both directions: an integer relation
# missing from here fails the audit as a gap, and an entry that is no longer
# integer fails it as stale, so a Wave E slice cannot land without shrinking it.
RESIDUAL_INTEGER_RELATIONS: dict[TableColumn, OwnerLabel] = {
    ("games_purchase_games", "game_id"): _converted_by("ID-11 (#646)"),
    ("games_purchase_games", "purchase_id"): _converted_by("ID-13 (#849)"),
    ("games_userlibrary", "user_id"): NEVER_CONVERTS,
    ("games_userpreferences", "user_id"): NEVER_CONVERTS,
}

RESIDUAL_INTEGER_PRIMARY_KEYS: dict[TableName, OwnerLabel] = {
    "games_game": _converted_by("ID-11 (#646)"),
    "games_platform": _converted_by("ID-11 (#646)"),
    "games_session": _converted_by("ID-12 (#848)"),
    "games_playevent": _converted_by("ID-12 (#848)"),
    "games_gamestatuschange": _converted_by("ID-12 (#848)"),
    "games_purchase": _converted_by("ID-13 (#849)"),
    "games_device": _converted_by("ID-14 (#850)"),
    "games_filterpreset": _converted_by("ID-14 (#850)"),
    "games_purchase_games": _THROUGH_PK_IS_PERMANENT,
    "games_exchangerate": _NOT_A_CONVERTED_MODEL,
    "games_sitesetting": _NOT_A_CONVERTED_MODEL,
    "games_userpreferences": _NOT_A_CONVERTED_MODEL,
}

INTEGER_TYPES = frozenset(["integer", "bigint", "smallint"])

# pg_type.typname carries PostgreSQL's internal spelling; Django's db_type()
# emits the SQL standard one. Domains (uuid_v7) are already named identically.
_CATALOG_TYPE_NAMES: dict[str, ColumnType] = {
    "int2": "smallint",
    "int4": "integer",
    "int8": "bigint",
}


class Violation(NamedTuple):
    check: str
    subject: str
    detail: str


class Note(NamedTuple):
    """A reportable non-failure - a skipped model, an excluded row count.

    Checks that skip work must say so out loud: a check silently reporting
    nothing is indistinguishable from a check that passed.
    """

    check: str
    subject: str
    detail: str


class CheckReport(NamedTuple):
    violations: list[Violation]
    notes: list[Note]


class RelationColumn(NamedTuple):
    table: TableName
    column: str
    target_table: TableName
    target_column: str
    expected_type: ColumnType

    @property
    def key(self) -> TableColumn:
        return (self.table, self.column)

    def __str__(self) -> str:
        return f"{self.table}.{self.column}"


def audited_models() -> list[type[Model]]:
    """Every table this project owns, auto-created through tables included.

    `include_auto_created` is not optional: `games_purchase_games` carries half
    the residual integer inventory and is invisible without it.
    """
    return list(apps.get_app_config("games").get_models(include_auto_created=True))


def relation_columns() -> list[RelationColumn]:
    """Every foreign-key column this project owns, with its expected type.

    The expectation is the *target field's* database type, which is what makes
    this derived rather than declared: a relation points at whatever identity its
    target currently exposes, so the audit needs no update when one converts.
    """
    columns: list[RelationColumn] = []
    for model in audited_models():
        for field in model._meta.local_fields:
            if not isinstance(field, ForeignObject):
                continue
            target: Field = field.target_field
            column = field.column
            target_column = target.column
            expected_type = field.db_type(connection)
            if not (column and target_column and expected_type):
                continue
            columns.append(
                RelationColumn(
                    table=model._meta.db_table,
                    column=column,
                    target_table=target.model._meta.db_table,
                    target_column=target_column,
                    expected_type=expected_type,
                )
            )
    return sorted(columns)


def actual_column_types(cursor) -> dict[TableColumn, ColumnType]:
    """Read every audited table's column types straight from the catalog.

    `pg_type.typname`, not `format_type()`: the latter is search-path sensitive
    and reports `public.uuid_v7` whenever the domain's schema is not visible,
    which would turn every UUID column into a false violation on precisely the
    long-lived deployment this audit exists to inspect.
    """
    tables = [model._meta.db_table for model in audited_models()]
    cursor.execute(
        """
        SELECT class.relname, attribute.attname, type.typname
        FROM pg_attribute AS attribute
        JOIN pg_class AS class ON class.oid = attribute.attrelid
        JOIN pg_type AS type ON type.oid = attribute.atttypid
        WHERE class.relname = ANY(%s)
          AND attribute.attnum > 0
          AND NOT attribute.attisdropped
        """,
        [tables],
    )
    return {
        (table, column): _CATALOG_TYPE_NAMES.get(type_name, type_name)
        for table, column, type_name in cursor.fetchall()
    }


def primary_key_types(
    actual_types: dict[TableColumn, ColumnType],
) -> dict[TableName, ColumnType]:
    types: dict[TableName, ColumnType] = {}
    for model in audited_models():
        primary_key = model._meta.pk
        if primary_key is None or primary_key.column is None:
            continue
        actual = actual_types.get((model._meta.db_table, primary_key.column))
        if actual is not None:
            types[model._meta.db_table] = actual
    return types


def check_type_agreement(
    relations: list[RelationColumn],
    actual_types: dict[TableColumn, ColumnType],
) -> CheckReport:
    """Compare what Django believes each relation column is against the database.

    Wave C rewrote these columns with raw SQL, `RemoveField` and `RenameField`,
    and Wave E will do more of the same. Django's migration state and PostgreSQL
    can therefore disagree without any drift check noticing, because
    `makemigrations --check` compares state against models, never against the
    database.
    """
    violations: list[Violation] = []
    notes: list[Note] = []
    present_tables = {table for table, _ in actual_types}
    missing_tables = sorted({relation.table for relation in relations} - present_tables)
    # Report an absent table once instead of letting each of its columns raise a
    # separate "no such column": against an unmigrated database the per-column
    # form buries the actual problem under nineteen lines of consequence.
    violations.extend(
        Violation(
            "type-agreement",
            table,
            "table does not exist - is this database migrated?",
        )
        for table in missing_tables
    )
    for relation in relations:
        if relation.table in missing_tables:
            continue
        actual = actual_types.get(relation.key)
        if actual is None:
            violations.append(
                Violation(
                    "type-agreement",
                    str(relation),
                    "Django declares this column but PostgreSQL has no such column",
                )
            )
        elif actual != relation.expected_type:
            violations.append(
                Violation(
                    "type-agreement",
                    str(relation),
                    f"Django expects {relation.expected_type}, "
                    f"PostgreSQL has {actual} "
                    f"(target {relation.target_table}.{relation.target_column})",
                )
            )
    notes.append(
        Note(
            "type-agreement", "relations", f"{len(relations)} relation columns checked"
        )
    )
    return CheckReport(violations, notes)


def _inventory_violations[Key](
    check: str,
    actual_integers: dict[Key, ColumnType],
    inventory: dict[Key, OwnerLabel],
    subject_of: Callable[[Key], str],
) -> list[Violation]:
    violations = [
        Violation(
            check,
            subject_of(key),
            f"still integer ({type_name}) and not in the residual inventory",
        )
        for key, type_name in sorted(actual_integers.items())
        if key not in inventory
    ]
    violations.extend(
        Violation(
            check,
            subject_of(key),
            f"listed as residual ({owner}) but is no longer integer - "
            "remove it from the inventory",
        )
        for key, owner in sorted(inventory.items())
        if key not in actual_integers
    )
    return violations


def check_residual_inventory(
    relations: list[RelationColumn],
    actual_types: dict[TableColumn, ColumnType],
    pk_types: dict[TableName, ColumnType],
) -> CheckReport:
    """Assert the still-integer set is exactly the documented one.

    Equality in both directions is the whole point: containment would let a
    missed relation hide, and would let a converted column linger in the
    inventory, so the inventory would stop meaning anything by Wave E.
    """
    integer_relations = {
        relation.key: actual_types[relation.key]
        for relation in relations
        if actual_types.get(relation.key) in INTEGER_TYPES
    }
    integer_primary_keys = {
        table: type_name
        for table, type_name in pk_types.items()
        if type_name in INTEGER_TYPES
    }

    violations = _inventory_violations(
        "residual-relations",
        integer_relations,
        RESIDUAL_INTEGER_RELATIONS,
        lambda key: f"{key[0]}.{key[1]}",
    )
    violations.extend(
        _inventory_violations(
            "residual-primary-keys",
            integer_primary_keys,
            RESIDUAL_INTEGER_PRIMARY_KEYS,
            lambda table: table,
        )
    )

    notes = [
        Note(
            "residual-relations",
            f"{key[0]}.{key[1]}",
            f"{type_name}, {RESIDUAL_INTEGER_RELATIONS[key]}",
        )
        for key, type_name in sorted(integer_relations.items())
        if key in RESIDUAL_INTEGER_RELATIONS
    ]
    notes.extend(
        Note(
            "residual-primary-keys",
            table,
            f"{type_name}, {RESIDUAL_INTEGER_PRIMARY_KEYS[table]}",
        )
        for table, type_name in sorted(integer_primary_keys.items())
        if table in RESIDUAL_INTEGER_PRIMARY_KEYS
    )
    return CheckReport(violations, notes)
