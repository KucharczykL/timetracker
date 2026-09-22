# A person chooses which columns a list shows

Seven lists let a person turn columns off: games, sessions, purchases,
playthroughs, historical playtime, devices and platforms. The control is an icon
in the table's own header row, not on the quick filter bar. The bar asks which
rows; the columns are what the table shows of them. A column choice travels in
no `?filter=`, is saved by no preset, and changes no result set.

## Where the choice lives

`ListColumnChoice` holds one row for each person and mode, unique on
`(user, mode)`, with a `UUIDv7Field` key. `shown` is a JSON map of column key to
whether that person shows it, holding only the keys standing away from the
column's own default. `games/list_columns.py` is the one reader and the one
writer, and it refuses a mode no list states.

The choice belongs to the person. A saved filter describes the rows and is keyed
on the library; which columns a person reads those rows with stays theirs. The
key on `auth.User` is a bigint, so the row states the two inventory lines the
identity audit asks of one.

Nothing here is a command and nothing appends an event.

## The default is the declaration

Each column states where it starts, and `Column.hidden_by_default` turns one off
for a person who has stated nothing. The created timestamp starts off on all
seven lists, and so do Wikidata on games, Infinite and Refunded on purchases, and
References on platforms: each earns its width seldom. A column that refuses to
hide may not start hidden, because nothing could then show it again.

Nothing is written until a person chooses, and a row records only what differs
from the declaration. Three things follow, and a stored list of hidden keys gives
none of them:

- a column added later starts where **it** says, rather than where an older row
  left it;
- showing a column that starts hidden is storable, where an empty hidden list
  would read as "no choice" and hand back the default;
- a default this project changes later does not invert what a person already
  stated, because the row states `false`, not "away from whatever the default is".

A key no column claims any more hides nothing; the reader ignores it. A choice
that states the defaults back removes the row, because the row would say what the
declaration says. Reset removes it too.

No row is seeded when a person is created. A seeded row is a copy of the
declaration that goes stale: a column added after the seeding could carry no
default, and every person who already exists would need a data migration to
receive one.

## A column's identity

`Column` states a `key`, because a label is not an identity: the game list's
playtime header reads `Playtime`, `Playtime (matching)` or
`Playtime (matching sessions)` for one column, depending on the filter.

`Column.hideable` is false on two kinds: the first column, which is the
`<th scope="row">` that names every row, and the Actions column, which carries
every act on it. A person who unchecks every box is left a table that still names
its rows and still acts on them, and a list always starts with more than those
two.

## Narrowing

`drop_columns` in `common/components/primitives.py` takes each named column out
with its cell in every row. It reads no `hideable`: a page states exclusions no
person may state, and Game detail leads its record table with the day, hiding the
very Name column the list pins. The view reads `hideable`, through
`column_choice`, which narrows the person's set before the builder sees it.

One parameter carries both. `historical_playtime_tabledata` and
`playthrough_tabledata` take `hidden`, and each reads the same set for the
stacked line below `md`: a table that drops a cell and leaves its fact in the
summary is the judgement this design removes.

## The control

A square icon button sits in the table's **last** header cell: the trailing
row-menu cell where the rows carry a menu, else the Actions header. Stated that
way, the icon follows the slot by itself as
[#1134](https://github.com/KucharczykL/timetracker/issues/1134),
[#1135](https://github.com/KucharczykL/timetracker/issues/1135),
[#1136](https://github.com/KucharczykL/timetracker/issues/1136) and
[#1266](https://github.com/KucharczykL/timetracker/issues/1266) retire the four
Actions columns.

The panel is a `<drop-down behavior="column-picker">`, which opens
`position: fixed`. It must: the table's shell clips, so a panel anchored inside
the header is sliced at the shell's edge. The behavior states a match-nothing
item selector, so the boxes keep Space and the arrow keys, and `keepOpenOnTab`,
so Tab reaches Apply.

The panel holds a plain `<form method="post">` — nothing wraps a list's table in
a form — with one checkbox for each column, Apply, and Reset. A column that
refuses to hide states a checked, disabled box rather than none, so the panel
reads as the whole table.

An unchecked box posts nothing, so the posted keys are the whole of what a person
shows, read against the live column list. A disabled box posts nothing either,
which is why a pinned column is shown whatever the request carries. Reset is a
named submit, read before the boxes: a `formaction` would post whatever the panel
stood at.

The route is POST only at `lists/<mode>/columns/`, carries `?origin=`, and is
`ORIGIN_AWARE`. With no scripting the panel does not open; the server still
renders the person's columns, because it reads them before it renders.

## The session list

The Playthrough column is declared always, at priority 3 after Name. No page
judges whether a run is worth naming. A person who turns the column off is named
no run anywhere: not beside the name, and not in the stacked summary. Two sessions
at one game on one day, on different runs, then read alike. That is the cost of
the rule, and the rule is that a column which moves its content elsewhere when
hidden is the same judgement, wearing other clothes.

## What does not change

`<responsive-table>` drops for width among the columns that are left. A hidden
column still orders the list where the URL names it in the sort, and still
filters it where the quick bar names it in a facet: what a person shows and what
a person asks of the rows are two questions. `<selectable-table>` keys its
storage on the scope and the path, which no column moves.

The purchase refund endpoint re-renders one row outside the list, so it reads the
same choice. A row of the declared width would land in a narrowed table.

## What this leaves

[#1261](https://github.com/KucharczykL/timetracker/issues/1261) holds the preset
that carries its own columns.
[#1262](https://github.com/KucharczykL/timetracker/issues/1262) holds the choice
a person states with no scripting.
[#521](https://github.com/KucharczykL/timetracker/issues/521) holds column order,
width and print styles.
[#1267](https://github.com/KucharczykL/timetracker/issues/1267) holds the quick
filter bar's own grouping, which moving this control off the bar revealed.
