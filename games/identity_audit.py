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
    ("games_userlibrary", "user_id"): NEVER_CONVERTS,
    ("games_userpreferences", "user_id"): NEVER_CONVERTS,
    ("games_libraryevent", "actor_id"): NEVER_CONVERTS,
}

RESIDUAL_INTEGER_PRIMARY_KEYS: dict[TableName, OwnerLabel] = {
    "games_purchase_games": _THROUGH_PK_IS_PERMANENT,
    "games_exchangerate": _NOT_A_CONVERTED_MODEL,
    "games_sitesetting": _NOT_A_CONVERTED_MODEL,
    "games_userpreferences": _NOT_A_CONVERTED_MODEL,
}

INTEGER_TYPES = frozenset(["integer", "bigint", "smallint"])
UUID_TYPE: ColumnType = "uuid_v7"

# The field each model's UUID was backfilled from, and orders by. Wave B chose
# these per model rather than uniformly; `GameStatusChange` has no `created_at`
# at all, so its audit trail's own `timestamp` is the only ordering it has.
DEFAULT_ORDER_SOURCE = "created_at"
IDENTITY_ORDER_SOURCE: dict[TableName, str] = {
    "games_gamestatuschange": "timestamp",
    "games_libraryevent": "recorded_at",
}

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


class IdentityModel(NamedTuple):
    model: type[Model]
    table: TableName
    identity_field: str  # ORM name, e.g. "uuid" or "library"
    identity_column: str  # database column, e.g. "uuid" or "library_id"
    order_source: str | None  # None when the model has nothing to order by


def audited_models() -> list[type[Model]]:
    """Every table this project owns, auto-created through tables included.

    `include_auto_created` is not optional: `games_purchase_games` carries the
    permanent bigint through-row primary-key exemption and is invisible without it.
    """
    #: `managed` is what excludes the manufactured twins.
    return [
        model
        for model in apps.get_app_config("games").get_models(include_auto_created=True)
        if model._meta.managed
    ]


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


def identity_models() -> list[IdentityModel]:
    """Every model carrying a UUID identity, derived rather than listed.

    A model qualifies through its own `uuid` column or through a `uuid_v7`
    primary key - the latter catches `UserLibrary`, which is already converted,
    and the two models that share its key.
    """
    models = []
    for model in audited_models():
        primary_key = model._meta.pk
        identity = next(
            (
                field
                for field in model._meta.local_fields
                if field.name == "uuid" and field.db_type(connection) == UUID_TYPE
            ),
            None,
        )
        if (
            identity is None
            and primary_key is not None
            and primary_key.db_type(connection) == UUID_TYPE
        ):
            identity = primary_key
        if identity is None or identity.column is None:
            continue
        source = IDENTITY_ORDER_SOURCE.get(model._meta.db_table, DEFAULT_ORDER_SOURCE)
        has_source = any(field.name == source for field in model._meta.local_fields)
        models.append(
            IdentityModel(
                model=model,
                table=model._meta.db_table,
                identity_field=identity.name,
                identity_column=identity.column,
                order_source=source if has_source else None,
            )
        )
    return sorted(models, key=lambda entry: entry.table)


def check_identity_columns(cursor, models: list[IdentityModel]) -> CheckReport:
    """Confirm each identity column is still typed, constrained and populated.

    PostgreSQL enforces all of this already; the point is that Wave C's column
    surgery could have dropped a constraint while Django's migration state kept
    listing it, and `RemoveField` compiles to a `DROP COLUMN` that cascades away
    every index over the column without any drift check noticing.
    """
    violations: list[Violation] = []
    notes: list[Note] = []
    for entry in models:
        subject = f"{entry.table}.{entry.identity_column}"
        cursor.execute(
            """
            SELECT type.typname, attribute.attnotnull
            FROM pg_attribute AS attribute
            JOIN pg_class AS class ON class.oid = attribute.attrelid
            JOIN pg_type AS type ON type.oid = attribute.atttypid
            WHERE class.relname = %s AND attribute.attname = %s
              AND attribute.attnum > 0 AND NOT attribute.attisdropped
            """,
            [entry.table, entry.identity_column],
        )
        row = cursor.fetchone()
        if row is None:
            violations.append(
                Violation("identity-column", subject, "column does not exist")
            )
            continue
        type_name, not_null = row
        if type_name != UUID_TYPE:
            violations.append(
                Violation(
                    "identity-column",
                    subject,
                    f"expected {UUID_TYPE}, found {type_name}",
                )
            )
        if not not_null:
            violations.append(
                Violation("identity-column", subject, "column is nullable")
            )

        constraints = connection.introspection.get_constraints(cursor, entry.table)
        unique_indexes = [
            name
            for name, constraint in constraints.items()
            if constraint["columns"] == [entry.identity_column]
            and (constraint["unique"] or constraint["primary_key"])
        ]
        if not unique_indexes:
            violations.append(
                Violation("identity-column", subject, "no unique index over the column")
            )

        cursor.execute(
            f'SELECT count(*), count(DISTINCT "{entry.identity_column}"), '
            f'count(*) FILTER (WHERE "{entry.identity_column}" IS NULL) '
            f'FROM "{entry.table}"'
        )
        row_count, distinct_count, null_count = cursor.fetchone()
        if distinct_count != row_count - null_count:
            violations.append(
                Violation(
                    "identity-column",
                    subject,
                    f"{row_count - null_count} non-null rows share "
                    f"{distinct_count} distinct values",
                )
            )
        if null_count:
            violations.append(
                Violation("identity-column", subject, f"{null_count} NULL identities")
            )
        notes.append(Note("identity-column", subject, f"{row_count} rows"))
    return CheckReport(violations, notes)


def check_ordering(models: list[IdentityModel]) -> CheckReport:
    """Confirm UUID order still reproduces creation order.

    The one invariant here that no constraint enforces. Wave B's backfill
    established it and every later insert has to preserve it, because a UUIDv7
    minted at any time other than the row's own creation silently breaks it.

    Rows whose ordering source is NULL are excluded rather than required to sort
    last: migration 0006 stamped those with the migration's own clock, which put
    them last only until the next row was inserted.
    """
    violations: list[Violation] = []
    notes: list[Note] = []
    for entry in models:
        if entry.order_source is None:
            notes.append(
                Note(
                    "ordering",
                    entry.table,
                    "skipped: the model has no creation timestamp to order by",
                )
            )
            continue
        rows = entry.model._base_manager.all()
        excluded = rows.filter(**{f"{entry.order_source}__isnull": True}).count()
        if excluded:
            rows = rows.filter(**{f"{entry.order_source}__isnull": False})
        by_identity = list(
            rows.order_by(entry.identity_field).values_list("pk", flat=True)
        )
        by_source = list(
            rows.order_by(entry.order_source, "pk").values_list("pk", flat=True)
        )
        if by_identity != by_source:
            divergence = next(
                index
                for index, (left, right) in enumerate(zip(by_identity, by_source))
                if left != right
            )
            violations.append(
                Violation(
                    "ordering",
                    entry.table,
                    f"identity order diverges from ({entry.order_source}, pk) order "
                    f"at position {divergence}: identity gives pk "
                    f"{by_identity[divergence]}, {entry.order_source} gives pk "
                    f"{by_source[divergence]}",
                )
            )
        note = f"{len(by_identity)} rows ordered by {entry.order_source}"
        if excluded:
            note += f", {excluded} excluded for a NULL {entry.order_source}"
        notes.append(Note("ordering", entry.table, note))
    return CheckReport(violations, notes)


def check_referential_agreement(cursor, relations: list[RelationColumn]) -> CheckReport:
    """Confirm every relation resolves, and that PostgreSQL has actually checked.

    The orphan count is what a committed database's constraints already
    guarantee. `convalidated` is not: PostgreSQL accepts a `NOT VALID` foreign
    key, which enforces new rows while never having looked at the existing ones.
    """
    violations: list[Violation] = []
    notes: list[Note] = []
    tables = sorted({relation.table for relation in relations})
    cursor.execute(
        """
        SELECT class.relname, attribute.attname, constraint_.convalidated
        FROM pg_constraint AS constraint_
        JOIN pg_class AS class ON class.oid = constraint_.conrelid
        JOIN pg_attribute AS attribute
          ON attribute.attrelid = constraint_.conrelid
         AND attribute.attnum = ANY(constraint_.conkey)
        WHERE constraint_.contype = 'f' AND class.relname = ANY(%s)
        """,
        [tables],
    )
    validated = {
        (table, column): is_valid for table, column, is_valid in cursor.fetchall()
    }

    for relation in relations:
        is_valid = validated.get(relation.key)
        if is_valid is None:
            violations.append(
                Violation(
                    "referential",
                    str(relation),
                    "no foreign-key constraint on the column",
                )
            )
        elif not is_valid:
            violations.append(
                Violation(
                    "referential",
                    str(relation),
                    "foreign key is NOT VALID - existing rows were never checked",
                )
            )
        cursor.execute(
            f"""
            SELECT count(*) FROM "{relation.table}" AS child
            LEFT JOIN "{relation.target_table}" AS target
              ON target."{relation.target_column}" = child."{relation.column}"
            WHERE child."{relation.column}" IS NOT NULL
              AND target."{relation.target_column}" IS NULL
            """
        )
        (orphans,) = cursor.fetchone()
        if orphans:
            violations.append(
                Violation(
                    "referential",
                    str(relation),
                    f"{orphans} row(s) reference a missing "
                    f"{relation.target_table}.{relation.target_column}",
                )
            )
    notes.append(
        Note("referential", "relations", f"{len(relations)} relation columns resolved")
    )
    return CheckReport(violations, notes)
