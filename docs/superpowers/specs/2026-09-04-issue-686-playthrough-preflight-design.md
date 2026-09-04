# Report the legacy lifecycle rows

Issue [#686](https://github.com/KucharczykL/timetracker/issues/686), in epic
[#601](https://github.com/KucharczykL/timetracker/issues/601).

`games/preflight/playthrough.py` reads the legacy `PlayEvent` rows. The
`preflight_playthroughs` command prints the result, and
`make preflight-playthroughs` runs it. The code only reads. It appends no event
and writes no row.

#684 converts each live `PlayEvent` into a Playthrough. This report says what
that conversion meets. #684 imports the classifiers, thus the two agree.

## The walk

The walk starts at the live `PlayerGame` rows of one library. A library can
track a catalog game that it does not own, thus a walk over the catalog can
miss rows. `PlayerGame` has no manager. Write the liveness condition in full:
`filter(library=…, removed_at__isnull=True)`.

`keyset_pages` pages the aggregates. Each batch makes one query for the games
and one for their rows. No code opens a server-side cursor.

## The two axes

`classify_row` gives one of five verdicts to each live row: `clean_both`,
`clean_start_only`, `clean_end_only`, `no_known_endpoint` and
`reversed_endpoints`. The five counts sum to the live row count. A row with
`started == ended` is `clean_both`, because #681 refuses only a completion that
is earlier than its start.

`legacy_order_key` gives the display order: the known start, then the known
completion, then the primary key. Use the primary key, not `created_at`.
`created_at` is `auto_now_add`, thus `loaddata` writes a new value. Three
counts report the order of a game: `ordered_by_date`, `tie_broken` and
`date_order_differs_from_insertion`. The last two can both apply to one game.

The report also counts the rows that the conversion does not see: a removed
row, a row on a removed game, a row on an untracked game, and a row with no
projection. The last count is the #676 signal. The checks run in this order,
thus each row is counted once.

## The pairing

An endpoint is one known date on one live row. A candidate is a #676 status
event with the same aggregate, the same kind and the same day. `pair_endpoints`
groups the endpoints and the events by that key. A group with one endpoint and
one event is `unambiguous`. A larger group is `ambiguous`, and no event is
taken. An endpoint with no event is `absent`. The verdict is a property of the
group, thus the read order cannot change it.

The day comparison occurs in Python. `effective_time` has no generated bound
columns. A candidate must state a known day, because `lower_bound` also answers
for a month or a decade. The candidate events are read once for each library.

## The output

Name the scope: `--user`, `--library` or `--all-libraries`. The first line is
`PLAYTHROUGH_PREFLIGHT_JSON=` and a payload that carries a `schema_version`,
the summary, one entry for each library, and the shared catalog counts. A
readable section follows for each library. `--sample-size` limits the
identifiers beside a count; the default is 20, and `0` prints none. Two runs
over the same data print the same bytes.

The command always exits 0. A preflight reports; it does not gate.

The pairing counts are zero before migration 0033. Restore a copy of the
deployed database, migrate it, then run the command.
