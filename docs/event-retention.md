# Retaining a referenced row

An event is immutable. A `REQUIRED` reference in a payload is a promise that a
replay finds the row. Destroying the row breaks the promise. No later code can
repair it: the row is gone and the payload keeps the id.

This is the policy that keeps the promise. The code is in
`games/retention.py`. The payload side is in
[Durable references in event payloads](event-references.md).

## No screen destroys a row

Since #944 a user has one act: remove. `games.removal.remove(instance)` sets
`removed_at`, and `restore(instance)` sets it back to null. The row stays, all
its data stays, and only a purge of the full library destroys anything.

Thus the retention question no longer has two outcomes. Every screen keeps the
row, whether or not an event names it, and this policy governs the paths a
screen cannot reach: a shell, a script, a management command, and a purge.

## The index

`LibraryEventReference` holds one row for each reference in each event. The
append writes it. The payloads hold the same data, but a scan of the payloads
is a scan of the full log. The index makes the retention question a lookup.

The append writes the index in the same transaction as the events, under the
same lock. Thus a row is protected at the moment the event that names it
commits. There is no interval in which the guard permits a destroying delete of
that row.

## Where a removed row is not visible

`for_library()` and `visible_to()` exclude a removed row. All reads for a user
go through these two methods. A list, a form, a filter and an API response do
not each apply the exclusion.

`Edition` and `Release` have no `removed_at` column. They also have no
visibility of their own. Their querysets read the column of the parent `Game`.

Each uniqueness constraint on `Game`, on `Platform` and on `FilterPreset` has
the condition `removed_at IS NULL`. A removed row is not in the library. Thus
it must not prevent the entry of the same name again. `Platform.clean()`
applies the same condition, so the message to the user agrees with the
constraint.

The conditions have one effect that is easy to miss. Django does not validate a
conditional constraint in a form when the condition names an excluded field.
`removed_at` is not editable, thus a form always excludes it. Without a
correction, no constraint here operates during form validation, and a duplicate
becomes an `IntegrityError` and not a field error.
`_LibraryBoundConstraintValidationMixin` in `games/forms.py` keeps `removed_at`
out of the exclusions. A row that a form reaches is a live row, thus the value
is always NULL, which is the value the condition expects.

Three readers see removed rows. They use the plain manager: the resolver, this
policy, and the audit inventories.

## Resolving a reference

`resolve_reference(reference)` gives the row that a recorded reference names.
The row can be removed. The function reads through `_default_manager`, which is
the plain manager on all three models.

If no row answers, the function raises `UnresolvableReference`. The exception
holds the reference and not only a message, thus a caller can say which
reference did not resolve.

`unresolved_among(kind, references)` answers the same question for a set of index
rows. It is in this module, beside the resolver. One module owns what resolves.
If the two rules were in two modules, a removed row could pass one and fail the
other.

## The replay check

`require_resolvable_references(library)` stops a replay of a library that records
a reference to a row that no longer exists. `replay()` calls it after it reads
the stream head and before it reads the first event. The code is in
`games/events/reconcile.py`.

The check reads the index and not the payloads. It takes the kind names that the
index holds. For each `REQUIRED` kind it makes one anti-join against the model of
that kind, through the plain manager. Thus a removed row resolves. The check
does not query an `EVIDENCE_ONLY` kind, because for that kind the snapshot is
sufficient.

If each reference names a row, the replay continues. If one reference does not,
the check raises `UnresolvedReferences`. The exception holds a
`ReferenceReconciliation`: the library, the kinds that the check examined, the
number of rows that no longer exist, and a description of the first 20 of them,
in the order of the kind and the row id. The number is always complete. The
description is not. A purge-shaped accident must not give a report of ten
thousand lines.

The description of one gap gives the kind, the id, the payload key, the sequence
of the first event that names the row, the number of events that name it, and the
snapshot that the first event recorded. This is the only step that reads a
payload. The snapshot says what the row was called. It does not replace the row.
Nothing here writes a row again.

The two modes of `rebuild_projections` refuse. The refusal occurs before a
shadow table holds a row, thus there is no report of the tables to give.
`manage.py rebuild_projections` prints the full description to the error output
and exits with a non-zero status in the two modes. A `--check` exits zero for
drift, because a rebuild removes drift. A row that no longer exists is not a
condition that a rebuild repairs.

The message gives the remedy. Put each row back with the same id, or purge the
library. A purge takes the events, thus no recorded reference stays to resolve.

The check has two limits, and they are the limits of the index. The check reads
the index, thus a reference that the index does not hold is not visible to it.
The append writes the index in the same transaction as the events, which is what
makes the index complete. The check also runs before the handlers, thus it is
not a lock. The guard keeps a referenced row, and no screen destroys one, thus
nothing can take a row between the check and the handlers. A purge of the full
library can occur, and it takes the events also.

## The guard

A `pre_delete` receiver on the three models raises `ReferencedRowDeletion`. The
receiver is in `games/signals.py`. Its audience is the shell, the script and
the management command, because no view reaches it: a view removes, and a
remove is an `UPDATE`.

A receiver on `Platform` and on `Device` prevents the Django fast delete for
those models. Only a purge of a full library takes them in quantity, thus the
cost applies only there.

### The order

The three models are subclasses of `ReferencedRow`. Its `delete()` asks the
policy before it calls `Model.delete()`.

`Model.delete()` collects the related rows before it sends `pre_delete`. A
`RESTRICT` relation, such as `PlayerGame.game`, thus refuses first and raises
`RestrictedError`. That error names a foreign key. It does not tell the caller
to remove the row instead. The override makes the policy speak first, and the
receiver stays the backstop for the paths that do not call `Model.delete()`.

A queryset delete is one such path. `Game.objects.filter(...).delete()` still
raises `RestrictedError` for a tracked game. Each such call a person starts
takes one row, thus each message a person reads is the policy's.

### The one exemption

`purging_library()` stops the guard for a purge of a full library.
`purge_user_library` uses it. A purge also takes the events. After a purge
no recorded reference stays, thus no row needs retention. Without the
exemption the guard stops the one operation that is permitted to leave nothing.

The exemption is a context variable. It ends with the `with` block. It does not
go to a different thread.

## Naming

One act takes one verb. The event type, the command and the projection column
all use that verb.

The column names the act in the past participle: `<act>_at`, and a name for what
the act touches can come first. It is a nullable `DateTimeField`, and null is
the live state. Thus `removed_at`, `voided_at`, `access_ended_at`.

A fact about the world and a retraction of a record are two acts, thus they take
two verbs. An end of access and a refund are facts. A void is a retraction.

`Purchase.date_refunded` is older than the rule.

## Not in this contract

- A Trash screen that lists what a library removed, and an undo (#695, #795).
  The rows and the column are already there; nothing yet reads them back.
