# The selection line's actions

Issue: [#712](https://github.com/KucharczykL/timetracker/issues/712). Part of
the [Selectable tables wave](2026-09-19-selectable-tables-wave-design.md).

A person selects rows and acts on them from the line that counts them.

## What a view declares

`SelectionDeclaration` states `actions` and a token beside `filter`. An
action is a `SelectionAction`: a label, a URL and a cardinality. `common/`
spells the cardinality in its own words and the view maps the act's word
onto it, so the components layer reads no act table. The view builds each
action from that table and gives the URL the origin the person stands on.
The line reverses no route, which is what lets a page with a stripped URL
table render one.

The line renders one form into its slot: the token, a hidden field, and one
submit for each act, each with its own `formaction` and in the colours the
act states. One form, because a
submit that posts alone renders a form of its own, and each of those would
carry a copy of the statement. The field's name is stated once, where the
line is built, and the route reads that statement. The line renders a `many`
act alone; #718 gives a `one` act the row's own pages.

## The slot's element

`<selection-actions>` subscribes to `selectable-table:change` on the table it
stands in, then asks that table for the statement if it can answer yet. The
table announces a restored selection from its own connect, before this
element upgrades, so a statement only announced is a statement missed; and an
element whose module ran first has a host that answers nothing, so the
subscription is never conditional on the answer. The element writes the
statement into the hidden field and disables each submit while the count is
zero. The statement is the posted grammar already, so the element translates
nothing.

A submit stops the writing. The table answers a submit by forgetting the
selection, which announces an empty statement while the form is read, so the
element ignores each change from the press on. What a person pressed is what
posts. A page the browser brings back is choosing again: no connect runs for
it, so the latch is cleared where the restore is announced, or the next press
states the press before it.

## Bulk Remove

Three acts: a session, a run and a record. Each states the list's own read as
its scope, narrowed by the statement's filter, and a resolve that finds the
live rows and reports a key it does not find as lost. Each scope compiles the
filter with the library's query context, so a statement that names a related
entity narrows the act as it narrowed the list. The run's scope reads the
condition aliases, because the condition is counted at read time and is no
column. The run's resolve numbers each row across every live ordinary run of
its game, never across the selection, or each row a person selects is the
first.

The acts refuse nothing else. A conflict is the sentence the command wrote,
and the batch continues: the last live ordinary run of a game, and a run a
session names, refuse this way. A key this library does not hold is simply
lost, at the resolve and at the inverse alike; a projection row that names
another library's row is a defect, and ends the batch. The inverse is the
restore, which refuses a session a live record was made from.

The six removal and restoration wrappers take an idempotency key and source
metadata, both optional and keyword-only, and answer the command's result,
because the runner tells a row that moved from a row already so. A single-row
route states neither.

## The confirmation

`BulkAction` is generic in its row, and so are the resolution and the
callables it states. The runner holds any row. The act states `preview`: a
heading, an alignment, and a cell built from one row and the presentations
the request carries, days and durations alike. The runner keeps the cap, the
"and N more" line and the table, so each act reads alike. Both sentences of
the confirmation name the act's subject.

## Delivered

Both Playtime lists, the Playthrough list and Game detail's two tables are
selectable and offer Remove. The session list offers the reclassification
beside it. Game detail's two tables state no filter, and its sections state
no paginator, so the line there can name only the rows a person marked: an
act's scope is the library's, and a wider statement would name every row it
holds. The Library page's Playtime section keeps its explanation, its count
and the link to the review, and presses nothing, so the sentence promising an
Undo went with the button. The Actions columns stand until #718.

Vitest covers the statement the slot posts, a selection restored before the
slot upgrades, the press that stops the writing, and the page the browser
brings back. Pytest covers each act's scope, resolve, run and inverse, and
each act's confirmation through the route, where the cells run. Three passes
drive a real browser: two rows removed and put back, a refused row beside
removed siblings, and the runner's walk over two chunks.
