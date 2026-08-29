# Make removal one act

Issue [#944](https://github.com/KucharczykL/timetracker/issues/944). It closes
[#929](https://github.com/KucharczykL/timetracker/issues/929). #653 and #669
built the husk this specification takes apart. #937 named the husk. #675 built
the player act that this specification renames.

## The defect

Delete has two outcomes today, and the condition that picks one is invisible.
`tombstone_or_delete()` asks `must_be_retained()`. A `REQUIRED` reference makes
the answer true, and the row survives as a husk. No reference makes the answer
false, and the row is destroyed. The page promises the same thing either way.

Four ideas of removal exist beside each other:

1. a destroying delete, for Session, Purchase, PlayEvent and GameStatusChange
2. the husk, for Game, Platform and Device
3. `PlayerGame.archived_at`, which #675 added and nothing calls
4. the live `PlayerGame` row a husk leaves behind, which still says the library
   tracks the game

## The act

Removal becomes one act with one verb. Nothing a user can reach destroys a row.

| Act | Verb | Column | Applies to |
| --- | --- | --- | --- |
| Take a record out of the library | remove | `removed_at` | every record a user can remove |
| Put it back | restore | clears `removed_at` | the same |
| Destroy a library and its events | purge | none | a whole library only |

`delete` leaves the domain. It means Django's `.delete()` and nothing else.

## Where the mark lives

| Model | Mark | How |
| --- | --- | --- |
| Game, Platform, Device | `removed_at` | `tombstoned_at` renamed |
| Session, PlayEvent, FilterPreset | `removed_at` | a new column |
| Purchase | `removed_at` | a new column, and the rule below |
| PlayerGame | `removed_at` | `archived_at` renamed |
| Edition, Release | none | read the parent Game |
| GameStatusChange | none | no screen removes one, and #771 drops the table |

`TombstonableQuerySet` becomes `RemovableQuerySet`. Session, PlayEvent, Purchase
and FilterPreset get the same `for_library()` treatment the catalog three
already have: the method calls `alive()`, so a list, a form, a filter and an API
response each exclude a removed row without asking. About 110 references reach
these methods.

`games/removal.py` holds `remove(instance)`, `restore(instance)` and the tuple
of removable models. `games/retention.py` keeps what it is about: the reference
index, the resolver, the replay check and the purge exemption.

## A parent hides its children

Only the removed row takes a stamp. A child reads the parent.

`Session.for_library()` and `PlayEvent.for_library()` already join the game.
They gain one condition, `game__removed_at__isnull=True`. `Edition` and
`Release` read the same column today and change only its name.

This gives two properties for free. Restoring a game restores everything below
it in one statement. A session the user removed by itself keeps its own stamp,
so restoring its game leaves it removed. Neither needs a batch identity, and
neither needs a column on a child.

## Purchases

A Purchase names many games, so it cannot read one parent.

`Purchase.for_library()` filters `removed_at IS NULL` and one `EXISTS` over its
live games. A bundle stays while any one of its games stays. A bundle whose
games are all removed hides, and comes back with the first of them.
`num_purchases` counts the live games only.

`detach_game_from_purchases()` goes. It exists because a husk skips the
`pre_delete` receiver, and because an emptied Purchase was destroyed. Neither
condition remains.

## Removing a game is two writes

A projection row changes through an event only, and `run_in_transaction` refuses
to nest, so one transaction cannot hold both writes.

The order is fixed. The view dispatches `RemovePlayerGame` first. It stamps
`Game.removed_at` second. If the second write fails, the library no longer
tracks the game and every list already omits it, because the list joins the
projection. Running the act again completes it. The opposite order would leave a
hidden game the library still tracks, which is defect 4 above.

## The rename on PlayerGame

#944 lists the archive column, its two commands and its two events under "what
goes". They are renamed instead.

`PlayerGame` is a projection. No code writes it, and `rebuild_projections`
rebuilds every row from the event log. A column that no event states comes back
empty. So `removed_at` on that table exists only if an event type exists to
state it, and that event type is the one #675 already built.

| Now | After |
| --- | --- |
| `PlayerGame.archived_at` | `PlayerGame.removed_at` |
| `ArchivePlayerGame` | `RemovePlayerGame` |
| `CommandName.PLAYERGAME_ARCHIVE` | `CommandName.PLAYERGAME_REMOVE` |
| `library.playergame.archived` | `library.playergame.removed` |
| `PLAYERGAME_ARCHIVED` | `PLAYERGAME_REMOVED` |
| `PlayerGames._archived` | `PlayerGames._removed` |

`RestorePlayerGame`, `PLAYERGAME_RESTORED` and `library.playergame.restored`
keep their names. Restore is already the right word.

No library has recorded an event of the archive type. Nothing dispatches the
command, so the rename moves no data and needs no retired-event tier (#919).

## Denormalized columns

`Game.playtime` is a signal-maintained sum over `game.sessions`. It becomes a
sum over `game.sessions.alive()`. `remove()` stamps through
`save(update_fields=["removed_at"])`, so `post_save` fires and the sum is
recomputed.

Nine reads reach a child through a reverse accessor rather than through
`for_library()`. They are in `games/signals.py`, `games/views/game.py` and
`games/views/playevent.py`. Each takes `.alive()`. A parameterized test over the
removable models proves that `for_library()` hides a removed row, and a
page-level test proves that removing a game empties its sessions from the
session list.

## What goes

- `_delete_everything_but()`, and with it the Django `Collector` surgery
- `Retirement`, which reported which of two outcomes happened
- `tombstone_or_delete()`, replaced by `remove()`
- `games/views/retirement.py`, `confirm_and_retire()` and `retention_message()`
- `games/views/deletion.py` and `confirm_and_delete()`
- the copy that says the record "is kept out of sight rather than deleted"

`games/views/removal.py` holds the generic `confirm_and_apply()` and one
`confirm_and_remove()`. The six routes and their URLs take the verb:
`games:delete_game` becomes `games:remove_game`, and `game/<id>/delete` becomes
`game/<id>/remove`. The `CONFIRMATION` set in `games/views/returns.py` follows.
A bookmark of an old URL breaks; #648 set that precedent for route churn.

The `pre_delete` guard stays. It now guards against a `.delete()` in a shell, a
script or a management command, and its message names `remove()`.

## What still destroys a row

- **A library purge.** `purging_library()` is unchanged. It takes the events
  too, so no recorded reference survives to resolve.
- **The `add_game` rollback.** `games/views/game.py` undoes its own insert when
  the tracking command fails. The row was never visible, and no event names it.
  This is an undone insert, not a removal.
- **Nothing else.** `split_purchase()` destroys the bundle it splits today. It
  stamps it instead, because a user starts it from a screen.

## The confirmation page

The page states the act and what goes with it, and promises nothing further:

> Remove Hollow Knight from your library? Its 43 sessions and 2 purchases go
> with it.

The old copy promised a recovery that has never existed. The new copy must not
promise the recovery this issue does not build either. It says neither
"permanently" nor anything about a husk.

## Undo is not in this issue

#944 asks for an undo on every removal. That moves out. #695 owns it, widened
from Session to every removable record, and #795 owns the recovery screen past
the undo window.

`restore()` still ships and is tested. Reversibility is what makes "nothing is
destroyed" a true statement rather than a hope. No screen calls it yet.

**The issue text needs one edit**: strike "Removing anything offers an undo"
from Acceptance, and record the handoff to #695.

## `alive()` keeps its name

The word paired with `tombstone`, and that pair is gone. `not_removed()`,
`kept()` and `in_library()` were each weighed. The rename is deliberately not
part of this issue, so review does not derive the question again.

## Migrations

- three `RenameField`s for the catalog three, and the four constraint conditions
  that name the column
- one `RenameField` for `PlayerGame`
- four `AddField`s: Session, PlayEvent, Purchase, FilterPreset
- `FilterPreset`'s unique `(library, mode, name)` takes the condition
  `removed_at IS NULL`. Without it a removed preset holds its own name against
  the next one.

`make makemigrations` passes `--noinput`, and the non-interactive questioner
answers no to every rename question. It emits `RemoveField` and `AddField`
instead. Each rename is written by hand.

## Vale and the docs

`tombstone` and `archive` join the refused list, with the domain sense at error
level and every other sense at warning, as `fold` already is. Domain `delete`
joins them: an error when the sentence names a record a user removes, and a
warning otherwise, because `.delete()`, a deleted branch and a deleted file are
all still the right word.

`docs/event-retention.md` keeps the reference index, the guard, the resolver and
the replay check. Its tombstone chapter goes, and the naming section records
`removed_at` as the example. `docs/vocabulary.md` gets a section for each new
word. `CLAUDE.md` follows.

## Delivery

Five commits on one branch. Each passes the full `make check` by itself.

1. Rename in place: `tombstoned_at` to `removed_at`, archive to remove on
   PlayerGame. No behaviour changes.
2. Removal stops destroying: `remove()`, the parent-reads rule, purchases, the
   playtime sum.
3. `removed_at` on Session, PlayEvent, Purchase and FilterPreset; the views and
   the two API routes stamp instead of destroying.
4. One `confirm_and_remove()`; the old pair goes; routes, copy and
   `split_purchase()`.
5. Vale rules, docs, and the issue edits.

## Verification

The gate is the full `make check`, including `e2e/`.

Three tests carry the claims. A parameterized test over the removable models
proves `for_library()` hides a removed row and `restore()` brings it back. The
existing equivalence test in `tests/test_retention.py` inverts: two libraries,
one referenced game and one not, and removing either must leave equal state,
because the branch it was written to police is gone. An e2e test walks a game
removal and asserts its sessions leave the session list.

**Grep for `tombston` and `archiv`.** `tests/test_ensure_postgres.py` means a
tar archive. Any other hit is a missed reference.

## Not in this specification

- an undo affordance (#695) or a recovery screen (#795)
- a per-record purge. #944 records why a `REQUIRED` reference needs the
  identity and not the contents, and why demoting `catalog.game` to
  `EVIDENCE_ONLY` is ruled out by `PlayerGame.game` being a `RESTRICT` foreign
  key
- `Purchase.date_refunded`, which is off-convention and older than the rule
- a word for #796 to use, which cannot be restore
