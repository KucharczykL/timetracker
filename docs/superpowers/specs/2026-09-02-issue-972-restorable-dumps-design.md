# A dump restores whatever schema it carries

**Issue:** [#972](https://github.com/KucharczykL/timetracker/issues/972)
**Date:** 2026-09-02

## The failure

`make restore-dump` against a dump of the deployed database stops on the first
temporal value:

```text
pg_restore: error: COPY failed for table "games_game": ERROR:  value for domain
public.temporal_value violates check constraint "temporal_value_valid"
CONTEXT:  COPY games_game, line 1, column original_release_date: "2026"
```

`2026` is a valid temporal value. The message blames the row, and the row is
fine.

`pg_dump` opens every dump it writes with an empty `search_path`.
`0017_temporal_value_domain` created twelve functions that call their helpers by
bare name and carry no `search_path` of their own, so during a load those calls
reach nothing. The `EXCEPTION WHEN OTHERS` handler in
`timetracker_temporal_is_valid` reads that lookup failure as invalid data and
answers `false`, so the domain refuses every value the dump carries.

`0034_temporal_functions_search_path` corrected the live schema. It could not
correct a dump, because a dump carries the function bodies as they were.

## Why the deployed state does not settle it

The deployed image is `main-e45911c` (2026-08-21), whose tree stops at
`0022_external_references`. Every dump that exists was therefore taken from a
schema at 0022, and every one of them carries 0017's bodies.

The next deploy carries 0023 through 0040, `0034` among them. Dumps taken after
it load in one command, so the reported instance ends with that deploy.

Two things outlive it.

**Dumps already written stay unreadable.** A dump is a backup. Every `.dump`
file on disk today was taken from the 0022 schema and always will be, so the
disaster it exists for is the one case where this failure costs something. The
pre-deploy rehearsal is the smaller reason to act; retained backups are the
larger one.

**The shape recurs, in one narrow way.** A later migration that gives a function
its `search_path` breaks the load of every dump taken before it. The scope of
that claim matters and is stated under *What this does not fix* below.

## What was measured

The design below was run before it was written, then run again after an
adversarial review, which falsified part of the first attempt. Both fixtures
applied `0017_temporal_value_domain`'s `CREATE_TEMPORAL_VALUE_DOMAIN` verbatim,
which leaves all twelve functions with `proconfig IS NULL` — the 0022 schema's
condition.

The second fixture is the one that counts. It carries the shape 0018 really
builds: a `games_game` with a bare domain column, and a `games_release` whose
`release_date_lower` and `release_date_kind` are `GENERATED ALWAYS AS ... STORED`
over `timetracker_temporal_lower` and `timetracker_temporal_kind`.

| Path | Result |
|---|---|
| One `pg_restore --exit-on-error` | Fails: `violates check constraint "temporal_value_valid"` on `"2026"` |
| pre-data, reach for **every** function, data, post-data | Loads. Generated columns recompute: `199X → 1990-01-01`, `atomic` |
| Reach for `timetracker_temporal_is_valid` **alone** | **Fails, partially loaded.** `games_game` 3 rows, `games_release` 0: `function _timetracker_temporal_atom_lower(text) does not exist` |
| Repair run twice | Second run matches no function and alters nothing |

The third row is the review's finding and it corrects this document's first
draft. A domain `CHECK` routes through `is_valid`, so giving reach to that one
function loads any table whose temporal column is plain. A generated column
calls `timetracker_temporal_lower` and `timetracker_temporal_kind` **directly**,
so each of those needs its own reach. Every function must get it.

This also condemns the manual workaround in `docs/deployment.md`, which names
`is_valid` alone and offers "apply the helper reach to every
`timetracker_temporal_*` function if the data section still fails" as a
contingency. It is not a contingency. On the real schema the narrow form loads
part of the data and then stops with a second misleading message, which is
worse than failing outright.

## Design

### The restore loads in four steps

`restore()` in `scripts/db_dump.py` issues one `pg_restore` today. It becomes:

```text
pg_restore --section=pre-data     domain, functions, tables
psql -f REACH_THE_HELPERS         the repair
pg_restore --section=data         COPY, where domain checks and generated
                                  columns run
pg_restore --section=post-data    keys and indexes
```

Each `pg_restore` keeps `--exit-on-error --no-owner --no-privileges`.

The repair uses `ALTER FUNCTION`, so the setting belongs to the function rather
than the session. That is what carries it across the section boundaries, since
each `pg_restore` opens its own session and each session starts with the empty
`search_path` the dump sets.

The data section is the one that needs it. Measured: `pg_dump` writes a table
`CHECK` constraint inline in `CREATE TABLE`, which is pre-data, and a table with
no rows validates nothing — the constraint first runs during the `COPY`, beside
the domain check and the generated columns. Post-data holds the keys and the
indexes.

Post-data can need it in principle, because `CREATE INDEX` over a function
expression runs that function under a secure `search_path` that excludes
`public`. It cannot need it in practice: measured, such an index cannot be built
at all while its function is unset (`function timetracker_temporal_lower(text)
does not exist`), so no dump written before `0034` can carry one. Placing the
repair before the data section covers post-data at no cost, and nothing is built
around a case that cannot arrive.

The three sections are an exact partition of the archive. Verified on the local
post-0040 database (274 TOC entries): `pre 68 + data 49 + post 157 = 274`, no
entry in two sections and none in neither. A single-shot load and a four-step
load into two fresh databases produced identical `pg_dump -s`, identical
`pg_dump -a`, and identical `last_value` for all fourteen sequences. The split
is equivalence-preserving for a dump that needs no repair.

One caveat carried from that check: `pg_restore` replays SECTION_NONE entries in
every `--section` run rather than once. Our dumps carry only `ENCODING`,
`STDSTRINGS` and `SEARCHPATH` there, all idempotent. If `fetch_command()` ever
gains `--create`, `CREATE DATABASE` would be attempted three times.

### The repair states no function body

```sql
DO $$
DECLARE
    function_row record;
BEGIN
    FOR function_row IN
        SELECT procedure.oid::regprocedure AS signature
        FROM pg_proc AS procedure
        JOIN pg_namespace AS namespace ON namespace.oid = procedure.pronamespace
        WHERE namespace.nspname = 'public'
          AND procedure.prokind = 'f'
          AND NOT EXISTS (
              SELECT 1
              FROM unnest(coalesce(procedure.proconfig, '{}')) AS setting
              WHERE setting LIKE 'search\_path=%')
          AND NOT EXISTS (
              SELECT 1 FROM pg_depend
              WHERE objid = procedure.oid
                AND classid = 'pg_proc'::regclass
                AND deptype = 'e')
    LOOP
        EXECUTE format(
            'ALTER FUNCTION %s SET search_path = pg_catalog, public',
            function_row.signature);
    END LOOP;
END $$;
```

`ALTER FUNCTION` changes reach and nothing else, which is the property the whole
design rests on. The tool never has to choose which generation of a body to
write, and the question does not arise.

That question is real. These bodies have three generations, not the two the
issue counts: 0017 wrote them, 0034 restated `timetracker_temporal_is_valid`,
and 0038 restated `_timetracker_temporal_atom_precision`,
`_timetracker_temporal_atom_lower`, `_timetracker_temporal_atom_upper` and
`timetracker_temporal_is_valid` again for qualifier support, adding five
functions. Those copies are distinct historical states, not duplication. A
module holding "the current SQL" that `0034` imported would stop `0034` being a
record of what ran in August, and applying 0034's `is_valid` to a dump taken
after 0038 would quietly drop the three qualifier checks from the domain.

Three clauses earn their place:

- `prokind = 'f'` — `ALTER FUNCTION` refuses an aggregate or a procedure.
- `search\_path` — the escape stops `LIKE` reading the underscore as a wildcard.
- the `pg_depend` test — an extension's functions are its own business.
  Verified: `CREATE EXTENSION pg_trgm` puts 31 unset functions in `public`, and
  without this clause the block alters all 31.

### The filter names no function

The `WHERE` clause tests one thing — a function in `public`, not owned by an
extension, with no `search_path` of its own. It does not test the name.

A name test would reopen the shape on the day a migration adds a function
outside the `timetracker_temporal_*` prefix. The hazard belongs to any `public`
function a domain `CHECK`, a generated column or an index expression reaches
during a load, and nothing about the name predicts that.

The breadth is deliberately blunt, and safe here for three reasons. Every
function this application puts in `public` wants exactly this path — verified on
the live post-0040 database, where all 17 already carry it and none is
`SECURITY DEFINER`. Extension members are excluded. And the target is a scratch
database that is dropped or migrated immediately afterwards, so a setting wider
than strictly needed reaches nothing that outlives the verification.

`--no-owner` means the restoring role owns every function the load created, so
`ALTER FUNCTION`'s ownership requirement is met without a further clause.

`0002_uuid_v7_domain` needs none of this: its check calls `uuid_extract_version`,
a builtin in `pg_catalog`, which an empty `search_path` still reaches because
`pg_catalog` is searched whether or not the path names it.

### How the repair is invoked

`psql -X --set=ON_ERROR_STOP=1 --command=<the block>`, through
`client_tool("psql")`.

Both flags are load-bearing. Measured: a plain `psql -f` **exits 0** when the
script raises, including a `DO` block that raises — `run()` uses `check=True`
and would see success. The operator would then get the original domain error
from the data section with nothing saying the repair never ran. With
`ON_ERROR_STOP=1` the same failure exits 3. `-X` skips the user's `~/.psqlrc`,
which is a blank this module exists to fill.

The SQL lives as a module constant `REACH_THE_HELPERS` in `scripts/db_dump.py`,
named after the constant `0034` already uses for the same act, and is passed
with `--command`, since `run()` builds an argument list and opens no stdin.

## Testing

Two layers, because they answer different questions.

**The four steps issue in order** — `tests/test_db_dump.py`, in the
monkeypatched-`run` idiom the file already uses for its command-shape tests.
That the repair falls between pre-data and data is its own assertion: after data
is too late, and it is the ordering a later edit would get wrong. That the psql
invocation carries `ON_ERROR_STOP` is also its own assertion, since without it a
failure is silent. `test_restore_hands_pg_restore_the_documented_flags` asserts
a single invocation today and is rewritten.

**The load works** — a new file, against a real cluster, building the second
fixture measured above, not the first. It applies 0017's constant, then:

- `games_game`-shaped: a bare `temporal_value` column.
- `games_release`-shaped: a `GENERATED ALWAYS AS ... STORED` column over
  `timetracker_temporal_lower`, and one over `timetracker_temporal_kind`.
- a `CHECK` constraint over `timetracker_temporal_kind`, which `pg_dump` writes
  inline in `CREATE TABLE` and which therefore first runs during the `COPY`.

No expression index: one cannot be built while its function is unset, so no dump
this tool must load carries one, and a fixture holding one would prove something
about a database that cannot exist.

The generated column is not garnish. A repair that gave reach to `is_valid`
alone passes a fixture without one and fails a production dump; that is exactly
the wrong repair this test exists to reject.

It asserts in both directions. Through `restore()` the rows load and the
generated columns hold the right values. Through one plain `pg_restore` the load
fails with the domain message. Without the second assertion the test cannot show
that it reproduces #972, and a repair that had stopped working would pass it.

The fixture applies `CREATE_TEMPORAL_VALUE_DOMAIN` imported from
`games/migrations/0017_temporal_value_domain.py` rather than migrating. Reading
a frozen migration's constant is sound — it is the historical record, and the
record is the thing under test. The alternative, migrating to 0018, costs
eighteen migrations and an `INSERT` satisfying `games_game`'s columns as of that
node, to reach the same domain and the same functions.

Note for the plan: the issue says to migrate to 0017. A database at 0017 dumps
and loads cleanly — verified — because 0017 creates the domain and no column
uses it. The first temporal columns arrive in `0018_catalog_hierarchy`.

Scratch database names carry the xdist worker id. Both are dropped in a
`finally`. The module skips when `client_tool` cannot find the client programs,
`psql` among them, as `tests/test_filter_tree_contract.py` skips on its absent
artifact.

## Documentation

`docs/deployment.md` has a subsection, "Dumps taken before migration 0034",
teaching a manual load that gives reach to `is_valid` alone. That recipe is
wrong, as measured above, and is replaced by the same `DO` block the tooling
runs, so the shell operator and the tool do the same thing. The raw commands
stay: the section they sit in serves an operator holding only a shell, and that
operator still needs them.

The subsection then states that `make restore-dump` and `make verify-dump` do
this without being asked, and why a dump needs it. The paragraph on the `make`
targets gains one sentence saying the same.

The earlier "Isolated restore verification" recipe is a single `pg_restore` and
stays broken for a pre-0034 dump. It gains a pointer to the subsection.

## What this does not fix

The repair restores **reach**, and only reach. The issue's step 1 — one module
of function SQL that the migration and the tool share — is declined, for the
three-generations reason above.

So the recurring shape is narrower than "any later migration that corrects a
function reachable from a domain `CHECK`". A migration that corrects a *body* —
a wrong regex in `_atom_precision`, say — still leaves old dumps loading under
old semantics, and a function that fails for any reason other than reach still
produces the same misleading domain message. Closing #972 buys the search_path
subclass, which is the one that has actually happened.

## Out of scope

- Deploying 0023 through 0040. This makes the rehearsal available; running it is
  the deploy's business.
- `make anonymize-sample`, which reads a restored production database and gains
  a working `restore()` at no cost.
- The `EXCEPTION WHEN OTHERS` handler that turned a lookup failure into a verdict
  on the data. `0034` narrowed it for the live schema, and the migrate step after
  a restore applies that. A restore does not rewrite it, because a restore
  states no bodies.

## Risks

**A section boundary is a new place to stop.** A failure in the data section
already leaves rows in every table loaded before the failing one, so partial
state is not new. What is new is a failure between sections, which leaves a
schema and no rows. The scratch database is dropped and recreated by the next
run, and `verify()` already leaves a failed copy for inspection deliberately.

**The repair is silent about what it changed.** It reports no count. An operator
reading a later failure cannot tell from the output whether the block matched
anything. Printing the number of functions given reach is cheap and belongs in
the plan.

## Definition of done

- `restore()` loads in four steps with the repair between the first two, invoked
  so that a failure in it stops the restore.
- Command-shape tests cover the order and the `ON_ERROR_STOP` flag; a round-trip
  test covers the load in both directions, with a generated column in the
  fixture.
- `docs/deployment.md` teaches a recipe that works, and states what the tooling
  does.
- Full `make check`, `e2e/` included, is green.
- Closes #972.
