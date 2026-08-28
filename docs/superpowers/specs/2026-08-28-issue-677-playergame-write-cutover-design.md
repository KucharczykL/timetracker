# Switch PlayerGame writes to commands

Issue [#677](https://github.com/KucharczykL/timetracker/issues/677). The code is
a new `games/writes/` package, a new `games/playergame_status.py`,
`games/commands/playergame.py`, `games/forms.py`, `games/api.py`, and the game,
session, play-event and purchase views. #671 gives the row, #672 to #675 give
the commands, #676 gives every library-owned game a row, and #906 gives a repeat
its success.

Six places write `Game.status` or `Game.mastered` directly. After this issue each
one states the fact as a command, and the catalog column is a mirror of the
projection that #678 removes.

This issue also takes the rendering #905 was deferred twice for want of. #677 is
the first evented view, so it is the first place a `CommandRejected` or an
exhausted retry can reach a person.

## The six writes

| Site | Fact today |
|---|---|
| `partial_update_game`, `games/api.py` | status, from the `GameStatusSelector` dropdown |
| `add_game`, `games/views/game.py` | a new catalog row, its status and its mastery |
| `edit_game`, `games/views/game.py` | status and mastery |
| `SessionForm.save`, `games/forms.py` | status unplayed to played, under `mark_as_played` |
| `PlayEventForm.save`, `games/forms.py` | status to finished, under `mark_as_finished` |
| `refund_purchase`, `games/views/purchase.py` | status to abandoned, once per game of the purchase |

Nothing else writes either column. `add_statuschange`, `edit_statuschange` and
`delete_statuschange` edit legacy history rows and leave the game alone; #771
removes them.

## The write path

`games/writes/playergame.py` sits beside `games/commands/playergame.py`,
`games/projectors/playergame.py` and `games/backfill/playergame.py`. It is the
one module that holds both vocabularies at once, thus it is the one module #678
edits to delete the mirror.

Two functions. `track_game(actor, game)` dispatches `TrackGame`.
`record_facts(actor, game, *, status=None, mastered=None)` states one fact or
two, where `None` means this write does not state that fact. Both take an actor
rather than a request: `authorize()` checks `library.user_id == actor.pk`, thus
the actor already names the library, and a test needs no HTTP.

`record_facts` does four things in order.

1. Translates `Game.Status` to `PlayerGameStatus`.
2. Dispatches, with a fresh key.
3. Tracks the game and dispatches once more, if the game had no row.
4. Mirrors the projection onto the catalog.

A single stated fact dispatches `SetPlayerGameStatus` or
`SetPlayerGameMastered`. Two stated facts dispatch the composite below, so the
form's two facts stay one act.

The game form always states both facts, whether or not the player touched
either. Filtering by `form.changed_data` would give `SetPlayerGameMastered` its
only caller, and it would move "does this state already hold" out of `build()`,
which is where #906 put it and where a stale `initial` cannot reach it. The
command answers the question; the view does not pre-empt it.

## Why the mirror is not a projector

A projector folding `library.playergame.status_changed` into `Game.status` would
be one write path rather than two, and a rebuild would reproduce the catalog
column with the projection. It cannot be built. `only_shadow_writes()`
(`games/events/rebuild.py:110`) refuses every statement that writes outside a
shadow table, because a rebuild must write nothing but its own copies. A family
that wrote `games_game` would raise on the first fold of every rebuild.

The refusal is right and the mirror is what moves. The catalog column is not a
projection: it is the old storage, kept correct for the readers #678 has not
moved yet.

## The mirror reads the fold

After a dispatch returns, `record_facts` reads the `PlayerGame` row back and
writes the mapped values onto `Game`. It does not write what the caller asked
for.

A mirror that reads the fold cannot disagree with it. The two differ whenever a
command declines what was asked, and #906 made that an ordinary outcome:
`UNCHANGED` and `REPLAYED` both return without appending, and the state that
holds is the state the projection states.

`Game.save(update_fields=["status", "mastered"])` performs the write, thus the
`pre_save` audit signal fires and legacy `GameStatusChange` history continues
exactly as today.

`games/playergame_status.py` holds both directions of the vocabulary map.
`player_status_for()` moves there from `games/backfill/playergame.py`, which
imports it back; `legacy_status_for()` is new. `PlayerGameStatus.SHELVED` has no
member of `Game.Status`, thus `legacy_status_for()` raises for it. Nothing emits
`shelved`, and the dropdown offers `Game.Status.choices` until #678 moves the
reads, so the raise is a guard rather than a path.

## The composite command

`RecordPlayerGameFacts` joins the six in `games/commands/playergame.py`, under
`CommandName.PLAYERGAME_RECORD_FACTS`, `library.playergame.record_facts`. Its
fields are `game_id`, `status` of `PlayerGameStatus | None`, and `mastered` of
`bool | None`.

`build()` reads the row once and returns the events for the stated facts that
differ: a `status_changed`, a `mastered_changed`, or both. The event types are
#672's and #673's, thus the projector, the replay and every rebuild are
untouched by this issue. Nothing stated differs, and it returns `Unchanged` —
the outcome #673 forecast and #906 delivered, for the save that changes nothing.

`None` is a field value like any other, thus it enters the fingerprint. Two
saves that state different facts are two different commands under one key, which
is what `IdempotencyKeyMismatch` exists to catch.

## A game with no row

`_tracked_game()` rejects a game the library does not track. #676 backfilled a
row for every game a library held, and `add_game` tracks each new one, so the
rejection means the two fell out of step: a `TrackGame` that did not commit, a
row from a restored dump, a game the sample loader made.

The rejection becomes its own class, `PlayerGameNotTracked(CommandRejected)`,
raised by `_tracked_game()`. `record_facts` catches that one class, dispatches
`TrackGame`, and dispatches the original command again. Matching on a message
would be the alternative and it is not one.

An untracked game is otherwise unwritable forever, and it is reachable: creating
the catalog row and tracking it are two commits, because `run_in_transaction`
refuses a nested transaction (`games/events/retry.py:113`) and a view therefore
cannot hold both in one. The heal makes the second commit's failure a delay
rather than a dead row.

## The keys name the request

Each dispatch takes `str(uuid.uuid7())`, as #670's benchmark already does.

The alternative is a key derived from the command and the game, and #675's
review recorded why it is wrong: `idempotent_append` reads the key before
`build()` runs, thus archive, restore and archive under one key append one event
and report success for an archive that did not happen.

A fresh key means a resubmitted browser POST is a second request and appends a
second event. Nothing here defends against that, and nothing did before. A
client-supplied token would, and it is a separate change to every form and to
the dropdown's fetch; #740 is the issue that will want it.

## The form

`GameForm` declares `status` and `mastered` as plain form fields and drops them
from `Meta.fields`. They render, validate and take their initial value from the
instance exactly as now, and `form.save()` writes neither. The single writer is
the write path.

`add_game` is the exception, and deliberately. It assigns the two cleaned values
onto the unsaved instance, saves, tracks the game, and then states both facts. A
new catalog row starts at the state the form states, so the mirror finds the
projection and the catalog already equal and writes nothing.

Creating the row at the column default and letting the mirror move it would
append a `GameStatusChange` that today does not exist: `game_status_changed`
returns early when no previous row exists (`games/signals.py:147`), thus a game
created as Played records no transition today and would record one after. The
assignment keeps legacy history byte-identical.

`edit_game` takes no such exception. It saves the catalog fields, then states the
two facts. The order matters: a dispatch that fails must leave the catalog where
it was, never the other way round.

## The call sites

| Site | After |
|---|---|
| `partial_update_game` | `record_facts(status=payload.status)`, then 204 |
| `add_game` | assign, `form.save()`, `track_game()`, `record_facts(status, mastered)` |
| `edit_game` | `form.save()`, then `record_facts(status, mastered)` |
| session views | `record_facts(status=PLAYED)` when `mark_as_played` and the game reads unplayed |
| play-event views | `record_facts(status=FINISHED)` when `mark_as_finished` |
| `refund_purchase` | `record_facts(status=ABANDONED)` per game, then the refund |

`SessionForm.save` and `PlayEventForm.save` lose their status flips, and
`PlayEventForm.save` loses the `transaction.atomic()` that wrapped them: a
dispatch inside it would raise `NestedTransactionNotSupported`, and one
remaining save needs no block. A form has no actor, thus the fact moves to the
view that has one.

The session guard keeps reading `Game.status`, because every read reads the
catalog until #678. Without it a completed game would fall back to played.

`partial_update_game` gains a real validation. `GameStatusUpdate.status` becomes
a `Game.Status` rather than a `str`, thus Ninja refuses an unknown member with a
422 before the view runs. Today the value reaches the column: `Game.save()`
calls `clean()` and not `full_clean()`, and neither checks choices.

`refund_purchase` dispatches once per game and the dispatches do not share a
transaction. A failure part-way abandons some games and refunds nothing, which
is the failure shape the loop of `game.save()` calls has today.

## Failures at the view boundary

The write path raises `Http404` for `CommandNotPermitted`, and
`PlayerGameWriteFailed(message, status_code)` for the rest. One `_translate` in
`games/writes/playergame.py` owns the table.

| Raised | Becomes | Wording |
|---|---|---|
| `CommandNotPermitted` | `Http404` | Django's own |
| `CommandRejected`, after the heal | 409 | the command's own sentence |
| `RetryBudgetExhausted` | 409 | lost to a concurrent write, try again |
| `IdempotencyKeyMismatch` | 409 | this request cannot be retried |
| `UNCHANGED` | the ordinary success | the toast a change shows |

`CommandNotPermitted` is a 404 because the charter says an object of another
library is returned as not found and not disclosed through a permission error.
The two leaves of `CommandConflict` keep the distinct treatment #905 asked for:
one says try again and one says this will never work. A mismatch is unreachable
under per-request keys and is handled anyway, so that a future keyed caller
meets a 409 rather than a 500.

The API registers one Ninja exception handler. The four view sites catch
`PlayerGameWriteFailed` themselves, add `messages.error`, and redirect through
`return_url(request, fallback=…)`, each with its own fallback.

They redirect rather than re-render, including the two form views. A failure
reaches them only after the catalog row was saved, thus re-rendering the form
would invite a resubmit that creates a second game. The row stands, the facts
were not recorded, and the toast says so.

An `UNCHANGED` outcome is a quiet success. The player asked for a state and the
state holds, thus the screen says what it says for a change. `CommandResult.reason`
reaches the log and no screen, as #906 requires: a replayed no-op has no reason
to give.

## What an archived game accepts

#675 left this issue the question of whether an archived game accepts a status.
It does. The commands do not consult `archived_at`, an archived row keeps every
fact, and a restore returns the game the library archived.

The question is inert here for a second reason: nothing archives a game yet, and
no list hides one. #678 owns both.

## Two legacy writes this does not switch

**`Purchase.infinite`** is the legacy write behind
`PlayerGame.excluded_from_unfinished`. It stays where #674 put it, at the
Purchase cutover.

It does not fit this issue's strategy. Every other fact has one catalog column
per game to mirror onto. This one is per purchase, thus the translation is "any
infinite purchase excludes the game", it does not invert, and there is nowhere
to mirror back to. Moving it means moving its readers with it —
`stats_data.py:214` and `:224`, `filters.py:351`, `sorting.py:110`, the
`QuickFacet("infinite")`, the purchase list column and any saved preset carrying
the criterion — plus the per-game backfill #676 deliberately did not do, with
the preflight #674 asked for over games holding both an infinite and a finite
purchase. That is a vertical of its own and it belongs to the wave that owns the
column.

**Archive and restore** have no legacy write to switch. #675 named this issue as
their first caller and also gave #678 "what an archived game means to each
list". The action and its visible effect thus had different owners, and nothing
in the tracker scheduled the action. #678 takes both: the control, the lists
that hide an archived game, and the place a restore is issued from. An Archive
button shipped here would record an event and change nothing a player can see.

Four of the seven commands therefore have no caller when this issue closes, and
that is recorded rather than fixed.
`SetPlayerGameExcludedFromUnfinished` waits for the Purchase cutover, and
`ArchivePlayerGame` and `RestorePlayerGame` wait for #678.
`SetPlayerGameMastered` waits for a second mastery writer: the game form is the
only one, and it states two facts, thus the composite answers it.

## Verification

Per call site: the event lands with the payload expected, the projection holds
the new fact, the catalog column mirrors it, and `GameStatusChange` appears when
and only when it appears today.

- A repeated save appends nothing, leaves the head where it was, and reports the
  ordinary success.
- The composite emits one event, two events, or `Unchanged`, over the four
  combinations of stated facts.
- The reversible-key rule: the same fact stated twice under two keys appends two
  events, and one key twice appends one.
- An untracked game heals: the row is deleted, a status is stated, and the
  result is a `TrackGame` followed by the status event.
- `rebuild_projections` in `RebuildMode.CHECK` reports no drift after each flow,
  and #676's reconciler asserts the catalog equals the fold.
- A game of another library answers 404 through every one of the six sites.
- Each of the five failures renders as its row of the table states, including
  the API's 422 for an unknown status string.
- Creating a game as Played records no `GameStatusChange`, as today.
- e2e over the status dropdown, the add and edit forms, mark-as-played,
  mark-as-finished, and a refund of a two-game purchase.
- The full `make check` gate passes.

## Reversibility

No migration and no schema change, thus a revert is the commits.

One consequence is worth stating. After the revert the writes return to the
catalog and the projection stops receiving them, and #676's backfill will not
catch up: its idempotency keys are one per game per fact, thus a second run
appends nothing for a game it already backfilled. The projection would lag by
whatever was written in the interval, and #676's reconciler reports the gap
rather than repairing it. Repair is a re-backfill under new keys, which is work
a revert would have to take on.

## Out of scope

- Every read. Lists, the detail page, filters, saved presets, statistics, the
  API shape and the TypeScript contracts stay on the catalog columns until #678.
- `PlayerGameStatus.SHELVED`. The dropdown offers `Game.Status.choices` while
  the catalog is the read source, thus the sixth member has no way in until #678.
- The legacy `GameStatusChange` storage and its editing UI, which is #771.
- Recording a rejected command, which is #740.
- A client-supplied idempotency token.
