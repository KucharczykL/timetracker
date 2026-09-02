# Restorable Dumps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `make restore-dump` and `make verify-dump` load a dump written before `0034_temporal_functions_search_path`, so the pre-deploy rehearsal runs against the deployed database.

**Architecture:** `restore()` stops issuing one `pg_restore` and issues the dump's three sections in order, running one `psql` repair between the first two. The repair is a catalog-driven `DO` block that gives every unset non-extension function in `public` a `search_path` of its own. `ALTER FUNCTION` states reach and no body, so the tool never chooses which generation of a function body to write.

**Tech Stack:** Python 3.14, PostgreSQL 18 client programs (`pg_restore`, `psql`, `pg_dump`, `createdb`, `dropdb`), pytest, pytest-xdist.

**Spec:** `docs/superpowers/specs/2026-09-02-issue-972-restorable-dumps-design.md`

## Global Constraints

- **Drive everything through `make`.** Never `direnv exec .`, never a raw `uv run pytest` / `pnpm`. Focused runs: `make test ARGS="tests/test_db_dump.py -x"`.
- **The verification gate is the full `make check`**, `e2e/` included. `make check-fast` is for iterating and is not the gate. `ARGS` is never for the gate.
- **Python 3.14 is a hard prerequisite.** A `SyntaxError` in an `except` clause means the wrong interpreter, not broken code.
- **Name variables with complete words** — `function_row` not `fn`, `setting` not `s`, in Python and in SQL aliases alike.
- **Refused words** (`make vale` enforces them over docs *and* code comments): `heal`/`self-heal`, `fold`, `archive`/`archival`/`tombstone`, and `delete` applied to a row or record. Write `drop`, `remove`, `state`, `restate`. `dropdb` and `DELETE` as SQL are identifiers and are fine.
- **Comments use the `#:` prefix** in `scripts/db_dump.py`, matching the file.
- The repair SQL is a module constant named **`REACH_THE_HELPERS`**, after the constant `0034_temporal_functions_search_path.py` already uses for the same act.
- Commit trailer: `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

---

## Background an implementer needs

`pg_dump` writes `SELECT pg_catalog.set_config('search_path', '', false)` at the top of every dump. `0017_temporal_value_domain` created twelve functions that call each other by bare name and set no `search_path` of their own, so during a load those calls resolve to nothing. `timetracker_temporal_is_valid` has an `EXCEPTION WHEN OTHERS` handler, which reads the lookup failure as a verdict on the data, and the load stops with:

```text
value for domain public.temporal_value violates check constraint "temporal_value_valid"
```

`0034` corrected the live schema. It cannot correct a dump, because a dump carries the function bodies as they were.

Three facts settle the design, all measured:

1. **`ALTER FUNCTION` states reach and no body.** So the repair never has to pick between the three historical generations of these bodies (0017 wrote them, 0034 restated `is_valid`, 0038 restated four and added five).
2. **Every function needs reach, not just `is_valid`.** A domain `CHECK` routes through `is_valid`, so reach for that one function loads a plain column. A generated column calls `timetracker_temporal_lower` **directly** and stops with `function _timetracker_temporal_atom_lower(text) does not exist`. This is why the round-trip fixture in Task 2 must carry a generated column — the wrong repair passes a fixture without one.
3. **The data section is the one that needs the repair.** `pg_dump` writes a table `CHECK` inline in `CREATE TABLE` (pre-data), and a table with no rows validates nothing, so the constraint first runs during the `COPY`. Post-data holds keys and indexes. An expression index over these functions cannot be built at all while they are unset, so no pre-0034 dump carries one — placing the repair before the data section covers post-data at no cost.

## File Structure

| File | Responsibility |
|------|----------------|
| `scripts/db_dump.py` (modify) | Gains `REACH_THE_HELPERS`, `_load_section()`, `_reach_the_helpers()`; `restore()`'s single `pg_restore` becomes four steps. Everything else — `fetch`, `verify`, the guards, `client_tool` — is untouched. |
| `tests/test_db_dump.py` (modify) | Command-shape tests. One existing test is rewritten; three are added. Still the monkeypatched-`run` idiom; no database. |
| `tests/test_dump_restore_roundtrip.py` (create) | The only test here that touches a real cluster: builds a pre-0034 source database, dumps it, and asserts the load works through `restore()` and fails through a plain `pg_restore`. |
| `docs/deployment.md` (modify) | The operator's recipe. Replaces a manual workaround that is measurably wrong, and says what the `make` targets now do. |

The two test files split on cost and on question: one asks "are the commands right", runs in milliseconds, and is always collected; the other asks "does a dump load", needs PostgreSQL client programs, and skips without them.

---

### Task 1: The repair, and the four-step restore

**Files:**
- Modify: `scripts/db_dump.py:37` (new constant after `PROTECTED_DATABASES`), `scripts/db_dump.py:199-232` (`restore`)
- Test: `tests/test_db_dump.py:231-241` (rewritten), plus three new tests after it

**Interfaces:**
- Consumes: `run()`, `client_tool()`, `with_database()`, `_guard_scratch_database()` — all already in the module.
- Produces:
  - `REACH_THE_HELPERS: str` — module constant, the `DO` block.
  - `DUMP_SECTIONS: tuple[str, str, str]` — `("pre-data", "data", "post-data")`.
  - `_load_section(dump: Path, *, scratch_url: str, section: str) -> None`
  - `_reach_the_helpers(scratch_url: str) -> None`
  - `restore(dump, *, database, database_url) -> str` — signature unchanged; Task 2 calls it.

- [ ] **Step 1: Write the failing tests**

In `tests/test_db_dump.py`, **replace** `test_restore_hands_pg_restore_the_documented_flags` (lines 231-241) with the helper and four tests below. Leave `_recorded_restore` and every other test alone.

```python
def _section_command(url: str, dump: str, section: str) -> list[str]:
    return [
        "/tools/pg_restore",
        "--exit-on-error",
        "--no-owner",
        "--no-privileges",
        f"--section={section}",
        f"--dbname={url}",
        dump,
    ]


def test_restore_loads_each_section_with_the_documented_flags(
    tooling, monkeypatch, tmp_path
):
    commands, url = _recorded_restore(tooling, monkeypatch, tmp_path)
    dump = str(tmp_path / "timetracker.dump")

    assert commands[2] == _section_command(url, dump, "pre-data")
    assert commands[4] == _section_command(url, dump, "data")
    assert commands[5] == _section_command(url, dump, "post-data")
    assert len(commands) == 6


def test_the_repair_runs_between_the_schema_and_the_data(
    tooling, monkeypatch, tmp_path
):
    """After the data section is too late: the COPY is what fails."""
    commands, url = _recorded_restore(tooling, monkeypatch, tmp_path)

    assert commands[3] == [
        "/tools/psql",
        "-X",
        "--set=ON_ERROR_STOP=1",
        f"--dbname={url}",
        f"--command={tooling.REACH_THE_HELPERS}",
    ]


def test_a_refused_repair_stops_the_restore(tooling, monkeypatch, tmp_path):
    """psql answers a failed script with 0 unless ON_ERROR_STOP says otherwise.

    `run` uses `check=True`, so without the flag the operator would meet
    the original domain error one section later, with nothing saying the
    repair never ran.
    """
    commands, _ = _recorded_restore(tooling, monkeypatch, tmp_path)

    assert "--set=ON_ERROR_STOP=1" in commands[3]
    #: -X skips the operator's ~/.psqlrc, one more blank this module fills.
    assert "-X" in commands[3]


def test_the_repair_names_no_function(tooling):
    """A name test would miss whatever a later migration adds.

    The hazard belongs to any public function a domain CHECK or a
    generated column reaches during a load, and the name does not
    predict that.
    """
    block = tooling.REACH_THE_HELPERS

    assert "timetracker_temporal" not in block
    #: ALTER FUNCTION refuses an aggregate or a procedure.
    assert "prokind = 'f'" in block
    #: An extension's functions are its own business.
    assert "deptype = 'e'" in block
    #: Unescaped, LIKE would read the underscore as a wildcard.
    assert r"search\_path=%" in block
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `make test ARGS="tests/test_db_dump.py -x -q"`

Expected: `test_restore_loads_each_section_with_the_documented_flags` fails first — `commands` has 3 entries, not 6, and `commands[2]` carries no `--section`. `test_the_repair_names_no_function` fails with `AttributeError: module 'db_dump' has no attribute 'REACH_THE_HELPERS'`.

- [ ] **Step 3: Add the constant**

In `scripts/db_dump.py`, immediately after `PROTECTED_DATABASES` (line 37), add:

```python
#: `pg_dump` opens every session with an empty `search_path`, thus a
#: function that calls its helpers by bare name reaches nothing while
#: the data loads: `timetracker_temporal_is_valid` catches the lookup
#: failure and the domain answers that the value itself is invalid.
#: `0017_temporal_value_domain` wrote twelve such functions, and a dump
#: carries the bodies as they were, thus `0034` could not correct one.
#:
#: `ALTER FUNCTION` states reach and no body, so this loads a dump of
#: any age without choosing which generation of a body to write. It
#: names no function on purpose: the hazard belongs to whatever a
#: domain CHECK or a generated column reaches, which a name does not
#: predict. An extension's functions are its own business.
REACH_THE_HELPERS = r"""
DO $$
DECLARE
    function_row record;
    functions_reached integer := 0;
BEGIN
    FOR function_row IN
        SELECT candidate.oid::regprocedure AS signature
        FROM pg_proc AS candidate
        JOIN pg_namespace AS schema_entry ON schema_entry.oid = candidate.pronamespace
        WHERE schema_entry.nspname = 'public'
          AND candidate.prokind = 'f'
          AND NOT EXISTS (
              SELECT 1
              FROM unnest(coalesce(candidate.proconfig, '{}'::text[])) AS setting
              WHERE setting LIKE 'search\_path=%')
          AND NOT EXISTS (
              SELECT 1 FROM pg_depend
              WHERE objid = candidate.oid
                AND classid = 'pg_proc'::regclass
                AND deptype = 'e')
    LOOP
        EXECUTE format(
            'ALTER FUNCTION %s SET search_path = pg_catalog, public',
            function_row.signature);
        functions_reached := functions_reached + 1;
    END LOOP;
    RAISE NOTICE 'Gave % function(s) their own search_path.', functions_reached;
END
$$;
""".strip()

#: An exact partition of the dump: verified on the local database at
#: 0040, 68 + 49 + 157 = 274 entries, none in two sections and none in
#: neither.
DUMP_SECTIONS = ("pre-data", "data", "post-data")
```

The `r"""` prefix matters: `search\_path` is not a recognized Python escape and a plain string would warn.

- [ ] **Step 4: Add the two helpers**

In `scripts/db_dump.py`, immediately **before** `def restore(` (line 199), add:

```python
def _load_section(dump: Path, *, scratch_url: str, section: str) -> None:
    """Load one section of the dump into the scratch database."""
    run(
        [
            str(client_tool("pg_restore")),
            "--exit-on-error",
            "--no-owner",
            "--no-privileges",
            f"--section={section}",
            f"--dbname={scratch_url}",
            str(dump),
        ]
    )


def _reach_the_helpers(scratch_url: str) -> None:
    """Give every function the dump created a `search_path` of its own.

    `psql` answers a failed script with 0 unless `ON_ERROR_STOP` says
    otherwise, and `run` reads that as success, thus without the flag a
    refused repair would surface as the original domain error one
    section later. `--no-owner` above means the restoring role owns
    every function the load created, which is what `ALTER FUNCTION`
    asks for.
    """
    run(
        [
            str(client_tool("psql")),
            "-X",
            "--set=ON_ERROR_STOP=1",
            f"--dbname={scratch_url}",
            f"--command={REACH_THE_HELPERS}",
        ]
    )
```

- [ ] **Step 5: Rewrite the tail of `restore()`**

In `scripts/db_dump.py`, replace the single `pg_restore` call (lines 222-231) with:

```python
    #: The functions get their reach between the schema and the data:
    #: the domain check and the generated columns first run during the
    #: COPY, and each pg_restore opens its own session under the empty
    #: search_path the dump sets. ALTER FUNCTION is what carries the
    #: setting across that boundary.
    _load_section(dump, scratch_url=scratch_url, section=DUMP_SECTIONS[0])
    _reach_the_helpers(scratch_url)
    for section in DUMP_SECTIONS[1:]:
        _load_section(dump, scratch_url=scratch_url, section=section)
    return scratch_url
```

- [ ] **Step 6: Run the tests and watch them pass**

Run: `make test ARGS="tests/test_db_dump.py -q"`

Expected: all pass, including the untouched `verify` tests — those monkeypatch `restore` itself, so the new step count cannot reach them.

- [ ] **Step 7: Lint, format, and typecheck**

Run: `make lint && make format-check && make typecheck`

Expected: clean. If `format-check` objects to the constant, run `make format` and re-read the diff — ruff must not have altered the SQL string's content, only surrounding code.

- [ ] **Step 8: Commit**

```bash
git add scripts/db_dump.py tests/test_db_dump.py
git commit -m "Give a dump's functions their reach before the data loads

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: The round-trip proof against a real cluster

Task 1's tests assert the commands. None of them proves a dump loads. This task builds a database shaped like the deployed one before `0034`, dumps it, and asserts both directions.

**Files:**
- Create: `tests/test_dump_restore_roundtrip.py`
- Read (do not modify): `games/migrations/0017_temporal_value_domain.py`

**Interfaces:**
- Consumes from Task 1: `restore(dump, *, database, database_url) -> str`, and the module attributes `local_database_url()`, `with_database()`, `client_tool()`, `run()`, `DumpError`, `REQUIRED_ENCODING`, `REQUIRED_BUILTIN_LOCALE`.
- Produces: nothing other tasks use.

**Measured values this test asserts** (run against the real functions, do not re-derive):

| value | `timetracker_temporal_lower` | `timetracker_temporal_precision` | `timetracker_temporal_kind` |
|-------|------------------------------|----------------------------------|------------------------------|
| `2026` | `2026-01-01` | `year` | `atomic` |
| `1984-05` | `1984-05-01` | `month` | `atomic` |
| `199X` | `1990-01-01` | `decade` | `atomic` |

`kind` is `atomic` for all three — it separates an atomic value from a range, so it is used for the `CHECK` and never as a discriminating assertion.

- [ ] **Step 1: Write the test module**

Create `tests/test_dump_restore_roundtrip.py`:

```python
"""A dump written before migration 0034 loads through `restore()` (#972).

`0017_temporal_value_domain` created twelve functions that call their
helpers by bare name and carry no `search_path` of their own. A dump
opens every session with an empty one, so during a load those calls
reach nothing: `timetracker_temporal_is_valid` catches the lookup
failure and the domain answers that the value is invalid.

The fixture is the smallest schema that tells a working repair from a
broken one. A domain CHECK routes through `is_valid`, so reach for that
one function loads a plain column and then stops on a generated column,
which calls `timetracker_temporal_lower` directly. A fixture with no
generated column passes under the wrong repair, which is the repair
`docs/deployment.md` used to teach.

There is no expression index here. One cannot be built while its
function is unset, so no dump this tool must load carries one, and a
fixture holding one would prove something about a database that cannot
exist.
"""

import importlib.util
import os
import subprocess
import sys
from importlib import import_module
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).parents[1]
TOOLING_PATH = REPOSITORY / "scripts" / "db_dump.py"
CLIENT_PROGRAMS = ("createdb", "dropdb", "psql", "pg_dump", "pg_restore")

#: Each xdist worker gets its own pair, and both are dropped in a finally.
WORKER = os.environ.get("PYTEST_XDIST_WORKER", "master")
SOURCE_DATABASE = f"timetracker_dump972_source_{WORKER}"
TARGET_DATABASE = f"timetracker_dump972_target_{WORKER}"

#: `games_game` holds a bare domain column; `games_release` holds
#: generated columns over the same domain, which is the pair that tells
#: a whole repair from a partial one. The CHECK is written inline by
#: `pg_dump`, so it first runs during the COPY beside them.
PROBE_SCHEMA = """
CREATE TABLE probe_game (
    id integer PRIMARY KEY,
    original_release_date temporal_value
);

CREATE TABLE probe_release (
    id integer PRIMARY KEY,
    release_date temporal_value,
    release_date_lower date GENERATED ALWAYS AS (
        timetracker_temporal_lower(release_date::text)) STORED,
    release_date_precision text GENERATED ALWAYS AS (
        timetracker_temporal_precision(release_date::text)) STORED,
    CONSTRAINT probe_release_is_atomic
        CHECK (timetracker_temporal_kind(release_date::text) = 'atomic')
);

INSERT INTO probe_game (id, original_release_date)
    VALUES (1, '2026'), (2, '1984-05'), (3, '199X');
INSERT INTO probe_release (id, release_date)
    VALUES (1, '2026'), (2, '199X');
"""

DOMAIN_REFUSAL = "violates check constraint"


def _apply(tooling, database_url: str, statements: str) -> None:
    tooling.run(
        [
            str(tooling.client_tool("psql")),
            "-X",
            "--set=ON_ERROR_STOP=1",
            "--quiet",
            f"--dbname={database_url}",
            f"--command={statements}",
        ]
    )


def _drop(tooling, maintenance: str, database: str) -> None:
    tooling.run(
        [str(tooling.client_tool("dropdb")), maintenance, "--if-exists", database]
    )


def _create(tooling, maintenance: str, database: str) -> None:
    tooling.run(
        [
            str(tooling.client_tool("createdb")),
            maintenance,
            "--template=template0",
            f"--encoding={tooling.REQUIRED_ENCODING}",
            "--locale-provider=builtin",
            f"--builtin-locale={tooling.REQUIRED_BUILTIN_LOCALE}",
            database,
        ]
    )


def _rows(tooling, database_url: str, query: str) -> list[str]:
    """Every row of a one-or-more column query, as psql's `-At` writes it."""
    finished = subprocess.run(
        [
            str(tooling.client_tool("psql")),
            "-X",
            "-At",
            f"--dbname={database_url}",
            f"--command={query}",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return finished.stdout.split()


@pytest.fixture(scope="module")
def tooling():
    """`scripts/db_dump.py`, skipping the module if a client program is absent."""
    specification = importlib.util.spec_from_file_location(
        "db_dump_roundtrip", TOOLING_PATH
    )
    assert specification and specification.loader
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    for name in CLIENT_PROGRAMS:
        try:
            module.client_tool(name)
        except module.DumpError as absent:
            pytest.skip(str(absent))
    return module


@pytest.fixture(scope="module")
def pre_0034_dump(tooling, tmp_path_factory):
    """A dump of a schema whose functions carry no `search_path`.

    The domain SQL is read from the frozen migration rather than
    migrated to. The migration is the historical record, and the record
    is the thing under test; reaching the same state by migrating costs
    eighteen nodes and an INSERT satisfying `games_game` as of 0018.
    """
    domain_sql = import_module(
        "games.migrations.0017_temporal_value_domain"
    ).CREATE_TEMPORAL_VALUE_DOMAIN
    database_url = tooling.local_database_url()
    maintenance = f"--maintenance-db={tooling.with_database(database_url, 'postgres')}"
    source_url = tooling.with_database(database_url, SOURCE_DATABASE)
    dump = tmp_path_factory.mktemp("dump972") / "pre-0034.dump"
    _drop(tooling, maintenance, SOURCE_DATABASE)
    try:
        _create(tooling, maintenance, SOURCE_DATABASE)
        _apply(tooling, source_url, domain_sql)
        _apply(tooling, source_url, PROBE_SCHEMA)
        tooling.run(
            [
                str(tooling.client_tool("pg_dump")),
                source_url,
                "--format=custom",
                "--no-owner",
                "--no-privileges",
                f"--file={dump}",
            ]
        )
        yield dump
    finally:
        _drop(tooling, maintenance, SOURCE_DATABASE)


@pytest.fixture
def scratch(tooling):
    """Drop the target before and after, whatever the test did to it."""
    database_url = tooling.local_database_url()
    maintenance = f"--maintenance-db={tooling.with_database(database_url, 'postgres')}"
    _drop(tooling, maintenance, TARGET_DATABASE)
    try:
        yield database_url
    finally:
        _drop(tooling, maintenance, TARGET_DATABASE)


def test_the_fixture_reproduces_the_reported_failure(tooling, pre_0034_dump, scratch):
    """One pg_restore still fails, which is what #972 reports.

    Without this the passing test below could not show that it loads a
    dump that used to refuse, and a repair that had stopped working
    would go unnoticed.
    """
    maintenance = f"--maintenance-db={tooling.with_database(scratch, 'postgres')}"
    _create(tooling, maintenance, TARGET_DATABASE)

    finished = subprocess.run(
        [
            str(tooling.client_tool("pg_restore")),
            "--exit-on-error",
            "--no-owner",
            "--no-privileges",
            f"--dbname={tooling.with_database(scratch, TARGET_DATABASE)}",
            str(pre_0034_dump),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert finished.returncode != 0
    assert DOMAIN_REFUSAL in finished.stderr
    assert "temporal_value" in finished.stderr


def test_restore_loads_a_dump_written_before_0034(tooling, pre_0034_dump, scratch):
    scratch_url = tooling.restore(
        pre_0034_dump, database=TARGET_DATABASE, database_url=scratch
    )

    assert _rows(tooling, scratch_url, "SELECT count(*) FROM probe_game") == ["3"]
    assert _rows(tooling, scratch_url, "SELECT count(*) FROM probe_release") == ["2"]


def test_the_generated_columns_hold_their_computed_values(
    tooling, pre_0034_dump, scratch
):
    """A repair reaching `is_valid` alone loads the plain column and stops here."""
    scratch_url = tooling.restore(
        pre_0034_dump, database=TARGET_DATABASE, database_url=scratch
    )

    assert _rows(
        tooling,
        scratch_url,
        "SELECT release_date_lower, release_date_precision"
        " FROM probe_release ORDER BY id",
    ) == ["2026-01-01|year", "1990-01-01|decade"]


def test_every_function_in_the_copy_carries_its_own_reach(
    tooling, pre_0034_dump, scratch
):
    scratch_url = tooling.restore(
        pre_0034_dump, database=TARGET_DATABASE, database_url=scratch
    )

    assert _rows(
        tooling,
        scratch_url,
        "SELECT count(*) FROM pg_proc AS candidate"
        " JOIN pg_namespace AS schema_entry"
        " ON schema_entry.oid = candidate.pronamespace"
        " WHERE schema_entry.nspname = 'public'"
        " AND candidate.prokind = 'f' AND candidate.proconfig IS NULL",
    ) == ["0"]
```

- [ ] **Step 2: Run the module**

Run: `make test ARGS="tests/test_dump_restore_roundtrip.py -q -p no:randomly"`

Expected: 4 passed. If it skips, the machine has no PostgreSQL client programs — run `make ensure-postgres` and retry.

- [ ] **Step 3: Prove the test has teeth**

The test would also pass if `restore()` never needed repairing. Confirm it fails without the repair:

In `scripts/db_dump.py`, temporarily comment out the `_reach_the_helpers(scratch_url)` line inside `restore()`, then run:

`make test ARGS="tests/test_dump_restore_roundtrip.py -q"`

Expected: `test_the_fixture_reproduces_the_reported_failure` still passes; the other three fail with `CalledProcessError` from the data section, and the captured stderr names `violates check constraint "temporal_value_valid"`.

Then restore the line. This step changes no committed file.

- [ ] **Step 4: Run the module again**

Run: `make test ARGS="tests/test_dump_restore_roundtrip.py -q"`

Expected: 4 passed.

- [ ] **Step 5: Confirm no scratch database was left behind**

```bash
psql "$(uv run --frozen python -c 'import os;print(os.environ["DATABASE_URL"])' 2>/dev/null || echo postgres)" \
  -Atc "SELECT datname FROM pg_database WHERE datname LIKE 'timetracker_dump972%'"
```

Expected: no rows. If the command cannot resolve a URL, use the one `make restore-dump` prints.

- [ ] **Step 6: Lint, format, typecheck**

Run: `make lint && make format-check && make typecheck`

- [ ] **Step 7: Commit**

```bash
git add tests/test_dump_restore_roundtrip.py
git commit -m "Prove a pre-0034 dump loads, and that it used to refuse

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: The operator's recipe

`docs/deployment.md` teaches a manual load that gives reach to `timetracker_temporal_is_valid` alone. Measured, that recipe part-loads a production dump and then stops on the first generated column with a *second* misleading message. It is replaced by the same block the tool runs, so the operator and the tool do the same thing.

**Files:**
- Modify: `docs/deployment.md:72-87` (a pointer), `docs/deployment.md:89-105` (one sentence), `docs/deployment.md:110-137` (the recipe)

**Interfaces:** none — prose only.

- [ ] **Step 1: Replace the pre-0034 subsection**

In `docs/deployment.md`, replace everything from `### Dumps taken before migration 0034` (line 110) through `Any dump taken after that migration restores in one command.` (line 137) with:

````markdown
### Dumps taken before migration 0034

`make restore-dump` and `make verify-dump` handle this without being asked. The
commands below are for an operator holding only a shell.

A dump opens every session with an empty `search_path`, which the
`timetracker_temporal_*` functions did not carry their own setting against until
`0034_temporal_functions_search_path`. Those functions call each other by bare
name, so during a load the calls reach nothing, and
`timetracker_temporal_is_valid` reports the lookup failure as a verdict on the
value:

```text
value for domain public.temporal_value violates check constraint "temporal_value_valid"
```

A dump carries the function bodies as they were, so migrating the source does
not make an existing dump loadable. Load it in three parts instead, and give the
functions their reach between the first two:

```bash
pg_restore --exit-on-error --no-owner --no-privileges --section=pre-data \
  --dbname="$SCRATCH_URL" /path/to/timetracker.dump

psql -X --set=ON_ERROR_STOP=1 --dbname="$SCRATCH_URL" --command="
DO \$\$
DECLARE
    function_row record;
BEGIN
    FOR function_row IN
        SELECT candidate.oid::regprocedure AS signature
        FROM pg_proc AS candidate
        JOIN pg_namespace AS schema_entry ON schema_entry.oid = candidate.pronamespace
        WHERE schema_entry.nspname = 'public'
          AND candidate.prokind = 'f'
          AND candidate.proconfig IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM pg_depend
              WHERE objid = candidate.oid
                AND classid = 'pg_proc'::regclass
                AND deptype = 'e')
    LOOP
        EXECUTE format(
            'ALTER FUNCTION %s SET search_path = pg_catalog, public',
            function_row.signature);
    END LOOP;
END
\$\$;"

pg_restore --exit-on-error --no-owner --no-privileges --section=data \
  --dbname="$SCRATCH_URL" /path/to/timetracker.dump
pg_restore --exit-on-error --no-owner --no-privileges --section=post-data \
  --dbname="$SCRATCH_URL" /path/to/timetracker.dump
```

Every function needs the setting, not only `timetracker_temporal_is_valid`. A
domain check routes through that one function, but a generated column calls
`timetracker_temporal_lower` directly, so naming `is_valid` alone loads the
plain columns and then stops on the first generated one.

`ALTER FUNCTION` changes reach and no function body, so this is safe on a dump
of any age. Migrating the copy afterwards makes the setting permanent. Any dump
taken after `0034` loads in one command.
````

Two details are deliberate. `--set=ON_ERROR_STOP=1` is what makes a refused
repair stop the shell pipeline — `psql` otherwise exits 0 on a failed script.
`proconfig IS NULL` stands in for the tool's escaped `LIKE` test because it
reads better in a document and is exactly right for a dump of this vintage,
where no function has any setting at all.

- [ ] **Step 2: Point the earlier recipe at it**

In `docs/deployment.md`, after the code block that ends at line 87 (the
`dropdb` in "Isolated restore verification"), add:

```markdown
A dump taken before `0034_temporal_functions_search_path` needs more than this
one `pg_restore`; see [Dumps taken before migration
0034](#dumps-taken-before-migration-0034).
```

- [ ] **Step 3: Say what the targets do**

In `docs/deployment.md`, in the "From a checkout" paragraph, after the sentence
ending `A restore refuses to name the development database or a maintenance
one.` (line 100), add:

```markdown
Both targets load the dump in three sections and give its functions their
`search_path` between the first two, so a dump taken before
`0034_temporal_functions_search_path` needs no special handling.
```

- [ ] **Step 4: Lint the prose**

Run: `make vale`

Expected: no new findings. The file must not gain `archive`, `tombstone`, `fold`,
`heal`, or `delete` applied to a row. Seven warnings elsewhere in the tree are
pre-existing — compare against `git stash`-ed output if unsure.

- [ ] **Step 5: Commit**

```bash
git add docs/deployment.md
git commit -m "Teach the load that works, not the one that part-loads

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: The gate

**Files:** none expected; this task exists to run the full gate and fix whatever it finds.

- [ ] **Step 1: Run the full check**

Run: `make check`

This is lint + format-check + mypy + vale + ts-check + icons + migrations + vitest + the entire pytest suite **including `e2e/`**. It takes roughly 6.5 minutes serial, under a minute at 16 workers. Do not substitute `make check-fast`, and do not pass `ARGS`.

Expected: green.

- [ ] **Step 2: Fix anything it finds, then run it again**

If `make check` is red, fix the cause and re-run the whole target, not the
failing file. A `SyntaxError` in an `except` clause means the interpreter is not
3.14 — check `python --version` before suspecting the code.

- [ ] **Step 3: Confirm the scratch databases are gone**

The round-trip module drops both of its databases in a `finally`, but a killed
run can leave one. Confirm none survived the parallel suite:

```bash
psql -Atc "SELECT datname FROM pg_database WHERE datname LIKE 'timetracker_dump972%'"
```

Expected: no rows.

- [ ] **Step 4: Commit anything the gate moved**

```bash
git status --porcelain
```

If the tree is clean, there is nothing to commit. Otherwise commit the fixes
with a message naming what the gate objected to.

---

## Self-Review

**Spec coverage.** Every section of the spec maps to a task:

| Spec section | Task |
|---|---|
| Design — the four steps | 1 |
| Design — the `DO` block, the three earned clauses | 1 (constant), 1 Step 1 (`test_the_repair_names_no_function`) |
| Design — the filter names no function | 1 |
| Design — how the repair is invoked (`-X`, `ON_ERROR_STOP`, `--command`) | 1 |
| Testing — the four steps issue in order | 1 |
| Testing — the load works, in both directions | 2 |
| Testing — fixture reads 0017's constant, xdist-suffixed names, `finally`, module skip | 2 |
| Documentation — replace the pre-0034 recipe | 3 |
| Documentation — pointer from the earlier recipe, sentence on the targets | 3 |
| Risks — the repair reports no count | 1 (`RAISE NOTICE` in the block) |
| Definition of done — full `make check` green | 4 |

**Type consistency.** `REACH_THE_HELPERS`, `DUMP_SECTIONS`, `_load_section`,
`_reach_the_helpers` are spelled identically in Task 1's implementation, Task 1's
tests, and Task 2's consumption. `restore()`'s signature does not change, so
Task 2 and the untouched `verify()` both keep working.

**Not covered, by decision.** The issue's step 1 — a shared SQL module the
migration and the tool both import — is declined in the spec, for the
three-generations reason. There is no task for it.
