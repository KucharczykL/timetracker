# Reading the status a refused command answered with

Issue [#958](https://github.com/KucharczykL/timetracker/issues/958).
[#905](https://github.com/KucharczykL/timetracker/issues/905) gives the boundary
that writes the status.

A refused command raises `CommandFailed`. The exception carries a sentence and a
status code. The boundary answers two codes. `CONFLICT_STATUS` is 409 for a page
that is behind. `DEFECT_STATUS` is 500 for a fault of ours.

## What a wrapper answers

Six request-shaped wrappers answer `WriteAnswer`. Two are in
`games/views/playergame_writes.py`. Four are in
`games/views/playthrough_writes.py`. `record_completed` in
`games/views/playthrough.py` passes the same type through.

`WriteAnswer` has one field. The field holds the refusal, or `None`. `__bool__`
answers true when the write landed. Thus a caller that only asks whether the
write landed reads the value as a condition.

A pair of `recorded` and `status_code` is refused. Such a pair admits a landed
write that carries a status, which means nothing. One field has two states, and
neither state is nonsense.

## Which view reads the status

A view narrows on `answer.refusal is not None`. `__bool__` narrows no field for
the type checker.

The refund in `games/views/purchase.py` answers `answer.refusal.status_code`.
Its answer replaces one row of a table, thus it can land nowhere. htmx swaps
nothing outside 2xx, and it reads 409 and 500 by one rule.

## A re-rendered form answers the status

Four modules render their form again after a refused command. Each answers the
refusal's status: `edit_game` in `games/views/game.py`, both session forms in
`games/views/session.py`, both run forms in `games/views/playthrough.py`, and
both historical playtime forms in `games/views/historical_playtime_entry.py`. A
status states what the request did, and the request did not save.

Each of those views renders one tail for two causes. The second cause is a form
that the person must correct, which answers 200. Thus each view holds the status
in a local variable.

A refused add keeps its 302. `add_game` redirects because a second render
invites a second game.

## Three wrappers raise

`remove_game_for_request`, `remove_run_for_request` and
`restore_game_for_request` raise. `confirm_and_apply` reads the status of the
first two. `restore_and_return` redirects, and a redirect states no status.

The restore reads the status for a different answer. Its refusal carries a
sentence and a "Try again" button, because the catalog mark is clear and a
second press ends the halfway. Only a conflict gets them. A defect states that
the problem was reported, and offers no button, because no retry of it can
succeed.

## The status stays on the exception

`games/writes/answers.py` makes one sentence and one status from each leaf. A
view that branched on the leaf would import the conflict types, and derive again
what `CONFLICT_ANSWERS` states one time.
