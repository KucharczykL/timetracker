# Make removal one act

Issue [#944](https://github.com/KucharczykL/timetracker/issues/944). It closes
[#929](https://github.com/KucharczykL/timetracker/issues/929).

## The act

A library has one act that takes a record out, and one act that destroys.

| Act | Verb | Column | Applies to |
| --- | --- | --- | --- |
| Take a record out | remove | `removed_at` | every record a user can remove |
| Put it back | restore | clears `removed_at` | the same |
| Destroy a library and its events | purge | none | a whole library only |

`delete` is Django's word. It has no domain sense.

## Where the mark lives

`removed_at` is on Game, Platform, Device, Session, PlayEvent, Purchase,
FilterPreset and PlayerGame. It is a nullable `DateTimeField`, and null is the
live state. Edition and Release read the parent Game.

`games/removal.py` holds `remove()`, `restore()` and the removable models.
`games/retention.py` holds the reference index, the resolver, the replay check
and the purge exemption.

`PlayerGame` is a projection, thus its mark exists only because an event states
it: the `RemovePlayerGame` command and the `library.playergame.removed` event.

## Where a removed row is not visible

`RemovableQuerySet.alive()` excludes a stamped row. `for_library()` and
`visible_to()` call it. Thus a list, a form, a filter and an API response each
exclude a removed row.

## A parent hides its children

Only the removed row takes a stamp. A child reads the parent.
`Session.for_library()` and `PlayEvent.for_library()` add the condition
`game__removed_at IS NULL`.

This gives two properties. A restore of a game restores all its children in one
statement. A session that a user removed by itself keeps its own stamp, thus a
restore of its game does not show that session again.

## Purchases

A Purchase names many games, thus it cannot read one parent.
`Purchase.for_library()` requires `removed_at IS NULL` and one live game, or no
game at all. `num_purchases` counts the live games only.

## Removing a game is two writes

A projection changes through an event only, and `run_in_transaction` refuses to
nest. Thus one transaction cannot hold both writes.

The order is fixed. The view dispatches `RemovePlayerGame`, then it stamps
`Game.removed_at`. If the second write fails, the library no longer tracks the
game and each list already omits it. A second attempt completes the act. The
opposite order leaves a hidden game that the library still tracks.

## The stamp is an UPDATE

`remove()` writes with `update()`. Game, Platform, Session and Purchase each
override `save()` to call `clean()`, and a stamp must not validate a row again.
An `update()` sends no `post_save`, thus `remove()` does by hand what a receiver
did: a removed Session recalculates its game's playtime, and a removed Game
counts its purchases again.

## What still destroys a row

- A library purge. `purging_library()` stops the guard, and a purge takes the
  events also, thus no recorded reference stays to resolve.
- The `add_game` rollback, which undoes an insert that no user saw.

No screen destroys a row. The `pre_delete` guard thus speaks to a shell, a
script and a management command.

## The confirmation page

The page states the act and what goes with it. It promises no recovery.

> Remove Hollow Knight from your library? Its 43 sessions and 2 purchases go
> with it.

## Not in this specification

- an undo (#695) or a recovery screen (#795)
- a per-record purge
- a different name for `alive()`
