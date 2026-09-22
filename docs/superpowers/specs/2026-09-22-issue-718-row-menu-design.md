# The row's menu, and Finish in the tray

A table states two act lists. The tray states what a selection can do; the
row's menu states what one row can do. Neither list is the other's residue,
so an act reaching the tray takes nothing off the row.

## The menu column

`Column` states `menu`. A menu column declares no sort key, aligns right and
carries the row's own acts as one `Dropdown`. The trigger is a ghost
`ControlButton` holding the `ellipsis` icon, stamped by `_as_menu_trigger`,
with an `aria-label` naming its row and an id of its own.
`common/components/library_kit.py` already builds this trigger; the shape
moves to a builder both callers read. `ButtonDropdown` is not that builder:
it states no variant and appends a caret of its own.

Five tables declare a menu column: the session list, the historical playtime
list, the playthrough list, and Game detail's playthroughs and historical
playtime. Two builders serve four of them, so a builder's column serves both
its pages.

The column replaces each table's `Actions` column. Its priority is that
column's, which is the strict maximum of the table: `<responsive-table>`
keeps the highest-priority column beside the row header at every width, and
the acts are what keeps a row actionable on a phone.

`_header_cell` states the label to a reader and hides it from a viewer, and
marks the header `data-row-menu` beside the drop policy.
`tests/test_column_priority_contract.py` reads that marker **or** the label
`Actions`. Six tables keep a labelled Actions column, and the test exempts a
table it finds neither on, so reading the marker alone would unprotect all
six in silence.

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
longer fit move into one `ellipsis` menu at the end, rightmost first, and
move back when the width returns. The line wraps today, which puts a sticky
bar of several rows over the table once a table states five acts.

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
