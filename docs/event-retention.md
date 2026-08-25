# Retaining a referenced row

An event is immutable. A `REQUIRED` reference in its payload promises that a
replay can find the row it names. A hard delete breaks that promise, and no
later code can repair it: the row is gone and the payload still points at it.

This is the policy that keeps the promise. The code is in
`games/retention.py`. The payload side of the contract is in
[Durable references in event payloads](event-references.md).

## The two outcomes

Deleting a `Game`, `Platform` or `Device` goes through
`archive_or_delete(instance)`, which returns which of two things happened.

| Outcome | When | What is left |
|---|---|---|
| `DELETED` | No recorded event names the row | Nothing. The ordinary delete, unchanged |
| `ARCHIVED` | An event names the row under a `REQUIRED` kind | The row, with `archived_at` set. Everything else the delete would have taken is gone |

An archived row is not a lighter kind of delete. Everything a real delete would
have done still happens — the sessions, the play events, the purchase
bookkeeping, the `SET_NULL`s. Only the row itself stays.

## Where the collateral comes from

`_delete_everything_but` asks Django's own `Collector` what deleting the row
would take with it, drops the root from what it collected, and runs the rest.
Enumerating the cascades by hand would be a second copy of every `on_delete`,
free to drift from the first, and the drift would surface as orphaned rows in a
list view.

One thing the collector cannot know about: `Game`'s purchase bookkeeping lives
in a `pre_delete` receiver, and archiving never deletes the row, so the receiver
never fires. `detach_game_from_purchases` is that logic, called by both the
receiver and the archive path so there is one implementation rather than two.

`tests/test_retention.py::test_archiving_leaves_exactly_what_deleting_would`
is the guard: the same fixture in two libraries, one game referenced and one
not, and the two resulting library states must be equal.

## Where an archived row disappears from

`archived_at` is excluded inside `for_library()` and `visible_to()`, the two
methods every user-facing read goes through. A list, a form, a filter, an API
response — none of them has to remember to ask.

`Edition` and `Release` have no `archived_at` of their own. They have no
visibility of their own either, so their querysets filter on the parent
`Game`'s column.

Uniqueness is partial on `archived_at`, on both `Game` constraints and both
`Platform` constraints. An archived row is gone as far as the library is
concerned, so it must not be what stops the same name being entered again.
Django skips a conditional constraint during *form* validation when the
condition names a field the form excludes, which is why
`_LibraryBoundConstraintValidationMixin` (`games/forms.py`) keeps `archived_at`
out of the exclusions — otherwise a live duplicate would reach the database as
an `IntegrityError` instead of a field error.

Three reads deliberately see archived rows, all through the plain manager:
`resolve_reference`, the retention policy itself, and the audit/ownership
inventories.

## Resolving

`resolve_reference(reference)` returns the row a recorded reference names,
archived or not. It raises `UnresolvableReference`, which carries the reference
rather than only a message, when the row is not there at all.

#653 ships this resolver and proves an archived row resolves through it.
Failing a *replay* that cannot resolve a reference, and reporting which
references could not be reconciled, is #669's.

## The guard

A `pre_delete` receiver on all three models raises `ReferencedRowDeletion`
rather than let a referenced row be deleted. It is connected in
`games/signals.py`, not left to the three delete views, because a promise only
one call path keeps is not a promise — a shell, a script or a management
command is held to it too.

Note that a receiver on `Platform` and `Device` rules out Django's fast-delete
for them. The cost lands on a whole-library purge, which is the only operation
that deletes them in bulk.

### The one exemption

`purging_library()` turns the guard off for the duration of a whole-library
purge, and `delete_user_library` enters it. A purge takes the events with the
rows, so afterwards there is no recorded reference left to resolve and nothing
to retain the row for. Without the exemption the guard would make the one
operation allowed to leave nothing behind impossible to complete.

The exemption is a context variable, so it does not outlive the `with` block
and does not leak to another thread.

## The confirmation page

`games/views/retirement.py` is the delete affordance for these three models: a
sibling of `confirm_and_delete` that asks the policy what the POST will do and
says so. Promising a permanent delete and then archiving would be worse than
either outcome on its own, so the copy switches when the row is referenced.

## What is not here

- Replay-time enforcement and the reconciliation report (#669).
- A user-visible Trash or recovery UI (#795). Archiving in place rather than
  writing a tombstone stub is what leaves that possible: the `Edition`/`Release`
  graph and every external reference survive intact.
