# Loading a dump that predates migration 0034

`pg_dump` starts each session with an empty `search_path`. Migration
`0017_temporal_value_domain` made twelve functions that call their helpers by
bare name. These functions have no `search_path` of their own. During a load,
the calls find nothing. `timetracker_temporal_is_valid` catches the failure, and
the domain reports that the value is incorrect:

```text
value for domain public.temporal_value violates check constraint "temporal_value_valid"
```

Migration `0034_temporal_functions_search_path` corrects the live schema. It
does not correct a dump. A dump holds the function bodies as they were.

## The load

`restore()` in `scripts/db_dump.py` loads a dump in four steps.

1. `pg_restore --section=pre-data`
2. `psql --command=<REACH_THE_HELPERS>`
3. `pg_restore --section=data`
4. `pg_restore --section=post-data`

Each `pg_restore` keeps `--exit-on-error --no-owner --no-privileges`. Each step
opens a new session with the empty `search_path` of the dump. `ALTER FUNCTION`
attaches the setting to the function, thus the setting stays across the step
boundaries.

The data section is the section that needs the repair. `pg_dump` writes a table
`CHECK` inside `CREATE TABLE`, which is pre-data. A table with no rows validates
nothing, thus the constraint first runs during the `COPY`, with the domain check
and the generated columns.

Post-data holds the keys and the indexes. An expression index over one of these
functions cannot be built while the function is unset, thus no dump of this age
holds one.

## The repair

`REACH_THE_HELPERS` is a `DO` block. It gives a `search_path` to each function
in `public` that has none. `ALTER FUNCTION` states reach and no body, thus the
tool does not select a generation of a body. These bodies have three
generations: 0017 wrote them, 0034 restated `is_valid`, and 0038 restated four
functions and added five.

The filter does not test the name. The risk applies to each function that a
domain `CHECK` or a generated column calls, and a name does not show this. Three
clauses are necessary:

| Clause | Reason |
|---|---|
| `prokind = 'f'` | `ALTER FUNCTION` refuses an aggregate or a procedure |
| `search\_path` | An unescaped underscore is a `LIKE` wildcard |
| `deptype = 'e'` | An extension keeps its own functions |

`psql` gets `-X` and `--set=ON_ERROR_STOP=1`. Without the second flag, `psql`
answers a failed script with 0, and `run()` accepts that as success.

Reach is necessary for each function, not only for `timetracker_temporal_is_valid`.
A domain check calls that one function, but a generated column calls
`timetracker_temporal_lower` directly.

## Limits

The repair corrects reach only. A migration that corrects a body leaves an old
dump with the old behaviour. A function that fails for another cause gives the
same incorrect domain message.

`docs/deployment.md` gives the same block to an operator who has only a shell.
