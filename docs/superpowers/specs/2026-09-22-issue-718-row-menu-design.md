# The row's menu, and Finish in the tray

A table states two act lists. The tray states what a selection can do; the
row's menu states what one row can do. Neither list is the other's residue,
so an act reaching the tray takes nothing off the row.

## The row's menu slot

The menu is not a column. `make_row` states it, beside the `key` and the
`summary` a row already states, and `StyledTable` renders it: one trailing
cell a row, and one trailing header cell so the grid stays rectangular and
`<responsive-table>`'s positional `nth-child` selectors keep addressing the
declared columns.

That header cell carries no visible label, an accessible name of its own, and
a `data-priority` of one above the table's highest, computed from the
columns the view declared. The element hides the lowest priorities until the
table fits, so a computed maximum is what keeps the acts on a phone.

The slot therefore never enters a view's `Column` list, never counts against
`MAX_DATA_TABLE_COLUMNS`, and states no per-table priority for anyone to get
wrong. `tests/test_column_priority_contract.py` turns a coincidence into a
guarantee by asserting that every declared `Actions` column outranks its
table; the five tables here stop needing it, because the rank is computed
rather than declared. The test keeps guarding the six tables that still
declare a labelled `Actions` column.

Five tables state a menu: the session list, the historical playtime list,
the playthrough list, and Game detail's playthroughs and historical
playtime. Two row builders serve four of them, so a builder's menu serves
both its pages.

## The trigger, and the menu around it

Three surfaces draw the same idea three ways: the quick filter bar's
overflow is the literal character, the library's summary rows are
`Icon("ellipsis")`, and a table row has nothing. `EllipsisTrigger` is the one
ghost `ControlButton` all three read, stated with a label and an
orientation.

The menu around it is not shared with the quick bar. A row's panel is a
`DropdownMenuPanel` of items; the bar's is a dialog holding the facet
triggers its layout moved there. Only the trigger is common.
`RowActionMenu` is the row's half, and the library's summary menu becomes a
caller of it.

Vertical marks a row's own acts, horizontal an overflow among controls.
`ellipsis.html` is three dots in a ring and stays as it is: it is
`TruncatedText`'s reveal as well as the summary rows', and its name is the
value of `data-truncated-reveal`. Two bare icons arrive beside it.

A row's trigger names its row and states an id of its own.

## What each row offers

The menu holds every act the row allows, gated as the buttons were gated.

A session offers Finish and Reset while it is a running Timed row, Edit,
Move to playthrough, Record as historical playtime while it is Duration-only,
and Remove. A playthrough offers Started today where it states neither
endpoint, Completed today where it states a start and no completion, then
Edit and Remove. A record offers Edit and Remove.

A gated act is absent, never disabled. A disabled item promises an act the
row cannot accept.

An item that a tray act also states reads in the tray's words. The words are
the act's, so the builder reads `games.bulk_actions`, and no module under
`common/components/` may: that import closes a cycle through the foot
imports of `games/bulk_actions.py`, out through `games/forms.py` and back
into `common.components`. The menu builder in `common/components/` therefore
states items and knows no act; each table's items are built under
`games/views/`, and the session row's builder leaves
`common/components/domain.py`.

Finish and the two playthrough acts post. The rest are links to their own
confirmation pages, which carry `?origin=` as they do today.
`DropdownPostItem` states `hidden_fields`, because Finish posts the zone.

## The tray, as its acts grow

The selection line renders its acts as a priority-plus row, the engine
`ts/elements/priority-plus.ts` already serves two callers: the acts that no
longer fit move into one horizontal `EllipsisTrigger` at the end, rightmost
first, and move back when the width returns. The line wraps today, which
puts a sticky bar of several rows over the table once a table states five
acts.

Declaration order is priority order. A table states its acts in the order a
person reaches for them and states the destructive act last, so that act is
the first to overflow and never sits between two benign ones.

The line is hidden until the mode turns on, so a width measured at connect is
zero. The row measures when the mode first turns on.

## Finish, as an act on many rows

`FINISH_SESSION` is a `BulkAction` over sessions. Its scope and resolve are
the removal act's, because the tray's act is the list's own read narrowed by
the statement. A row that is not running is refused by `EndSession` and named
in the report.

**One batch ends at one instant.** The runner keys each row
`f"{act.name}-{token}-{acted}"` and the idempotency record compares a
fingerprint of the command's input, so a payload that differs between two
posts of one chunk raises `IdempotencyKeyMismatch` and counts every finished
row as refused. `timezone.now()` inside the run is such a payload.
`<continuing-batch>` posts the waypoint on connect, so a reload would
reproduce it. The instant is therefore settled once and carried: the
confirmation stamps it, the choice holds it beside the zone, and
`_progress` round-trips the pair to every chunk.

The choice is the act's `BulkChoice`. `offer` answers a `Control` holding the
stamped instant and `BrowserTimeZoneInput()`, and `settle` answers both as
one value, refusing an instant it cannot read and reading the zone as
`zone_or_none` does, because the field is a person's to edit and the runner
settles it again on every chunk. A browser that states no zone states none,
which is what the row's Finish records.

The inverse restates the timing: `CorrectSessionTiming` to a `TimedTiming` of
the row's own start and both of its zones, with no end, which is the row
running again. `day_zone` is non-null on a Timed row by CHECK alone, so the
inverse states that as `reset_session` does. It reads the start the row holds
when the Undo runs, the hazard every batch Undo accepts, and a library whose
calendar zone changed between the Finish and the Undo has the Undo refused
row by row.

`end_session` and `correct_session` state `idempotency_key` and
`source_metadata` and answer the `CommandResult`. Each act's callable is a
wrapper of its own, as every shipped act has: the protocol states `choice`,
`idempotency_key` and `correlation_id` as keywords and answers a
`RowOutcome`.

## One cardinality is none

Every act the tray offers is an act on many rows, and no declaration says
otherwise. `Cardinality`, `BulkAction.cardinality`, `SelectionCardinality`,
`SelectionAction["cardinality"]`, the `SPELLED` map and the two filters that
read them are gone, over nine files. A field whose every value is the same
states nothing.

## What the shape forecloses

**A row states no act without scripting.** The panel carries the `hidden` the
server stamps and only `ts/elements/drop-down.ts` removes it, so the trigger
is inert and all five tables lose every row act. The row is plain links and a
no-JS form POST today, and this is a regression, not an inheritance from the
selection line, which was never a no-script path. No page states a row's
facts either: `games/urls.py` states no `view_` for a session, a run or a
record, and a session row's name cell links to the game. The answer is a page
of its own for each, which is #1258.

A row keeps a trailing control on every table, so a row can never be reduced
to its identity and its checkbox.

An act is declared twice, as a route with its own confirmation and as a
`BulkAction`. A rule the command gains reaches both, because both dispatch
the command; a rule the *screen* gains reaches one. Remove and the
reclassification already pay this.

Removing one row offers two confirmations, the row's own and the runner's,
which say different things about the same act.

Each `<drop-down>` binds two document listeners for its connected life, and
`per_page` admits 1000. The session list pays this already, one selector a
row; the playthrough and historical playtime lists pay it first here.
Nothing measures it.

## Verified by

An Orca transcript on the Playtime session list: the mode turned on, the
count heard, two rows checked, a tray act reached and pressed, then a row's
menu opened, its items counted and one fired. The other four tables are
Playwright's.

`make render-pages` before and after, every differing file attributed.

The two e2e tests that press a row's control move with it:
`e2e/test_session_finish_e2e.py` locates a form inside the row, and
`e2e/test_session_reset_e2e.py` a link. Both are inside a panel that starts
hidden.
