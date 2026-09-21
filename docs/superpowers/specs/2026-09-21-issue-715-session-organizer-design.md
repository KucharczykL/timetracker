# The desktop Session organizer

Date: 2026-09-21

Issue: [#715](https://github.com/KucharczykL/timetracker/issues/715) (ORG-02)

Wave: [Selectable tables and Session
organization](2026-09-19-selectable-tables-wave-design.md)

## Purpose

The organizer is the Playtime page's session list narrowed to one game. It
already has the filter, the sort, the presets and, since #712, the selection
line with the move #714 declares. It cannot say which run a session sits on,
and it cannot group its rows by run. This issue adds the Playthrough column
and the sort that groups by it, reaches the narrowed list from Game detail,
and gives the session row the stacked mobile cell #711 built and nothing has
used.

Nothing here writes an event, adds a bulk act, or changes a command.

## What the wave settled

The organizer session ruled five calls for this issue, recorded on #715 and
in the wave doc:

1. The column appears while **the list** names one game, not while the filter
   does. The filter wording was the doc's mechanism guess. Asking the
   narrowed queryset composes with #717's facet and reads no filter grammar.
2. The sort key exists on every session list. Only the header is
   conditional. A preset saved with `sort=playthrough` keeps sorting.
3. The bucket sorts last in **both** directions, through a null sort key
   rather than a pin on direction.
4. The name cell drops its run label while the column shows. One place.
5. Only the session list gets a summary line.
   [#1241](https://github.com/KucharczykL/timetracker/issues/1241) takes the
   other selectable tables.

## A sort key is an ordering, not a field

`SortSpec` holds one `expression`, and `apply_sort` emits one `ORDER BY` term
for it. Grouping sessions by run needs several terms, so the type is widened:

```python
@dataclass(frozen=True)
class SortSpec:
    expression: OrderField
    annotate: Annotations | None = None
    then: tuple[OrderField, ...] = ()
```

`apply_sort` emits `expression` and then every entry of `then`, each under the
term's own direction and each with `nulls_last=True`, exactly as it already
treats the head. `F("pk")` still closes the order. No existing `SortSpec`
changes.

This is the defect the Playthrough column has been blocked on: `sorting.py`
carries the comment "The Playthrough column carries no sort key", because the
run's place on a screen is a four-field order and the map held one field.

### What orders a run

`games/reads/playthrough_numbering.py` owns that order. Today it states it
once, as `DISPLAY_ORDER`, and turns it into `Playthrough N` with a window.
The module gains the field names as the source both forms read:

```python
#: The fields that order runs on a screen, in order.
DISPLAY_ORDER_FIELDS: tuple[str, ...] = (
    "started_lower",
    "completed_lower",
    "created_at",
    "id",
)

DISPLAY_ORDER = tuple(F(name).asc(nulls_last=True) for name in DISPLAY_ORDER_FIELDS)


def display_order_through(path: str = "") -> tuple[str, ...]:
    """DISPLAY_ORDER's fields, reached through a relation."""


def numbered_sort_key(path: str = ""):
    """Null where no number is counted across the run.

    The ORM twin of `is_numbered`.
    """
```

`DISPLAY_ORDER`'s two dated fields sort nulls last today and the two others
cannot be null, so building all four the same way changes no order.

`numbered_sort_key` is a `Case` answering `Value(0)` where `kind` is ordinary
and `removed_at` is null, and `None` otherwise. It states the same predicate
`is_numbered` states in Python.

Ruling 3 asks for a null sort key "rather than a `Case`". This is a `Case`
that *produces* the null; what the ruling refuses is a `Case` that reads the
direction to pin the bucket, and there is none. `apply_sort` already writes
`NULLS LAST` on both the ascending and the descending branch, so the null term
puts the bucket last under `playthrough` and under `-playthrough` alike.
Captured from the key this spec states:

```
ASC:  "games_game"."sort_name" ASC NULLS LAST,  20 ASC NULLS LAST,
      "games_playthrough"."started_lower" ASC NULLS LAST,  …
DESC: "games_game"."sort_name" DESC NULLS LAST, 20 DESC NULLS LAST,
      "games_playthrough"."started_lower" DESC NULLS LAST, …
```

The `20` is the select-list position of the `run_numbered` annotation.

### The two keys

A run's number means nothing outside its game, and the bucket belongs last
inside its own game rather than after every game. Both keys therefore lead
with the game:

```python
SESSION_SORTS["playthrough"] = SortSpec(
    f"{SESSION_GAME}__sort_name",
    {"run_numbered": numbered_sort_key("playthrough__")},
    then=(
        "run_numbered",
        *display_order_through("playthrough__"),
        "sort_instant",
    ),
)

PLAYTHROUGH_SORTS["playthrough"] = SortSpec(
    "player_game__game__sort_name",
    {"run_numbered": numbered_sort_key()},
    then=("run_numbered", *display_order_through()),
)
```

On the organizer the game term is constant, so it costs nothing and the
narrowed order is the run order. On a list that spans games the key reads
"grouped by game, each game's runs in display order" instead of interleaving
unrelated games by start date.

`sort_instant` closes the session key, so sorting by playthrough always means
"runs in display order, each run's sessions in time order". A plain header
click collapses the sort to one key (`collapse_sort`), so a second level
carried only by a link would not survive the first click.

**Descending is not a mirror of ascending, and that is the house rule.**
`nulls_last=True` rides every term in both directions, so a run that states no
start sorts after the dated runs under `playthrough` *and* under
`-playthrough`. `numbered_for` gives such a run the highest number, so a game
holding a dated run, a second dated run and an undated one reads 1, 2, 3
ascending and 2, 1, 3 descending. This is the convention the list already
keeps: `test_sorting_by_days_puts_the_runs_with_no_answer_last` in
`tests/test_sorting.py` pins it for the `days` key, under the docstring "No
answer sorts last both ways". The bucket's place is the same rule applied to a
run that is not numbered at all.

The Playthrough list's own run column gets the key through `_SORT_KEYS` in
`games/views/playthrough_rows.py`. That list is ordinary-only
(`library_runs` filters `kind`), so its null head never fires; it is stated
anyway, because the expression is the run's order and not this list's
population.

The path `playthrough__id` compiles to the session's own `playthrough_id`
column, so the session key joins `playthrough`, `player_game` and `game` and
nothing else. All three already exist on the list's row path.

## The column

`sole_game(sessions)` lands in `games/reads/player_sessions.py` beside
`library_sessions`. It takes the filtered queryset **before** `apply_sort`
annotates it, clears its ordering, and answers the game key when
`values_list(SESSION_GAME).distinct()[:2]` answers exactly one, else `None`.

The ordering must be cleared, but not because anything raises. Django adds
each ordering expression to the `SELECT DISTINCT` list itself, so an ordered
queryset would distinct over the game key **plus** `sort_instant` and `id` —
one game with two sessions would answer two rows and `sole_game` would say
`None`. Taking the queryset before `apply_sort` keeps the sort's `CASE` out of
the same list for the same reason. `readable_sessions` carries no ordering of
its own today (`PlayerSession._meta.ordering` is empty), so `.order_by()` is a
guard against a later one rather than a fix for a present bug.

It answers the key rather than a boolean, because #717's counts and any later
header that names the game read the same function.

The read runs on every session-list load: one aggregate over at most the
library's sessions, 2,817 of them on the 2026-09-19 dump. Skipping it while
unfiltered was rejected: a library holding one
game would then show the column when narrowed to that game and hide it when
not, for the same rows.

When `sole_game` answers a key:

- a `Column("Playthrough", "playthrough", shrinkable=True, priority=3)` is
  inserted after Name. Priority 3 ties it with Date, and the rightmost of
  equals drops first, so the drop order is Created, Device, Duration, Date,
  Playthrough. `computeHiddenColumns` in `ts/elements/responsive-table.ts`
  never drops the last of that order, which is Actions, so Playthrough is the
  last column that *can* drop — the grouping key outlives every column except
  the one that is pinned. Below `md` it goes too, which the summary line
  answers;
- each cell is `TruncatedText(label)` over `every_run_label` (#714's), keyed
  on `session.playthrough_id`. A sole run is named, because the column's
  subject is the run. The bucket reads `Imported history`, which
  `every_run_label` stamps because `numbered_for` counts ordinary runs only.
  There is no playthrough detail page, so the cell is not a link;
- `NameWithIcon` is given `run_label=None`, so the run is named in one place.

When it answers `None` the columns and the cells are today's.

### A library holding one game

`sole_game` answers that game's key on the **unfiltered** list as well, so
such a library always sees the column and never sees a run label in the name
cell. That is ruling 1's point — the same rows get the same table however they
were reached — and it is the consequence that made "skip the read while
unfiltered" tempting. It rewrites three tests in `tests/test_session_list.py`,
which all seed one game and read `data-run-label` off the unfiltered list:
two now read the column instead, and `test_a_game_with_one_run_shows_no_run_label`
keeps passing for a different reason, so it is renamed to say which reason.

`every_run_label` needs no extra query: the page already calls
`ambiguous_run_labels`, which is the same read, and the view calls whichever
of the two the column state asks for.

## The stacked cell

Every session row states `summary=`, so the row has the second line #711
built. The line is `", ".join` of:

- the run label, **only while the list names one game** — the same state
  that declares the column. Below `md` the column itself has dropped like the
  others, and the name cell's label is gone by ruling 4, so without this the
  run would be unnamed on a phone;
- `session_time_range(session, presentation)`;
- `durations.format(session.effective_duration)`;
- the device name, omitted when the session names none — a scarce line does
  not spend itself saying "No device".

Commas, not a middle dot: the line is plain text inside the identity cell
with no `aria-hidden` available, and a screen reader reads a comma as a pause
and a middle dot as a word. The hand-entered mark the Duration cell carries
is not repeated; the summary states the number, not the cell.

## Game detail

`_sessions_section` gains an Organize button beside View all, both shown when
the section has rows. Its target is the same list under the new sort:

```python
filter_url(PlayerSessionFilter.where(game=[game.id]), sort="playthrough")
```

`_game_section` takes an `organize_url` beside `view_all_url`. The two links
differ only by that sort, which the wave doc accepts and the organizer
confirmed.

The button carries a new icon: a Lucide-style `list-tree` glyph, items
grouped under a parent, which is what a run and its sessions are. It is a
snippet under `games/templates/icons/` compiled by `make gen-icons`, whose
drift is guarded by `check-icons` inside `make check`. No existing slug is
bent to a meaning it did not have.

`ICON_NODES` is one namespace for platform badges and interface glyphs alike,
and `get_icon_node` answers `unspecified` for a name it does not hold without
failing, so a mistyped slug renders a wrong glyph silently. A test asserts the
slug resolves to its own node.

`_game_section`'s header is a `flex` row with no wrap, and a third button
lands beside a heading and a badge. It gets `flex-wrap`, and the section
header is checked in a browser at 375 px rather than reasoned about.

The five-row preview keeps its three columns. It is not the organizer.

## Not in scope

- The Name column repeats one game on every row of the organizer. Narrowing
  the identity cell is a table question, not this issue's.
- No quick facet for the run. #717 owns the next facet.
- No `make bench` entry. `sole_game` is one aggregate on a page the bench
  does not time.

## Verification

Ordering:

- `tests/test_sorting.py`: a game with **three** live ordinary runs — two
  dated, one stating no start — plus a bucket. Ascending, the sessions come
  out in the order `numbered_for` numbers the runs, bucket last. Descending,
  they read 2, 1, 3, bucket last, which is the null rule this spec states and
  not a mirror. Each run's sessions are in `sort_instant` order; a second
  game's rows do not interleave.
- `test_the_run_sorts_read_the_projection` asserts `PLAYTHROUGH_SORTS`'
  keyset exactly and gains `"playthrough"`.
- `DISPLAY_ORDER` is built from `DISPLAY_ORDER_FIELDS`, so a test that
  rebuilds one from the other proves nothing. Instead: `numbered_for` returns
  the same order before and after the change, over a fixture holding a run
  with no stated endpoint.
- `tests/test_sort_header_parity.py` keeps passing unchanged; it asserts
  headers are a subset of the map, which a conditional header satisfies.
- The API takes the key through the same `apply_sort`
  (`GET /api/session/?sort=playthrough`), ascending and descending.

The column:

- The list renders the column and drops the name cell's run label when
  `sole_game` answers one game, and renders neither when it answers `None`.
- `sole_game` answers `None` for an empty list and for two games, and the
  game's key for one, under a filter and without one.
- The three `tests/test_session_list.py` label tests are rewritten for the
  one-game consequence above.
- `test_the_list_costs_no_query_per_row` keeps holding: `sole_game` adds one
  query, constant in the row count.

The page:

- One e2e on the real session list at 375 px: the summary line renders under
  the name and the checkbox sits beside the name, not centred across both
  lines.
- The Game detail section header at 375 px with three buttons, in a browser.
- The Playthrough list sorts on its run column and the header links to the
  new key.
- The `list-tree` slug resolves to its own icon node.

Full `make check` green.

### Left unproven

- A second `shrinkable` column below `md`. `SHRINKABLE_COLUMN_CLASS` is
  `max-md:w-full max-md:max-w-0`, and `columnCosts` substitutes a floor only
  for column 0, so two shrinkable headers compete for the same greed. The
  Playthrough list already ships `column("Game", shrinkable=True)` at index 1,
  so whatever this does is not new here; nobody has measured it between
  390 px and 767 px.

## Follow-ups

- [#1241](https://github.com/KucharczykL/timetracker/issues/1241) — the
  summary line on the other selectable tables and the Playthrough list.
