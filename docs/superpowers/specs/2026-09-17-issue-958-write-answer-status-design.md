# Reading the status a refused command answered with

Issue [#958](https://github.com/KucharczykL/timetracker/issues/958). The code is
in `games/writes/answers.py`, `games/views/playergame_writes.py`,
`games/views/playthrough_writes.py` and `games/views/purchase.py`.
[#905](https://github.com/KucharczykL/timetracker/issues/905) gives the boundary
that writes the status, and its "The status code has one reader" section names
this repair.

`CommandFailed` carries a sentence and a status code. A view that catches the
exception itself reads both: `games/views/historical_playtime_entry.py` renders
its form again at `failure.status_code`, and `confirm_and_apply` in
`games/views/removal.py` renders its confirmation the same way.

A view that takes its refusal through one of the six request-shaped write
wrappers reads neither. The wrapper catches the exception, raises a message from
it, and answers `bool`: the sentence reaches the person as a toast and the status
stops at that line.

One view needs the status anyway. The refund loop in `games/views/purchase.py`
states the number itself:

```python
return HttpResponse(status=409)
```

The number is right while every leaf answers 409. It is a copy of a value rather
than a reading of one, so a leaf that answers something else leaves the view
answering the old number, and no test says so. The boundary then carries a
status its own callers contradict.

## What a wrapper answers

`games/writes/answers.py` holds one more type.

```python
class WriteAnswer(NamedTuple):
    """What a request-shaped write left a view to answer with."""

    refusal: CommandFailed | None

    def __bool__(self) -> bool:
        """True when the write landed."""
        return self.refusal is None
```

It holds the refusal itself, not a copy of two of its fields. A pair of
`recorded: bool` and `status_code: int | None` admits `recorded=True,
status_code=409`, which means nothing, and it makes the status optional at every
call site although the branch that reads it is the branch where a refusal is
certain. One field has two states and neither is nonsense.

`__bool__` is what makes the change additive. Every caller that only asks whether
the write landed reads the value as it read the `bool` before it:

```python
if not record_facts_for_request(...):
    ...
if stated and played_is_offered(library, game):
    ...
```

Both sentences keep their meaning. A return type that a reader must invert — the
bare `CommandFailed | None` — reads as its opposite at each of those lines, and
no type checker reports it, because `not None` and `not failure` are both valid.
The one hazard that shape carries is the one `__bool__` removes.

`WriteAnswer` lives in `games/writes/answers.py` rather than in either view
module. Both view modules already import `CommandFailed` from it, one type for
one idea belongs beside the exception it holds, and a type in one of the two view
modules makes its sibling import across the pair.

## Why the refund keeps its wrapper

The repository states this refusal two ways. A view catches `CommandFailed`
itself in `games/views/session.py`, `games/views/historical_playtime_entry.py`
and `games/views/removal.py`. A view calls a `*_for_request` wrapper in
`games/views/game.py`, `games/views/playthrough.py`,
`games/views/playthrough_acts.py` and `games/views/purchase.py`.

The refund can take the first way: `record_facts` inside a `try`, and the status
read where it is caught. That costs no new type and no signature. It costs the
toast instead. The wrapper owns the one line that turns a refusal into a message,
and the refund states the write in a loop, once per game in the purchase, so the
view would either repeat that line or hold the only copy of it outside the two
write modules. It would also import a command's leaf into a view that states no
other one.

The wrappers exist to keep that line in one place. Giving them a return value
that carries the status keeps it there and answers the issue, where moving the
refund to the other way answers the issue by giving the line up.

## Where it applies

Six wrappers answer `WriteAnswer`.

| Module                               | Wrapper                                                                                       |
| ------------------------------------ | --------------------------------------------------------------------------------------------- |
| `games/views/playergame_writes.py`   | `track_game_for_request`, `record_facts_for_request`                                            |
| `games/views/playthrough_writes.py`  | `record_run_for_request`, `restate_run_for_request`, `start_run_for_request`, `complete_run_for_request` |

No caller of the four run wrappers reads a status today. They take the type
regardless, because the two modules state one idea in one docstring — "a view
that stays on its page toasts and answers False" — and two answers to one
question leave the next wrapper to copy whichever module its author opens first.
`__bool__` makes the four a signature change and nothing more.

Three wrappers raise instead of answering, and all three keep raising.

`remove_game_for_request` and `remove_run_for_request` stand behind a
confirmation, which hands the exception to `confirm_and_apply`. That function
reads the status already, and a `WriteAnswer` there would ask the confirmation to
re-raise what it was given.

`restore_game_for_request` raises a `CommandFailed` of its own, because the
catalog mark is cleared by then and the refusal's own sentence would say nothing
was. It carries the refusal's status forward, and its caller —
`restore_and_return` — reads the sentence and redirects. A redirect states no
status of the refusal's, so the value it carries has no reader on that route.
That is the answer a redirect gives, not a number copied from somewhere: the page
the person lands on is the answer, as it is for a refused add.

`games/views/playthrough.py` holds `record_completed`, which passes one wrapper's
answer through to two callers that read neither. It takes the new type with it.

## Which view reads the status

The refund loop, and no other.

```python
answer = record_facts_for_request(...)
if answer.refusal is not None:
    ...
    return HttpResponse(status=answer.refusal.status_code)
```

The narrowing is the read: there is no property that answers a status on a
landed write, because such a property can only raise on the call that is wrong.

A defect therefore reaches the browser as 500 rather than as 409. Nothing else
moves. `HTMXMessagesMiddleware` attaches the toast header to a queued message on
every answer that is neither a redirect nor an `HX-Redirect` or `HX-Refresh`
header, and htmx answers 409 and 500 by the same rule — its default response
handling swaps nothing for either, which is why the view answers a status rather
than a redirect in the first place. The two numbers differ in what the network
record says, and a defect of ours reading there as a conflict the person can
retry is the thing this issue removes.

The other HTML failure paths keep their answers. A refused add redirects with
302, and a refused session form renders again with 200. Each states where the
person lands, which no refusal knows. The refund answers a status because it can
land nowhere: its answer replaces one row of a table.

## The status stays on the exception

`CommandFailed` keeps `status_code`.

`games/writes/answers.py` exists to turn every leaf into one sentence and one
status. It answers two values: `CONFLICT_STATUS` for a page that is behind, and
`DEFECT_STATUS` for a fault of ours. A caller that branched on the leaf instead
would import the conflict types into the view layer and derive again what
`CONFLICT_ANSWERS` states once, which is the drift the module was built against.

The status is also the answer at the only place that reads it. A view answers
HTTP; `409` and `500` are its words, not a translation of them.

## What a test notices

`tests/test_playergame_view_cutover.py` holds
`test_a_partly_applied_refund_says_how_far_it_went`. It replaces the leaf
`record_facts`, not the wrapper, so the wrapper and the view both run. The test
takes the status as a parameter and states it twice, 409 and 500, and asserts the
view answers the one the leaf raised. A view that copies a number passes at 409
and fails at 500, which is the hole this issue names. Django logs a returned 500
on the `django.request` logger, so a test that reads records filters on the
`games` logger, as `tests/test_playthrough_view_cutover.py` already does.

One test states `WriteAnswer`'s truthiness in both of its states, because the
eight call sites that read the value read it that way and nothing else proves it.

Two test doubles answer a bare `False` today, in `tests/test_catalog_submit.py`
and `tests/test_playergame_view_cutover.py`. They pass unchanged, which is
`__bool__` working, and they take real `WriteAnswer` values regardless: a double
of a typed function that answers another type describes the function wrongly to
its next reader.
