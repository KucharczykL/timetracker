# The bulk-command runner

One act on many rows, run as one batch a person can undo as one. The wave is
[Selectable tables](2026-09-19-selectable-tables-wave-design.md), which states
the shape this issue builds and the reasons behind it.

## The declaration

A bulk action is a value in one table, `games/bulk_actions.py`, constructed
only through `BulkAction.on`, as `BLOCKING_REFERRERS` is, and a test holds the
table complete against the routed names. Each states its name, its label, the
noun its answer speaks of, and the cardinality the tray reads later, beside
five things:

- the **scope**, its own base queryset narrowed by the statement's filter. The
  base is the action's, so a rule no filter field can state stays in the base:
  the review offers no bucket row, and none enters the scope to be refused one
  by one. The filter is parsed here and one that cannot be parsed refuses the
  act. `apply_structured_filter` drops a filter it cannot read and the view
  renders the list whole, which for an act would widen it to every row;
- the **resolve**, which sorts keys into the rows it may act on and a sentence
  for each it may not;
- the **run**, which dispatches one row through its wrapper in `games/writes/`;
- the **inverse**, which states the opposite;
- the **aggregate type its inverse takes**. One act may write more than one
  aggregate: the reclassification appends a created record beside the moved
  session, under one correlation, and the inverse takes the session. Without
  this the Undo would hand each record's key to a command that reads sessions
  and refuse every row of its own batch.

This issue declares one action, the reclassification.

## The two POSTs

One route, `/bulk/<action>/`, tells its two POSTs apart by the submission
token. A POST without one resolves the selection statement under the library,
and answers a confirmation naming the act, its count and its scope, the rows to
a cap, every refusal with its reason, a fresh token, and the resolved keys.
A POST with one acts.

The keys ride one field, never one per row: a field per row meets Django's cap
at a thousand, and a page of keys does not fit a URL. The same field carries
the tally, so the runner keeps nothing between requests, as an origin is kept
nowhere but its parameter.

The token **is** the batch's correlation id, a UUIDv7 the confirmation mints.
One identity, so a batch that spans two requests is still one batch, and the
Undo route names the same value the confirmation wrote.

Both this route and the batch Undo are origin-aware. They act on POST and leave
the page.

## The chunk

A chunk is the rows one request acts on inside a time budget. It is no
transaction: each row is its own dispatch, keyed from the token and the row, so
a token posted twice converts nothing twice. Such a key answers from what it
produced, or refuses as a mismatch where the row's own statement moved since,
because the fingerprint covers what the command was given. Rows left over
render a progress page, which states the tally, posts the rest back, and offers
a Stop. With scripting the page continues by itself; without it, a person
presses Continue.

A refusal names its row and the next row runs. A row gone since the
confirmation is counted lost. A defect ends the batch, the rows already done
stay done, and the answer says how many.

## The batch

Every append of a batch shares the correlation id and states the action's name
in its source metadata. Each wrapper the runner drives gains a source-metadata
parameter; none takes one today, and the field has no reader in the app before
this one. Nothing validates the name at the append, so the Undo refuses a name
the table does not hold.

The Undo reads one event of that correlation to learn which action ran, and the
aggregates of the events of that action's aggregate type to learn its rows. It
then applies the inverse to each, as a batch of its own: its own token and
correlation id, the same budget, the same progress page, its own answer. A row
whose inverse is refused is named, and the rest are undone.

That read needs an index. Migration `0012` adds `(library, correlation_id)`,
which the batch reader uses, and `(library, aggregate_id)`, which the move
inverse uses in its own issue. `LibraryEvent` declares no index today.

## The Library page

The reclassification is the runner's first act. Its "Move all" button states an
`all` selection over the review, and its words start promising the Undo.

## Proof

Tests cover two chunks under one correlation, a token posted twice, a row lost,
a row refused, a defect, a filter that cannot be parsed, a count that moved,
and a batch whose Undo reads past the record events to the sessions.
`make bench` times 600 sessions through the runner against the per-command
budget.

> This spec is over the 200 to 500 word band. It holds six rules the code
> keeps: what an action declares and why it names an aggregate type, how one
> route tells its two POSTs apart and why the token is the correlation id, what
> a chunk is and is not, how a batch is named and undone, what the index is
> for, and what proves it. Cutting to the band drops a rule rather than a word.
