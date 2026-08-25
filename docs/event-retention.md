# Retaining a referenced row

An event is immutable. A `REQUIRED` reference in a payload is a promise that a
replay finds the row. A delete breaks the promise. No later code can repair it:
the row is gone and the payload keeps the id.

This is the policy that keeps the promise. The code is in
`games/retention.py`. The payload side is in
[Durable references in event payloads](event-references.md).

## The two outcomes

A delete of a `Game`, a `Platform` or a `Device` calls
`archive_or_delete(instance)`. The function gives the outcome.

| Outcome | Condition | Result |
|---|---|---|
| `DELETED` | No event names the row | Nothing stays. The usual delete |
| `ARCHIVED` | An event names the row under a `REQUIRED` kind | The row stays, with `archived_at` set. All other data goes |

An archived row is not a smaller delete. All the work of the delete occurs:
the sessions, the play events, the purchase counts and the `SET_NULL`s. Only
the row stays.

## The index

`LibraryEventReference` holds one row for each reference in each event. The
append writes it. The payloads hold the same data, but a scan of the payloads
is a scan of the full log. The index makes the retention question a lookup.

The append writes the index in the same transaction as the events, under the
same lock. Thus a row is protected at the moment the event that names it
commits. There is no interval in which the guard permits a delete of that row.

## What archiving does

`_delete_everything_but` asks the Django collector which rows a delete
collects. It then removes the root from the collection and deletes the
remainder. A list of the cascades in this module would be a second copy of
each `on_delete`. The two copies can become different. The result of a
difference is a row that stays in a list view with no parent.

The collector does not know about one thing. The purchase count of a `Game` is
maintained in a `pre_delete` receiver. Archiving does not delete the row, thus
the receiver does not operate. `detach_game_from_purchases` holds that logic.
The receiver and the archive path both call it. There is one implementation.

`archive_or_delete` sets `archived_at` with a queryset update. It does not call
`save()`. This is a stamp and not a change of the record. `Platform.save()`
operates `clean()` again, and `Game.save()` operates the status-change
receiver. Neither is applicable to a row that leaves the library.

The equivalence is a test, not a claim:
`tests/test_retention.py::test_archiving_leaves_exactly_what_deleting_would`
puts the same data in two libraries. One game is referenced and one game is
not. The two libraries must keep equal state.

## Where an archived row is not visible

`for_library()` and `visible_to()` exclude an archived row. All reads for a
user go through these two methods. A list, a form, a filter and an API
response do not each apply the exclusion.

`Edition` and `Release` have no `archived_at` column. They also have no
visibility of their own. Their querysets read the column of the parent `Game`.

Each uniqueness constraint on `Game` and on `Platform` has the condition
`archived_at IS NULL`. An archived row is not in the library. Thus it must not
prevent the entry of the same name again. `Platform.clean()` applies the same
condition, so the message to the user agrees with the constraint.

The conditions have one effect that is easy to miss. Django does not validate a
conditional constraint in a form when the condition names an excluded field.
`archived_at` is not editable, thus a form always excludes it. Without a
correction, no constraint here operates during form validation, and a duplicate
becomes an `IntegrityError` and not a field error.
`_LibraryBoundConstraintValidationMixin` in `games/forms.py` keeps
`archived_at` out of the exclusions. A row that a form reaches is a live row,
thus the value is always NULL, which is the value the condition expects.

Three readers see archived rows. They use the plain manager: the resolver, this
policy, and the audit inventories.

## Resolving a reference

`resolve_reference(reference)` gives the row that a recorded reference names.
The row can be archived. The function reads through `_default_manager`, which
is the plain manager on all three models.

If no row answers, the function raises `UnresolvableReference`. The exception
holds the reference and not only a message, thus #669 can build the
reconciliation report from the exception.

This issue supplies the resolver. #669 stops a replay that cannot resolve a
reference, and writes the report.

## The guard

A `pre_delete` receiver on the three models raises `ReferencedRowDeletion`. The
receiver is in `games/signals.py`. It is not in the three delete views, because
a shell, a script and a management command must obey the same policy. The
delete views call `archive_or_delete` and do not see this exception.

A receiver on `Platform` and on `Device` prevents the Django fast delete for
those models. Only a purge of a full library deletes them in quantity, thus the
cost applies only there.

### The one exemption

`purging_library()` stops the guard for a purge of a full library.
`delete_user_library` uses it. A purge also deletes the events. After a purge
no recorded reference stays, thus no row needs retention. Without the
exemption the guard stops the one operation that is permitted to leave nothing.

The exemption is a context variable. It ends with the `with` block. It does not
go to a different thread.

## The confirmation page

`games/views/retirement.py` is the delete control for these three models. It
asks the policy what the POST does, and the page gives that text. A promise to
delete, followed by an archive, is worse than each of the two outcomes.

## Not in this contract

- The replay check and the reconciliation report (#669).
- A Trash or recovery screen (#795). An archive in place, and not a stub
  record, keeps that screen possible: the `Edition` and `Release` rows and all
  external references stay correct.
