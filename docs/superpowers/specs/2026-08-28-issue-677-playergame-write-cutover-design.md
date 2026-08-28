# The PlayerGame write path

Code states a PlayerGame fact as a command. Code does not write `Game.status`
or `Game.mastered` directly. The two catalog columns are a mirror of the
projection. Issue #678 removes the mirror when the reads move.

The code is `games/writes/playergame.py`, with a request-shaped half in
`games/views/playergame_writes.py`.

## The two functions

`track_game(actor, game, *, correlation_id)` dispatches `TrackGame`.

`record_facts(actor, game, *, status=None, mastered=None, correlation_id)`
states one fact or two. `None` means that this act does not state that fact.
Neither fact raises `ValueError`. Both take an actor and not a request,
because `authorize()` compares `library.user_id` to the actor.

`record_facts` translates the status vocabulary, dispatches, heals an untracked
game, and then mirrors.

## The composite command

`RecordPlayerGameFacts` states a status, a mastery, or both, as one act. The
game form states both facts at each save, thus the two travel as one command.

`build()` reads the projection row one time and returns an event for each stated
fact that is different. If none is different, it returns `Unchanged`, thus a
repeated save records nothing.

`_tracked_game()` raises `PlayerGameNotTracked` for a game that the library does
not track. `record_facts` catches that class, tracks the game, and dispatches
one more time. The heal makes one attempt.

## The mirror

The mirror reads the projection row back and writes the mapped values onto the
catalog. A command can decline what a caller asks, thus only the fold is correct.

The mirror is not a projector. `only_shadow_writes()` refuses each statement
that writes outside a shadow table, thus a projector cannot write `games_game`.

`Game.save(update_fields=[...])` does the write. Because of this, the `pre_save`
audit signal operates and `GameStatusChange` history does not change.

`games/playergame_status.py` holds the two directions of the vocabulary map.
`PlayerGameStatus.SHELVED` has no member of `Game.Status`, thus
`legacy_status_for()` raises for it.

## Transactions

`run_in_transaction` opens the transaction that it retries and refuses to nest.
A view that dispatches thus has no `@transaction.atomic` and calls no helper
that has one. The `games.E008` check refuses `ATOMIC_REQUESTS`. A test that
sends a POST through such a view needs `@pytest.mark.django_db(transaction=True)`.

## Keys and correlation ids

Each dispatch takes a new UUIDv7 key, which deduplicates nothing: a resubmitted
POST carries a new key. The state comparison in `build()` is the defence.
Issue #740 owns a client-supplied token.

Each view mints one correlation id and gives it to each dispatch that it makes.
A refund of a three-game purchase is thus one act of three events.

## Failures

The write path raises `Http404` for `CommandNotPermitted`, and
`PlayerGameWriteFailed` with a 409 for each other failure. A view catches it,
shows a toast, and redirects. The API registers one Ninja handler.

`refund_purchase` answers a table row and an out-of-band modal close, thus a
failure answers 409 with no body. htmx swaps nothing outside 2xx, so the row
keeps what it shows and the toast rides the `HX-Trigger` header.

An `UNCHANGED` outcome is a quiet success.

## Limits

Each read reads the catalog until #678, and the status dropdown offers
`Game.Status.choices`. `PlayerGameStatus.SHELVED` thus has no way in.

Three commands have no caller: `SetPlayerGameExcludedFromUnfinished` waits for
the Purchase cutover, and the two archive commands wait for #678.
