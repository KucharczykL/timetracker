# The selection line's actions

Issue: [#712](https://github.com/KucharczykL/timetracker/issues/712). Part of
the [Selectable tables wave](2026-09-19-selectable-tables-wave-design.md).

A person selects rows and acts on them from the line that counts them. The
tray is that line, not a surface of its own.

## What a view declares

`SelectionDeclaration` states `actions` and a token beside `filter`. An
action is a `SelectionAction`: a label, a URL and a cardinality, which
`common/` spells in its own words and no act states for it. The view builds
each one from the act table and gives the URL the origin the person stands
on, so the act returns there. The line reverses nothing and names no route,
which is what lets a page with a stripped URL table render one.

The line renders one form into `[data-selection-actions]`: the token, a
hidden field, and one submit for each act, each with its own `formaction`.
The field's name is stated once, where the line is built, and the route
reads that statement. One form, because a button that posts on its own renders a
form of its own, and every such form would carry a copy of the statement.
Only a `many` act is rendered; `ONE` waits for #718, which puts the row's
own pages in the line.

## The slot's element

`<selection-actions>` asks `<selectable-table>` for the statement when it
connects, and reads `selectable-table:change` on it after that: the element
above it upgrades first and announces a restored selection before this one
exists, so a statement only announced is a statement missed. It writes the
statement into the hidden field and disables every submit while the count is
zero. The statement is the posted grammar already, so nothing is translated.

A submit stops the writing. `<selectable-table>` answers the submit by
forgetting the selection, which announces an empty statement while the form
is still being read, so the element that wrote the field ignores every
change from the press onwards. The rule is the order: what a person pressed
is what posts.

## Bulk Remove

Three acts, one for each row a selectable table holds: a session, a run, a
record. Each states its own scope, which is the list's own read narrowed by
the statement's filter, and its own resolve, which finds the live rows and
reports a row gone since the confirmation as lost. Every other refusal is
the command's: the runner turns a conflict into the sentence the command
wrote, and the batch continues. A run that is its game's last live ordinary
run, and a run sessions name, are refused this way. A run another library's
row names is no refusal but a defect, and ends the batch, as it does
everywhere. The inverse is the restore, which refuses a session a live
record was made from.

Each scope compiles the filter with the library's query context, so a
statement that names a related entity narrows the act as it narrowed the
list. The run's scope reads the list's queryset with its condition aliases,
because the condition is counted at read time and is no column, and a
statement that names it does not compile without them. The run's resolve
numbers each row across every live ordinary run of its game, never across
the selection, or each row a person selects is called the first.

The six removal and restoration wrappers take an idempotency key and source
metadata, both optional and keyword-only, and answer the command's result,
because the runner tells a row it moved from a row already so. Two of the
three modules thread neither today, and their dispatch helpers grow with
them. A single-row route states neither and behaves as before.

## The confirmation

`BulkAction` is generic in its row, and so are the resolution and the four
callables it states. The runner holds any row, as it does today. The act
states `preview`, a column for each fact the person needs: a heading, an
alignment, and a cell made from one row and the presentations the request
carries, days and durations alike. The runner keeps the cap, the "and N
more" line and the table, so every act reads alike and one change widens
them all. Both sentences of the confirmation, the one over rows and the one
over none, name the act's `subject`.

## What moves

The Playtime page's two lists, Game detail's two tables and the Playthrough
list become selectable and offer Remove. Each row names itself, and Game
detail states its request, or two tables of two people share one stored
selection. The session list offers the reclassification as well, and the
Library page's Playtime section loses the button that ran it, keeping its
prose, its count and its link. The Actions columns stay until #718.

## Proof

Vitest covers the slot's element, the statement it posts and the press that
stops it. Pytest covers each act's scope, resolve, run and inverse, a batch
a command refuses row by row, and the confirmation each preview renders. The
end-to-end pass that drove the runner from the Library button drives it from
the line instead, the walk over two chunks with it.
