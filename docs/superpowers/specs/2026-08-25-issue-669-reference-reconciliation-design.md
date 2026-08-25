# Reference reconciliation before a replay

Issue [#669](https://github.com/KucharczykL/timetracker/issues/669). The code is
in `games/events/reconcile.py`. The policy it reads back is in
[Retaining a referenced row](../../event-retention.md).

## The check

`require_resolvable_references(library, *, kinds)` refuses a library that records
a reference to a row that no longer exists. `replay()` calls it after it reads
the stream head and before it folds the first event. A library with no head
returns before the check. There is no option to skip the check.

`reconcile_references(library, *, kinds)` gives the same answer as a
`ReferenceReconciliation`. The check is read-only.

## The rules

- The check reads the reference index and not the payloads. The retention guard
  reads the same index. Thus the guard and the check cannot disagree about the
  references of a stream.
- The kind names come from the index. A name that the registry does not hold
  raises `UnknownReferenceKind`.
- Each `REQUIRED` kind gets one anti-join, in the form
  `~Exists(kind.model._default_manager.filter(pk=OuterRef("referenced_id")))`.
  The plain manager sees an archived row, thus an archived row resolves. A
  `NOT IN` subquery gives a different result if the column becomes nullable.
- An `EVIDENCE_ONLY` kind gets no query. For that kind the snapshot is
  sufficient.
- `unresolved_among()` is in `games/retention.py`, beside `resolve_reference`.
  One module owns what resolves.
- The report holds one gap for each row, and not for each event. A gap gives the
  kind, the id, the payload key, the sequence of the first event that names the
  row, the number of events that name it, and the snapshot from that first
  event.
- The limit applies to the ids, before the check reads a payload. `gaps` holds
  the first `GAP_SAMPLE_LIMIT` ids in the order of the kind and the id.
  `unresolved` holds the true number. The description of a gap is two queries:
  a `DISTINCT ON (kind, referenced_id)` for the earliest event, and one grouped
  `Count`. PostgreSQL makes the distinct columns lead the order, thus the order
  of the report is the order of that query.
- The snapshot describes the loss. It does not replace the row. If the payload
  holds no reference with that id, the label is `no snapshot recorded`.
- `UnresolvedReferences` carries the report. The two modes of
  `rebuild_projections` refuse, before the rebuild stages a shadow table.
  `manage.py rebuild_projections` prints the report to the error output and
  exits with an error in the two modes. A `--check` exits with no error for
  drift, because a rebuild removes drift.
- The message gives the remedy. Put each row back with the same id, or purge the
  library.
- The index read is scoped to one library. A gap in one library refuses the
  replay of that library only. A reference to the row of a different library
  resolves; a scoped resolver is
  [#909](https://github.com/KucharczykL/timetracker/issues/909).

The query count is one, plus one for each kind that the index holds, plus two
for a report with a gap. This issue adds no migration and changes no schema.
