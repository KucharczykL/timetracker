# Selectable tables and Session organization: the delivered wave

Parent epic: [#601](https://github.com/KucharczykL/timetracker/issues/601).
Charter: [the overhaul design](2026-08-09-timetracker-overhaul-design.md).
Planned on 2026-09-19, delivered whole on 2026-09-28.

## Purpose

A person selects rows of a list and acts on the selection as one batch.
The batch has one Undo. Every list that had an Actions column now has a
row menu and a tray instead. The Playtime page's session list, narrowed to
one game, is the organizer the charter asked for. This document is the
map of that work: what landed, which rules hold across it, what changed
from the plan, and what the wave taught. Each rule's machinery is in the
issue spec the table below names, or in `CLAUDE.md`. This document does not
repeat it.

## What was delivered

| Issue | What it is | Contract |
|---|---|---|
| #711 | `<selectable-table>`: the row checkbox, the selection statement, the keyboard contract, the stacked identity cell below `md`, the footer's selection line | [Selectable table](2026-09-19-issue-711-selectable-table-design.md) |
| #713 | The bulk runner: `BulkAction`, the two-POST confirmation, the token, chunks, the batch Undo, two event indexes, `make bench` for a batch. Closed #1123 and #1125 | [The bulk runner](2026-09-20-issue-713-bulk-runner-design.md) |
| #712 | The tray's actions slot and bulk Remove on the five session, run and record tables | [Selection actions](2026-09-20-issue-712-selection-actions-design.md) |
| #714 | Bulk move to a playthrough, the aggregate reader, the bucket removed when emptied. Its act later moved into Edit (#1310) | [Bulk move](2026-09-21-issue-714-bulk-move-design.md) |
| #715 | The organizer: the Playthrough column and sort on the session list, Organize on Game detail | [Session organizer](2026-09-21-issue-715-session-organizer-design.md) |
| #1241 | The stacked summary on the other four selectable tables | [Table summaries](2026-09-21-issue-1241-other-table-summaries-design.md) |
| #717 | `outside_playthrough_dates`, `playthrough_kind`, the Library page's three cards | [Outside run dates](2026-09-21-issue-717-outside-run-dates-design.md) |
| #718 | Five Actions columns retired into the tray and the row's ⋯ menu, Finish as a tray act, `EllipsisTrigger` | [The row menu](2026-09-22-issue-718-row-menu-design.md) |
| #1256 | Started today and Completed today as tray acts, with void commands as inverses | [Bulk endpoint acts](2026-09-22-issue-1256-bulk-endpoint-acts-design.md) |
| #1245 | The columns a list shows, per person and mode, with the picker in the row-menu slot | [Column choice](2026-09-22-issue-1245-column-choice-design.md) |
| #1211 | Bulk Edit on the session tables: device, emulated, note | [Bulk edit](2026-09-25-issue-1211-bulk-edit-design.md) |
| #1310 | Bulk Edit states the playthrough. Move leaves the tray | [Bulk Edit states the playthrough](2026-09-27-issue-1310-bulk-edit-moves-design.md) |
| #1134 | The Games list selectable: bulk Remove from the library, the row menu | [Games list](2026-09-22-issue-1134-games-list-selectable-design.md) |
| #1270 | Bulk Edit on the Games list: status, mastered, the unfinished flag | [Edit many games](2026-09-28-issue-1270-bulk-game-edit-design.md) |
| #1274 | Device becomes an event-sourced aggregate, so its removal has events an Undo reads | [Device aggregate](2026-09-24-issue-1274-device-aggregate-design.md) |
| #1135 | The Devices list selectable: bulk Remove, the row menu | [Devices list](2026-09-24-issue-1135-devices-list-selectable-design.md) |
| #1136 | The Platforms list selectable: bulk Edit and Remove over a batch ledger, the icon picker | [Platforms list](2026-09-28-issue-1136-platforms-list-selectable-design.md) |
| #1321 | Platform icons name their glyphs. Group is a search-select | [Platform icons](2026-09-28-issue-1321-platform-icon-glyphs-design.md) |
| #1254 | The quick bar keeps an applied facet inline and marks it. Every mode's facets reordered | [Facet priority](2026-09-28-issue-1254-quick-bar-facet-priority-design.md) |
| #1316 | Selection is not a mode: always-on checkboxes, a check-all in the header and the tray | [Always-on selection](2026-09-28-issue-1316-always-on-selection-design.md) |
| #1267 | The quick bar's acts as one group. `<preset-panel>` loads and saves presets | [Filter acts](2026-09-28-issue-1267-filter-acts-group-design.md) |
| #1283 | Edit's move-back answers a broken stream as a defect | [Move back](2026-09-28-issue-1283-move-back-unreadable-row-design.md) |

One prerequisite came from the Session wave: #1080, the creating
`SearchSelect`, which the move confirmation, the device control and the
Playthrough field of Edit read. #716 merged into #711 and #715. #1212 was
superseded by #1316.

Every issue merged alone. Each left `main` incomplete, never inconsistent.
#711 was a personality nothing used. #713 was a runner one page used. #712
was a tray beside the Actions columns it later replaced. No stack was needed,
because nothing converted data until #1274.

## The rules that hold

These rules cross the issues. No single spec owns them.

- **Two complete lists, no residue.** The tray offers every act. The row's
  ⋯ menu offers every act that is valid for one row, in the tray act's
  words. A tray act takes nothing off the row. A single row's act is two
  presses, the menu and the item. A multi-row act is the checkboxes, then
  the action.
- **The row menu is a slot, not a column.** `make_row` states it. The
  table draws it as one trailing cell whose priority is computed above
  every declared column. It never enters a view's `Column` list. The row
  checkbox is content of the identity cell and is not a column either.
- **A selection is a statement.** It is a list of keys, or `all` beside
  the filter, the count seen and the keys unchecked since. It is always
  POSTed. The confirmation resolves it under the library once. From then
  on the act names those keys and no others. A row gone since is counted
  lost. A row that entered the filter since is never touched.
- **A batch is one correlation id.** The token is that id. Every chunk
  resubmits it. Each row is its own transaction under its own idempotency
  key. A refused row is named and the next row runs. A defect ends the
  batch, and the rows already done stay done.
- **Every act is `many`.** There is no `one` cardinality and no per-row
  route for a tray act. A menu item hands one row to the runner through
  the same statement, so one row gets the confirmation, the tally and the
  Undo.
- **An act with a side effect confirms first.** It is never one press.
- **Declaration order is tray order.** The act reached for most often
  comes first. The destructive act comes last, so it overflows first and
  never sits between two benign acts.
- **One Edit per list.** Edit states every fact the list's row has, and an
  empty field keeps its value. A separate act per fact was tried and
  removed.
- **Every act has an inverse, and says where its Undo reads rows.** An
  aggregate's Undo reads the batch's events (`EventRows`). A conventional
  row's Undo reads the batch ledger (`LedgerRows`). The runner refuses an
  act that names neither.
- **An Undo is partial.** A row whose inverse is refused is named, and
  the rest is undone. All-or-nothing was rejected.
- **An inverse that restates overwrites and logs.** An inverse that would
  destroy a value the batch never wrote refuses that row. A side effect
  the batch stated on another aggregate is put back too.
- **An unreadable row is a defect.** A stream with no creation before the
  batch's event, or a payload of the wrong shape, raises `RowUnreadable`.
  It is never a sentence the person cannot act on.
- **The runner refuses a filter it cannot parse.** It never widens the
  act to every row.
- **A gated act is absent, never disabled.**
- **A reader an act needs lives in `games/reads/`.** An act module
  imports no sibling act. The act table imports every act at its foot.
- **Selection is the element's.** The server renders no checkbox and no
  tray.
- **A list column has a key.** A label is not one. `hideable=False`
  marks the column nobody may turn off. `hidden_by_default` marks the
  column that starts off.

## What changed from the plan

- **Selection was a mode. It is not.** The plan followed PatternFly,
  Carbon, Polaris, Helios and SABnzbd: a Select toggle, a reserved empty
  column, a tray opened with the mode. On the shipped list the empty
  reserve was wrong to the eye. #1212 asked whether to collapse it and was
  parked. #1316 removed the mode instead: every row shows its checkbox,
  the tray shows with a selection, the check-all sits in the header and
  the tray. Gmail and GitHub's issue list are the prior art that won.
- **The `one` cardinality went.** The plan offered Edit, Reset and
  Was-an-estimate as links while exactly one row was selected. The user
  overturned it on the shipped tray: bulk Edit is a different act from the
  row's Edit, and Finish is coherent over many rows. The two-lists rule
  replaced it.
- **Move and Set status became fields of Edit.** #714 shipped Move as its
  own act with its own confirmation. #1310 made the playthrough Edit's
  first field and took Move off the tray. #1270 was filed as Set status
  and shipped as the Games list's Edit.
- **The organizer's population was not the charter's.** The charter's
  "ambiguous" sessions were the imported-history bucket's. On the
  2026-09-19 production copy that was one row. The real population was the
  sessions the conversion had placed by the sole-run rule: 113 sessions on
  29 runs dated outside the run's stated interval. So #717 became a facet
  that asks that question, with no stored state.
- **Bulk Remove was added.** No placeholder named it. It is the one act
  valid on every table and the runner's proof.
- **#713 moved ahead of #712,** because the tray's first act needs the
  runner. #717 moved after #715, because its facet reads the organizer.
- **Devices needed an aggregate first.** #1135 was blocked: a device
  removal wrote no event, so its Undo had nothing to read. The user ruled
  a device player-owned state with a lifecycle, like a Purchase. #1274
  moved it inside the event-sourced boundary. #1275, sold and lost,
  followed.
- **Platforms got a ledger instead.** The charter keeps custom catalog
  rows conventional, and four tables hold a key to Platform. #1136 added
  `BatchChange` and `LedgerRows`, so a conventional row's batch has an
  Undo without becoming an aggregate.
- **Purchases waits.** #1266 stays behind #725–#736, because a Purchase
  becomes an aggregate there and takes `EventRows`. A ledger path built
  first would be thrown away.
- **Parked, then done.** #1212 and #1254 were parked on 2026-09-22 so
  #718 could land. #1316 replaced the first and #1254 shipped after.
- **Deviations from the charter.** The empty bucket is removed, not kept.
  Finish is a tray act and a menu item, not an inline control. A
  cross-game move is refused, not picked. The organizer is reached from
  Game detail's Sessions section. A date range is the date facet and
  "Select all N matching".

## Lessons

- **Ship the page, then judge the shape on it.** The mode, the empty
  reserve and the `one` cardinality all read well in the spec. All three
  fell on the shipped list. Prior art is a start, not a verdict.
- **Measure the population before you design for it.** The charter's
  organizer targeted one row. One query on a production copy found the
  real work. The same query set the chunk size: every real bulk is under
  100 rows, except "all matching" on the session list.
- **Shape closes what a setting cannot.** #1125's field cap fell to one
  statement field, not to a raised limit.
- **Decide per model where an Undo reads rows, before the list.** Device
  became an aggregate. Platform took a ledger. Purchase waits for its wave.
  Each answer was found while planning the list, and each blocked it for a
  day.
- **Run the test before a defect goes into a doc.** #1284 was a peer's
  claim carried into this document and one handoff. The test that
  disproved it had passed since #1256's own commit.
- **An acceptance item that is nobody's task never runs.** Three PRs
  merged with "Orca pass pending". #1335 now holds every check with an
  owner and a recipe.
- **One act per list, many facts.** Two acts per fact doubled
  confirmations and Undo rules. One Edit with "keep" as the empty value
  replaced Move and Set status and gave the Platforms list its Edit in one
  step.
- **A defect ends the batch, and done rows stay done.** Each row commits
  on its own. All-or-nothing would leave a batch stuck on one row, which
  was #1123's own complaint.
- **Keep the wave document current from the side.** After every merge, a
  docs-only PR carried what changed into this document. A comment carried
  it onto each open sibling issue. A planner who opened #1136 found the
  Undo question already asked on #1135.
- **Merge alone when nothing converts data.** Eleven issues landed as
  single PRs with `main` incomplete between them. The one conversion,
  #1274, landed with its consumer in one PR.

## What other waves take

- **The Trash (#795)** lists recent batches: the correlation id, the
  Undo route and the `(library, correlation_id)` index.
- **The union list (#1100)** takes the selection statement and the tray. A
  row declares its kind, and the act's per-row command reads it. A union
  mode states its own `FilterPreset` mode word, which keys both the column
  choice and the presets.
- **Import (#798)** gets an inbox that is a selectable table with bulk
  acts by construction.
- **Audit History** reads the aggregate reader, the first per-aggregate
  read of the stream.
- **Purchases (#1266)** takes the personality and the row menu after
  #725–#736, with `EventRows`.
- **Access and ownership** takes #1275, a device sold or lost.
- **The rethink (#1209)** waits for the interface work after #599's
  epics. It judges a confirmation that forecasts a command's refusal,
  whether bulk Remove on runs stays, and whether an act declared twice
  keeps two confirmations.

## Verification

Tests pin these proofs:

- The keyboard contract, on a synthetic e2e page.
- The runner: a batch of more than one chunk, a row removed since, a
  repeated token, a refused row, and a defect.
- The Undo on each inverse.
- The bucket removed when the last session leaves it.
- `make bench`: a reclassification row at 9.1 ms at p95, so a chunk holds
  about 300 rows.

Every PR ran `make render-pages` before and after, and attributed each
differing file. Full `make check` was green at every merged commit.

Not yet run: one Orca transcript over the shipped interface. #1335 holds
every check.

## What stays open

Follow-ups the wave filed, none of which gates it: #1261 and #1262 on
the column choice, #1315, #1317, #1293, #1325, #1326, #1275, #1100 behind
#798, #1266 behind #725–#736, and #1335.
