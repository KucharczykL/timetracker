# A dump restores whatever schema it carries

**Issue:** [#972](https://github.com/KucharczykL/timetracker/issues/972)
**Date:** 2026-09-02

## The failure

`make restore-dump` against a dump of the deployed database stops on the first
temporal value:

```text
pg_restore: error: COPY failed for table "probe": ERROR:  value for domain
public.temporal_value violates check constraint "temporal_value_valid"
CONTEXT:  COPY probe, line 1, column value: "2026"
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
it restore in one command, so the reported instance ends with that deploy.

Two things outlive it.

**Dumps already written stay unreadable.** A dump is a backup. Every `.dump`
file on disk today was taken from the 0022 schema and always will be, so the
disaster it exists for is the one case where this failure costs something. The
pre-deploy rehearsal is the smaller reason to act; retained backups are the
larger one.

**The shape recurs.** Any later migration that corrects a function reachable
from a domain `CHECK` breaks the load of every dump taken before it, with the
same message pointing at the same innocent row.

## What was measured

The design below was run before it was written. A scratch database received
`0017_temporal_value_domain`'s `CREATE_TEMPORAL_VALUE_DOMAIN` verbatim, a table
`probe (value temporal_value)`, and the rows `2026`, `1984-05`, `199X`. All
twelve functions in `public` had `proconfig IS NULL`, which is the 0022 schema's
condition.

| Path | Result |
|---|---|
| One `pg_restore --exit-on-error` | Fails: `violates check constraint "temporal_value_valid"`, `COPY probe, line 1, column value: "2026"` |
| pre-data, repair, data, post-data | Loads. All three rows present |
| Repair run twice | Second run matches no function and alters nothing |
| Reach given to `timetracker_temporal_is_valid` alone | Data section loads |

The last row confirms the mechanism the fix depends on: a function's
`SET search_path` stays in effect for the calls it makes, so the helpers inherit
it. It also confirms that the manual workaround in `docs/deployment.md` is
sound.

## Design

### The restore loads in four steps

`restore()` in `scripts/db_dump.py` issues one `pg_restore` today. It becomes:

```text
pg_restore --section=pre-data     domain, functions, tables
psql -f REACH_THE_HELPERS         the repair
pg_restore --section=data         COPY, where the domain check runs
pg_restore --section=post-data    indexes, constraints
```

Each `pg_restore` keeps `--exit-on-error --no-owner --no-privileges`. These
three sections are the whole archive; the split changes what a load can
interrupt, not what it writes.

The repair uses `ALTER FUNCTION`, so the setting belongs to the function rather
than the session. That is what carries it across the section boundary, since
each `pg_restore` opens its own session and each session starts with the empty
`search_path` the dump sets.

### The repair states no function body

```sql
DO $$
DECLARE fn record;
BEGIN
  FOR fn IN
    SELECT p.oid::regprocedure AS signature
    FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'public'
      AND p.prokind = 'f'
      AND NOT EXISTS (
        SELECT 1 FROM unnest(coalesce(p.proconfig, '{}')) AS s
        WHERE s LIKE 'search\_path=%')
  LOOP
    EXECUTE format(
      'ALTER FUNCTION %s SET search_path = pg_catalog, public', fn.signature);
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

`prokind = 'f'` is required: `ALTER FUNCTION` refuses an aggregate or a
procedure. `search\_path` escapes the underscore, which `LIKE` would otherwise
read as a wildcard.

### The filter names no function

The `WHERE` clause tests one thing — a function in `public` with no
`search_path` of its own. It does not test the name.

A name test would reopen the shape on the day a migration adds a function
outside the `timetracker_temporal_*` prefix. The hazard belongs to any `public`
function a domain `CHECK` or a generated column reaches while data loads, and
nothing about the name predicts that.

The breadth costs nothing today, because `public` holds only these twelve
functions. `0002_uuid_v7_domain`'s check calls `uuid_extract_version`, a builtin
in `pg_catalog`, which an empty `search_path` still reaches — `pg_catalog` is
searched whether or not the path names it.

The target is a scratch database that is dropped or migrated straight
afterwards, so a wider setting than strictly needed reaches nothing that
outlives the verification.

## Testing

Two layers, because they answer different questions.

**The four steps issue in order** — `tests/test_db_dump.py`, in the
monkeypatched-`run` idiom the file already uses for its twenty-odd command-shape
tests. That the repair falls between pre-data and data is its own assertion:
after data is too late, and it is the ordering a later edit would get wrong.
`test_restore_hands_pg_restore_the_documented_flags` asserts a single
invocation today and is rewritten.

**The load works** — a new file, against a real cluster, building the fixture
measured above: 0017's constant, a `probe` table, three values, `pg_dump
--format=custom`, then `restore()`.

It asserts in both directions. Through `restore()` the rows load. Through one
plain `pg_restore` the load fails with the domain message. Without the second
assertion the test cannot show that it reproduces #972, and a repair that had
stopped working would pass it.

The fixture applies `CREATE_TEMPORAL_VALUE_DOMAIN` imported from
`games/migrations/0017_temporal_value_domain.py` rather than migrating. Reading
a frozen migration's constant is sound — it is the historical record, and the
record is the thing under test. The alternative, migrating to 0018, costs
eighteen migrations and an `INSERT` satisfying `games_game`'s columns as of that
node, to reach the same domain and the same functions.

Note for the plan: the issue says to migrate to 0017. A database at 0017 dumps
and loads cleanly, because 0017 creates the domain and no column uses it. The
first temporal columns arrive in `0018_catalog_hierarchy`.

Scratch database names carry the xdist worker id. Both are dropped in a
`finally`. The module skips when `client_tool` cannot find the client programs,
as `tests/test_filter_tree_contract.py` skips on its absent artifact.

## Documentation

`docs/deployment.md` has a subsection, "Dumps taken before migration 0034",
teaching a manual three-section load. The raw commands stay: the section they
sit in serves an operator holding only a shell, and that operator still needs
them.

What changes is the standing of it. The subsection states that
`make restore-dump` and `make verify-dump` give the dump's functions their reach
before loading data, and why a dump needs it. The paragraph on the `make`
targets gains one sentence saying the same. The text stops reading as a
workaround awaiting a deploy.

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

**A section boundary is a new place to stop.** A failure between pre-data and
data leaves a scratch database holding a schema and no rows, where today it
holds nothing. The scratch database is already dropped and recreated by the next
run, and `verify()` already leaves a failed copy for inspection deliberately.

**`ALTER FUNCTION` needs ownership.** The restore connects as the local role and
passes `--no-owner`, so that role owns every function it just created. This does
not hold for a load into a database owned by somebody else, which
`_guard_scratch_database` already refuses for other reasons.

## Definition of done

- `restore()` loads in four steps with the repair between the first two.
- Command-shape tests cover the order; a round-trip test covers the load, in
  both directions.
- `docs/deployment.md` states what the tooling does and why.
- Full `make check`, `e2e/` included, is green.
- Closes #972.
