"""Compare the deployment's schema against one built from `0001_initial`.

`games/migrations/0001_initial.py` states the end of a history that had already
run in full, so nothing replays it any more and nothing else checks that the
end it states is the end that ran. This does: it restores a dump of the
deployment, carries it over to the new history exactly as an operator would,
builds a second database from `0001_initial` alone, and reads both catalogs.

Any row only one of them holds is drift, and drift here is a future migration
generated against a baseline the deployment does not have. Nothing is compared
by eye: `pg_dump` writes a table's columns in the order they were added, so its
text differs between two databases that hold the same schema, while the catalog
queries below sort every answer.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import db_dump
from db_dump import DumpError, client_tool, run, with_database

REPOSITORY = Path(__file__).parents[1]
DEPLOYED_DATABASE = "timetracker_baseline_deployed"
FRESH_DATABASE = "timetracker_baseline_fresh"

#: What an operator runs on the deployment, once, before recording the new
#: history. Every statement is written to be safe to run twice, so the same
#: block serves a deployment that has applied the legacy-table removal and one
#: that has not.
#:
#: The DROPs and the DELETEs are the work the deleted `0049` and `0050` did. A
#: deployment that took them already has neither table nor content type, and a
#: deployment that did not has both -- `0001_initial` creates neither, so
#: nothing else would ever take them away. `0050` removed a content type
#: through the ORM, whose collector reaches the permission rows that name it;
#: here the same reach is spelled out, because the database refuses the content
#: type while a permission still references it.
#:
#: The renames are cosmetic and still worth doing: PostgreSQL names a NOT NULL
#: constraint after the column, and these six were named while the column was
#: called `uuid`. A fresh build names them after `id`, so without this the two
#: schemas differ by six strings forever. Renaming one that is already renamed
#: is an error rather than a no-op, which is what the lookup is for.
CUTOVER = """
DROP TABLE IF EXISTS games_playevent;
DROP TABLE IF EXISTS games_gamestatuschange;

CREATE TEMPORARY TABLE legacy_content_type AS
SELECT id FROM django_content_type
WHERE app_label = 'games' AND model IN ('playevent', 'gamestatuschange');

CREATE TEMPORARY TABLE legacy_permission AS
SELECT id FROM auth_permission
WHERE content_type_id IN (SELECT id FROM legacy_content_type);

DELETE FROM auth_user_user_permissions
WHERE permission_id IN (SELECT id FROM legacy_permission);
DELETE FROM auth_group_permissions
WHERE permission_id IN (SELECT id FROM legacy_permission);
DELETE FROM auth_permission WHERE id IN (SELECT id FROM legacy_permission);
DELETE FROM django_content_type WHERE id IN (SELECT id FROM legacy_content_type);

DROP TABLE legacy_permission;
DROP TABLE legacy_content_type;

DO $$
DECLARE
    legacy_name text;
BEGIN
    FOR legacy_name IN
        SELECT constraint_entry.conname
        FROM pg_constraint AS constraint_entry
        JOIN pg_class AS table_entry
            ON table_entry.oid = constraint_entry.conrelid
        JOIN pg_namespace AS schema_entry
            ON schema_entry.oid = table_entry.relnamespace
        WHERE schema_entry.nspname = 'public'
          AND constraint_entry.contype = 'n'
          AND constraint_entry.conname LIKE 'games\\_%\\_uuid\\_not\\_null'
    LOOP
        EXECUTE format(
            'ALTER TABLE %I RENAME CONSTRAINT %I TO %I',
            left(legacy_name, -length('_uuid_not_null')),
            legacy_name,
            left(legacy_name, -length('_uuid_not_null')) || '_id_not_null'
        );
    END LOOP;
END
$$;

DELETE FROM django_migrations WHERE app = 'games';
""".strip()

type CatalogName = str
type CatalogQuery = str

#: One query per kind of thing a schema holds. Each sorts, and each names every
#: property that decides behaviour -- a type, a nullability, a default, a
#: definition -- so a difference in any of them shows up as a differing row.
#: Column order is deliberately absent: it is physical, and no statement this
#: application writes depends on it.
CATALOG_QUERIES: dict[CatalogName, CatalogQuery] = {
    "columns": """
        SELECT table_entry.relname,
               column_entry.attname,
               format_type(column_entry.atttypid, column_entry.atttypmod),
               column_entry.attnotnull,
               column_entry.attgenerated,
               pg_get_expr(default_entry.adbin, default_entry.adrelid)
        FROM pg_attribute AS column_entry
        JOIN pg_class AS table_entry ON table_entry.oid = column_entry.attrelid
        JOIN pg_namespace AS schema_entry
            ON schema_entry.oid = table_entry.relnamespace
        LEFT JOIN pg_attrdef AS default_entry
            ON default_entry.adrelid = column_entry.attrelid
           AND default_entry.adnum = column_entry.attnum
        WHERE schema_entry.nspname = 'public'
          AND table_entry.relkind = 'r'
          AND column_entry.attnum > 0
          AND NOT column_entry.attisdropped
        ORDER BY 1, 2
    """,
    "constraints": """
        SELECT table_entry.relname,
               constraint_entry.conname,
               constraint_entry.contype,
               pg_get_constraintdef(constraint_entry.oid)
        FROM pg_constraint AS constraint_entry
        JOIN pg_class AS table_entry ON table_entry.oid = constraint_entry.conrelid
        JOIN pg_namespace AS schema_entry
            ON schema_entry.oid = table_entry.relnamespace
        WHERE schema_entry.nspname = 'public'
        ORDER BY 1, 2
    """,
    "indexes": """
        SELECT tablename, indexname, indexdef
        FROM pg_indexes
        WHERE schemaname = 'public'
        ORDER BY 1, 2
    """,
    #: A definition spans lines, and each answer here has to be one row, or a
    #: line one routine gained and another lost would cancel out.
    "routines": """
        SELECT routine_entry.oid::regprocedure::text,
               regexp_replace(
                   pg_get_functiondef(routine_entry.oid), '\\s+', ' ', 'g'
               )
        FROM pg_proc AS routine_entry
        JOIN pg_namespace AS schema_entry
            ON schema_entry.oid = routine_entry.pronamespace
        WHERE schema_entry.nspname = 'public'
        ORDER BY 1
    """,
    "domains": """
        SELECT domain_entry.typname,
               format_type(domain_entry.typbasetype, domain_entry.typtypmod),
               domain_entry.typnotnull,
               (SELECT string_agg(
                           conname || ' ' || pg_get_constraintdef(oid), '; '
                           ORDER BY conname
                       )
                  FROM pg_constraint
                 WHERE contypid = domain_entry.oid)
        FROM pg_type AS domain_entry
        JOIN pg_namespace AS schema_entry
            ON schema_entry.oid = domain_entry.typnamespace
        WHERE schema_entry.nspname = 'public' AND domain_entry.typtype = 'd'
        ORDER BY 1
    """,
    "sequences": """
        SELECT sequence_entry.relname
        FROM pg_class AS sequence_entry
        JOIN pg_namespace AS schema_entry
            ON schema_entry.oid = sequence_entry.relnamespace
        WHERE schema_entry.nspname = 'public' AND sequence_entry.relkind = 'S'
        ORDER BY 1
    """,
    "recorded history": """
        SELECT app, name FROM django_migrations WHERE app = 'games' ORDER BY 2
    """,
}

#: psql prints one row per line with this between the values, which no value in
#: a catalog answer contains.
FIELD_SEPARATOR = "\x1f"


@dataclass(frozen=True)
class Drift:
    """One kind of thing, and the rows only one database holds."""

    catalog: CatalogName
    only_deployed: tuple[str, ...]
    only_fresh: tuple[str, ...]

    def report(self) -> str:
        lines = [
            (
                f"### {self.catalog}: "
                f"{len(self.only_deployed)} only in the deployment, "
                f"{len(self.only_fresh)} only in the fresh build"
            )
        ]
        lines += [f"  deployment: {row}" for row in self.only_deployed]
        lines += [f"  fresh:      {row}" for row in self.only_fresh]
        return "\n".join(lines)


def create_database(database: str, database_url: str) -> str:
    """Make an empty database under the cluster's collation contract."""
    maintenance = f"--maintenance-db={with_database(database_url, 'postgres')}"
    run([str(client_tool("dropdb")), maintenance, "--if-exists", database])
    run(
        [
            str(client_tool("createdb")),
            maintenance,
            "--template=template0",
            f"--encoding={db_dump.REQUIRED_ENCODING}",
            "--locale-provider=builtin",
            f"--builtin-locale={db_dump.REQUIRED_BUILTIN_LOCALE}",
            database,
        ]
    )
    return with_database(database_url, database)


def drop_database(database: str, database_url: str) -> None:
    maintenance = f"--maintenance-db={with_database(database_url, 'postgres')}"
    run([str(client_tool("dropdb")), maintenance, "--if-exists", database])


def manage(*arguments: str, database_url: str) -> None:
    environment = {**os.environ, "DATABASE_URL": database_url}
    #: This would otherwise send the command at the development database.
    environment.pop("TIMETRACKER_MANAGED_DATABASE_URL", None)
    run(
        [sys.executable, str(REPOSITORY / "manage.py"), *arguments],
        env=environment,
    )


def apply_sql(statements: str, *, database_url: str) -> None:
    run(
        [
            str(client_tool("psql")),
            "-X",
            "--set=ON_ERROR_STOP=1",
            f"--dbname={database_url}",
            f"--command={statements}",
        ]
    )


def read_catalog(database_url: str, query: CatalogQuery) -> list[str]:
    answer = subprocess.run(
        [
            str(client_tool("psql")),
            "-X",
            "--no-align",
            "--tuples-only",
            f"--field-separator={FIELD_SEPARATOR}",
            "--set=ON_ERROR_STOP=1",
            f"--dbname={database_url}",
            "--command",
            query,
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return sorted(line for line in answer.splitlines() if line.strip())


def compare(deployed_url: str, fresh_url: str) -> list[Drift]:
    drift = []
    for catalog, query in CATALOG_QUERIES.items():
        deployed = read_catalog(deployed_url, query)
        fresh = read_catalog(fresh_url, query)
        only_deployed = tuple(
            row.replace(FIELD_SEPARATOR, " | ") for row in deployed if row not in fresh
        )
        only_fresh = tuple(
            row.replace(FIELD_SEPARATOR, " | ") for row in fresh if row not in deployed
        )
        if only_deployed or only_fresh:
            drift.append(Drift(catalog, only_deployed, only_fresh))
        else:
            print(f"==> {catalog}: identical ({len(deployed)} rows)", file=sys.stderr)
    return drift


def verify(dump: Path, *, database_url: str, keep: bool = False) -> None:
    """Rehearse the cutover on a copy of the deployment, and read both schemas."""
    deployed_url = db_dump.restore(
        dump, database=DEPLOYED_DATABASE, database_url=database_url
    )
    apply_sql(CUTOVER, database_url=deployed_url)
    manage("migrate", "--fake", "games", "0001_initial", database_url=deployed_url)
    #: Every other app's history is untouched, and the copy has already applied
    #: it. This proves that, rather than assuming it.
    manage("migrate", "--check", database_url=deployed_url)

    fresh_url = create_database(FRESH_DATABASE, database_url)
    manage("migrate", database_url=fresh_url)

    drift = compare(deployed_url, fresh_url)
    if drift:
        print(
            f"\n{dump} does not reach the schema 0001_initial builds.\n",
            file=sys.stderr,
        )
        for finding in drift:
            print(finding.report(), file=sys.stderr)
        raise DumpError(
            f"{sum(len(f.only_deployed) + len(f.only_fresh) for f in drift)} "
            "catalog row(s) differ."
        )
    if not keep:
        for database in (DEPLOYED_DATABASE, FRESH_DATABASE):
            drop_database(database, database_url)
    print(
        f"==> {dump} carries over to 0001_initial with no drift.",
        file=sys.stderr,
    )
    if keep:
        print(f"==> Deployment copy kept:  {deployed_url}", file=sys.stderr)
        print(f"==> Fresh build kept:      {fresh_url}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    operations = parser.add_subparsers(dest="operation", required=True)
    verify_parser = operations.add_parser(
        "verify", help="rehearse the cutover and compare both schemas"
    )
    verify_parser.add_argument("--dump", type=Path)
    verify_parser.add_argument("--keep", action="store_true")
    operations.add_parser(
        "cutover", help="print the statements the deployment needs, and stop"
    )
    arguments = parser.parse_args()

    try:
        if arguments.operation == "cutover":
            print(CUTOVER)
            return
        database_url = db_dump.local_database_url()
        dump = arguments.dump or db_dump.newest_dump(db_dump.dump_directory())
        verify(dump, database_url=database_url, keep=arguments.keep)
    except DumpError as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    except subprocess.CalledProcessError as error:
        print(f"error: {' '.join(error.cmd)} failed.", file=sys.stderr)
        raise SystemExit(error.returncode or 1) from error


if __name__ == "__main__":
    main()
