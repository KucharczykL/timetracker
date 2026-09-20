# The bulk-command runner

One act on many rows, run as one batch a person can undo as one. The wave is
[Selectable tables](2026-09-19-selectable-tables-wave-design.md), which states
the shape this issue builds and the reasons behind it.

## The declaration

A bulk action is a value in one table, `games/bulk_actions.py`. Making the
value declares it: `__post_init__` refuses a name twice stated and an inverse
aggregate no event speaks about, then fills the table, so no construction
reaches the table with those refusals unread. `BLOCKING_REFERRERS` validates
through a classmethod instead, because its registry is the tuple at the call
site rather than the type itself. The table is read through a view that admits
no write, and a test holds every entry keyed by the name it states. Each states its name, its label, the
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

One action is declared, the reclassification. Each act's own half lives in
its own module, imported at the foot of the table, so one grep is the whole
inventory.

## The two POSTs

One route, `/bulk/<action>/`, tells its two POSTs apart by the submission
token. A POST without one resolves the selection statement under the library,
and answers a confirmation naming the act and how many rows it reaches, the
rows themselves to a cap, every refusal with its reason, a fresh token, and
the resolved keys. A POST with one acts.

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
confirmation is counted lost. A row a command finds already in the state it
would state is counted apart from one the act moved, because a count of what
was done must not claim work nobody did. A defect ends the batch, the rows
already done stay done, and the answer says how many.

The answer states sentences and the log states keys. Every row left alone is
named there under the batch's identity, a row the resolve refused as surely as
one the command refused, because the person reading a toast asks how many and
whoever reads the log afterwards asks which.

## The batch

Every append of a batch shares the correlation id and states the action's name
in its source metadata. Each wrapper the runner drives takes a source-metadata
parameter to carry it. Nothing validates the name at the append, so the Undo
refuses a name the table does not hold, and a correlation that states no name
is no batch and is not found.

The Undo reads one event of that correlation to learn which action ran, and the
aggregates of the events of that action's aggregate type to learn its rows. It
then applies the inverse to each, as a batch of its own: its own token and
correlation id, the same budget, the same progress page, its own answer. A row
whose inverse is refused is named, and the rest are undone.

That read needs an index. `LibraryEvent` declares two beside its sequence:
`(library, correlation_id)`, which the batch reader uses, and
`(library, aggregate_id)`, which the move inverse uses in its own issue.

## The Library page

The reclassification is the runner's first act. Its "Move all" button states an
`all` selection over the review, and its words promise the Undo. A selection
names a scope and a count, never a list of keys: the runner resolves the scope
again at the press, so a page left open acts on what is there.

## Proof

Tests cover two chunks under one correlation, a token posted twice, a row lost,
a row refused, a defect, a filter that cannot be parsed, a count that moved,
and a batch whose Undo reads past the record events to the sessions.
`make bench` times 600 rows through the runner's own loop against the
per-command budget, the resolve and the dispatch together, because a chunk
spends its budget on both. Measured on the 2026-09-20 seed: p50 8.3 ms, p95
9.1 ms, max 14.0 ms against the 100 ms a command is given, of which the
resolve is 1.9 ms at p95. It is the dearest of the four the bench times,
because one row is two events. At that cost a three-second chunk holds about
three hundred rows, and the replay of the batch it wrote reconciles clean. The
recording is `docs/event-benchmarks.md`.

> This spec is over the 200 to 500 word band. It holds six rules the code
> keeps: what an action declares and why it names an aggregate type, how one
> route tells its two POSTs apart and why the token is the correlation id, what
> a chunk is and is not, how a batch is named and undone, what the index is
> for, and what proves it. Cutting to the band drops a rule rather than a word.
