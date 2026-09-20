# The bulk-command runner

One act on many rows, run as one batch a person can undo as one. The wave is
[Selectable tables](2026-09-19-selectable-tables-wave-design.md), which states
the shape this issue builds and the reasons behind it.

## The declaration

A bulk action is a value in one table, `games/bulk_actions.py`, as the command
vocabulary is: one grep, and no entry that is not a thing the app does. It
names itself, its label, the noun its answer speaks of, and the cardinality the
tray reads later. It states four callables: the scope, which turns a filter
into rows and refuses a filter it cannot parse; the resolve, which sorts keys
into the rows it may act on and a sentence for each it may not; the run, which
dispatches one row through its own wrapper in `games/writes/`; and the inverse,
which states the opposite. This issue declares one action, the
reclassification.

The scope parses its own filter. `apply_structured_filter` drops a filter it
cannot read and renders the list whole, which for an act would widen it to
every row.

## The two POSTs

One route, `/bulk/<action>/`, tells its two POSTs apart by the submission
token. A POST without one resolves the selection statement under the library,
and answers a confirmation naming the act, its count and its scope, a sample of
the rows, every refusal with its reason, a fresh token, and the resolved keys.
A POST with one acts.

The keys ride one field, never one per row: a field per row meets Django's cap
at a thousand, and a page of keys does not fit a URL. The same field carries
the tally, so the runner keeps nothing between requests, as an origin is kept
nowhere but its parameter.

Both this route and the batch Undo are origin-aware. They act on POST and leave
the page.

## The chunk

A chunk is the rows one request acts on inside a time budget. It is no
transaction: each row is its own dispatch, keyed from the token and the row, so
a token posted twice replays and converts nothing twice. Rows left over render
a progress page, which states the tally, posts the rest back, and offers a
Stop. With scripting the page continues by itself; without it, a person
presses Continue.

A refusal names its row and the next row runs. A row gone since the
confirmation is counted lost. A defect ends the batch, the rows already done
stay done, and the answer says how many.

## The batch

Every append of a batch shares one correlation id and states the action's name
in its source metadata. The Undo reads one event of that correlation to learn
which action ran and the events' aggregates to learn the rows, then applies the
inverse to each as a batch of its own. A row whose inverse is refused is named,
and the rest are undone.

That read needs an index. One migration adds `(library, correlation_id)`, which
the batch reader uses, and `(library, aggregate_id)`, which the move inverse
uses in its own issue.

## The Library page

The reclassification is the runner's first act. Its "Move all" button states an
`all` selection over the review, and its words start promising the Undo.

## Proof

Tests cover two chunks, a token posted twice, a row lost, a row refused, a
defect, a filter that cannot be parsed, and a count that moved. The Undo is
proven over a real batch, including one whose record was restated since.
`make bench` times 600 sessions through the runner against the per-command
budget.

> This spec is over the 200 to 500 word band. It holds six rules the code
> keeps: what an action declares, how one route tells its two POSTs apart, what
> a chunk is and is not, how a batch is named and undone, what the index is
> for, and what proves it. Cutting to the band drops a rule rather than a word.
