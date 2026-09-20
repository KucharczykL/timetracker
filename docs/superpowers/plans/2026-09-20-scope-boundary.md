# Scope boundary implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A row the library does not hold answers 404 from the command layer,
stated once, so the route pre-checks that read the state ahead of a stated
idempotency key are no longer needed.

**Architecture:** A new `RowNotHeld`, sibling of `CommandRejected` and
`RowUnreadable`, which `answered()` turns into `Http404`. `Refusal` defaults to
it, so every `library_row` caller inherits the rule. The four route pre-checks
in `games/api.py` go away, which puts both resolves inside `build`, behind
`idempotent_append`'s key check.

**Tech Stack:** Django 6, Django Ninja, Python 3.14, PostgreSQL 18, pytest-xdist.

**Spec:** [Where a scope miss is answered](../specs/2026-09-20-issue-1167-1174-scope-boundary-design.md)

**Closes:** #1167 and #1174. Leaves #1180 and #1181, which the spec names.

## Global Constraints

- Every command is run through `make`. Never a bare `uv run` or `pytest`.
- Iterate with `make check-fast`; the gate is
  `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make check`, run
  once at the end, e2e included.
- A test that POSTs through a view which dispatches needs
  `@pytest.mark.django_db(transaction=True)`.
- `make vale` reads code comments as well as docs. `delete` is a refused word;
  write `remove`, `take out` or `goes away`.
- Comments explain intent, never an issue or PR number.
- Unabbreviated identifiers.
- The branch is `claude/issue-1167-1174-scope-boundary`, cut from `origin/main`.
  PR #1176 touches the same two route bodies; rebase before the gate if it has
  merged.

---

## File structure

| File | Change |
|---|---|
| `games/events/dispatch.py` | `RowNotHeld`, beside `RowUnreadable` |
| `games/writes/answers.py` | its clause in `answered()`, and `ANSWERED_DIRECTLY` |
| `games/commands/scope.py` | `Refusal`'s default, `__post_init__`, `raised()`; `library_device_row`'s sentence goes |
| `games/commands/playthrough.py` | `PlaythroughNotHeld` reparented; its sentence goes |
| `games/commands/playersession.py` | `SessionNotHeld` reparented; its sentence goes |
| `games/commands/historical_playtime.py` | `library_record`'s sentence goes |
| `games/commands/playergame.py` | `tracked_game` states `raises=` and keeps its sentence, with a comment |
| `games/views/session_reclassification.py` | `_convert_each` takes `Http404` |
| `games/api.py` | four pre-checks and their two helpers go away |
| `games/writes/historical_playtime.py` | the blank-key mint |
| `CLAUDE.md` | the three session API bullets, and the refusal-class rule |
| `docs/superpowers/specs/2026-09-20-issue-1074-session-api-record-design.md` | two sections it states |

---

### Task 1: `RowNotHeld` and its answer

No behaviour changes: nothing raises the class yet.

**Files:**
- Modify: `games/events/dispatch.py`
- Modify: `games/writes/answers.py`
- Test: `tests/test_command_answers.py`

**Interfaces:**
- Produces: `RowNotHeld(Exception)` in `games.events.dispatch`, one positional
  message, no `sentence` keyword. `answered()` answers it `Http404`.

- [ ] **Step 1: Write the failing tests**

Three, in `tests/test_command_answers.py`:

1. `test_a_row_not_held_is_no_rejection` — `assert not issubclass(RowNotHeld,
   CommandRejected)`, the twin of `test_an_unreadable_row_is_no_rejection` at
   `:176`.
2. `answered("session")` around a raised `RowNotHeld` answers `Http404`, not
   `CommandFailed`.
3. It logs one WARNING naming the row, through `caplog`.

`test_every_boundary_exception_is_classified` at `:300` fails on its own until
Step 3 lists the class; that is the fourth test and needs no writing.

- [ ] **Step 2: Run them and watch them fail**

`make test-fast ARGS="tests/test_command_answers.py"`

- [ ] **Step 3: Write it**

`RowNotHeld` under `RowUnreadable` in `games/events/dispatch.py`. Its docstring
says what the two endings are and why this one is a sibling, not a subclass.

In `games/writes/answers.py`: import it, add it to `ANSWERED_DIRECTLY`, and put
its clause **before** the `CommandRejected` clause — order does not matter for a
sibling, but the file reads top-down from absent to refused. One
`logger.warning` with the message, no `exc_info`, then
`raise Http404(f"No such {subject}.") from error`.

- [ ] **Step 4: Green**

`make test-fast ARGS="tests/test_command_answers.py"`

- [ ] **Step 5: Commit** — `feat: a row the library does not hold is its own refusal`

---

### Task 2: the rule, and everything that moves with it

This is the behaviour change. It lands whole, because a `Refusal` that states a
sentence is illegal the moment the default changes, and the batch conversion's
gap opens the moment a scope miss becomes `Http404`.

**Files:**
- Modify: `games/commands/scope.py`, `playthrough.py`, `playersession.py`,
  `historical_playtime.py`, `playergame.py`
- Modify: `games/views/session_reclassification.py`
- Test: `tests/test_command_scope.py`, `tests/test_playersession_command.py`,
  `tests/test_playthrough_command.py`,
  `tests/test_historical_playtime_command.py`,
  `tests/test_session_reclassification_views.py`

**Interfaces:**
- Consumes: `RowNotHeld` from Task 1.
- Produces: `Refusal(message)` answers 404; `Refusal(message, sentence=...,
  raises=SomeCommandRejected)` answers 409. `raised()` returns
  `RowNotHeld | CommandRejected`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_command_scope.py`:

- a `Refusal` stating a sentence with no `raises` is refused at construction;
- a `Refusal` stating `raises=CommandRejected` with no sentence is refused;
- `library_row` answers `RowNotHeld` for a foreign row and for an absent one
  alike, and neither carries a sentence attribute.

The module's `refusal()` helper at `:25-31` states a sentence today, so it must
lose it; `test_another_library_row_and_a_missing_row_refuse_alike` at `:44`
reads `.sentence` off both and must compare `str(...)` alone.

In `tests/test_session_reclassification_views.py`: the batch conversion meets an
`Http404` from one row and answers the same stop and report a defect gets.
Raise it with `monkeypatch` on the write the loop calls.

- [ ] **Step 2: Run them and watch them fail**

`make test-fast ARGS="tests/test_command_scope.py"`

- [ ] **Step 3: `Refusal`**

```python
@dataclass(frozen=True, slots=True)
class Refusal:
    """What a caller says when nothing resolves."""

    message: str
    #: Stated by a caller that answers a refusal, not an absence.
    sentence: str | None = None
    raises: type[RowNotHeld] | type[CommandRejected] = RowNotHeld

    def __post_init__(self) -> None:
        absent = issubclass(self.raises, RowNotHeld)
        if absent and self.sentence is not None:
            raise TypeError(...)
        if not absent and self.sentence is None:
            raise TypeError(...)

    def raised(self) -> RowNotHeld | CommandRejected:
        if issubclass(self.raises, RowNotHeld):
            return self.raises(self.message)
        return self.raises(self.message, sentence=self.sentence)
```

Each `TypeError` says which pair is wrong and what to state instead.
`RowUnreadable` stays outside both annotations, so the rule CLAUDE.md states —
`Refusal.raises` refuses it at mypy — keeps holding.

- [ ] **Step 4: the five resolvers**

Four lose their sentence and state nothing else:
`library_device_row` (`scope.py:60`), `library_record`
(`historical_playtime.py:203`), `library_playthrough` (`playthrough.py:196`,
keeps `raises=PlaythroughNotHeld`), `library_session` (`playersession.py:203`,
keeps `raises=SessionNotHeld`).

`tracked_game` (`playergame.py:52`) keeps its sentence and states
`raises=PlayerGameNotTracked`. A comment says why it is the exception: the
write path takes that class, tracks the game and states the fact again, so a
404 would end a request the program repairs.

Reparent `PlaythroughNotHeld` (`playthrough.py:184`) and `SessionNotHeld`
(`playersession.py:193`) onto `RowNotHeld`. Their two catchers keep working
untouched: `_session_run` (`playersession.py:215`) and
`_refuse_beside_a_live_session` (`historical_playtime.py:357`).

- [ ] **Step 5: the batch conversion**

`_convert_each` (`session_reclassification.py:322`) takes `Http404` beside
`CommandFailed`. Its `#: One type; the status tells defect apart.` comment
becomes true again by naming the second type. The rows come from
`library_sessions` moments earlier, so the case is unreachable by construction;
the handler says what happens if it stops being so.

- [ ] **Step 6: the command tests**

Each of these asserts a sentence that no longer exists, or catches a class that
no longer matches. Change each to assert the class:

- `tests/test_playersession_command.py` — the `refused_end` helper at `:504`
  asserts `isinstance(refusal.value, CommandRejected)` for every case that is
  not `RowUnreadable`; it needs a third branch. Call sites: `:696`, `:771`,
  `:1125`, `:1139`, `:1406`, `:1452`, `:1466`, `:1614`, `:1626`, `:1691`,
  `:1826`, `:1841`.
- `tests/test_playthrough_command.py` — `:659`, `:675`, `:1000`, `:1403`,
  `:1678`.
- `tests/test_historical_playtime_command.py` — `:237`, `:284`.

- [ ] **Step 7: Green**

`make check-fast`

- [ ] **Step 8: Commit** — `refactor: a scope miss is absent, not refused`

---

### Task 3: the routes

**Files:**
- Modify: `games/api.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write the failing tests**

One new, which is #1174's reproduction: POST a session naming a device under
`Idempotency-Key: k-2`; remove the device; POST the identical body under the
same key. Answers 201 and the first row, and
`PlayerSession.objects.filter(playthrough=run).count() == 1`.

Two flip:
- `test_session_patch_409s_a_run_another_library_holds` (`:1137`) answers 404.
  Rename it, and rewrite the docstring, which names the asymmetry being taken
  away.
- `test_post_session_404s_a_removed_device` (`:1000`) answers 409 and the
  sentence. Its docstring names `for_library`'s `alive()`, which goes away.

Five stay green and must be run as proof the rule held: the two
`test_post_session_404s_*` for a foreign and an unknown run (`:732`, `:749`),
`test_post_session_404s_a_device_another_library_holds` (`:765`),
`test_post_session_refuses_a_run_under_a_removed_game` (`:1025`), and
`test_post_session_404s_a_repeat_of_a_session_since_removed`.

- [ ] **Step 2: Run them and watch the three fail**

`make test-fast ARGS="tests/test_api.py -k session"`

- [ ] **Step 3: Take the pre-checks out**

`_library_run_or_404` (`api.py:699`) and `_library_device_or_404` (`api.py:688`)
go away, with their four call sites: `api.py:718` (`PATCH /{id}/device`),
`:872` and `:873` (POST), `:905-906` (PATCH). The PATCH's `if "device_id" in
stated:` guard goes with its body.

Nothing else in the file uses either helper; `owned_or_404` stays, and every
`Game`, run and session the routes read by path keeps it.

- [ ] **Step 4: Green**

`make test-fast ARGS="tests/test_api.py"`

- [ ] **Step 5: Commit** — `fix: the session routes resolve under the lock`

---

### Task 4: the blank-key twin

**Files:**
- Modify: `games/writes/historical_playtime.py`
- Create: `tests/test_historical_playtime_writes.py`, the twin of
  `tests/test_session_writes.py`, which the record write path has none of

- [ ] **Step 1: Write the failing test**

`record_historical_playtime(..., idempotency_key="")` raises `ValueError`,
because `dispatch` calls `validate_idempotency_key`
(`games/events/dispatch.py:236`) and a blank key is refused there. Today `or`
replaces the blank with a fresh key and nothing is raised.

The session twin has no such test either: its route refuses a blank key at 422
before the write path sees one, so the guard is unproven. Write the pair.

- [ ] **Step 2: Fail, then write it**

`_dispatch` at `:37` takes the session's shape from
`games/writes/playersession.py:62-68`, comment included:

```python
        idempotency_key=(
            str(uuid.uuid7()) if idempotency_key is None else idempotency_key
        ),
```

- [ ] **Step 3: Commit** — `fix: a blank key is no reason to mint one`

---

### Task 5: the documents

**Files:**
- Modify: `CLAUDE.md`
- Modify: `docs/superpowers/specs/2026-09-20-issue-1074-session-api-record-design.md`

- [ ] **Step 1: `CLAUDE.md`**

Three places state the old rule:

1. the `PATCH /api/session/{id}` bullet — "Device outside library answers 404"
   stays true; add that a run outside the library does too;
2. the `POST /api/session/` bullet — "A run or device the library does not hold
   answers 404" stays true, but "measured at the route" no longer describes the
   run and device, only the header;
3. the refusal-class rule under **Conventions** — it names `CommandRejected`,
   `RowUnreadable` and `CommandNotPermitted`. `RowNotHeld` belongs beside them,
   with the one line that tells them apart.

- [ ] **Step 2: the #1074 spec**

Two sections state what this replaces. "The two identifiers" describes the
pre-checks; "What stays" says the PATCH answers 409 and that one rule for the
two routes is a change to `library_playthrough` — which is this change. Rewrite
both to point at the new spec, timeless, in the house voice.

- [ ] **Step 3: `make vale`** — 889 files, no findings.

- [ ] **Step 4: Commit** — `docs: the API answers one rule for a row it does not hold`

---

## The gate

- [ ] `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make check`,
      green, e2e included. Read the exit code from a log; never grep the output.
- [ ] Open the PR, closing #1167 and #1174, naming #1180 and #1181 as what it
      leaves. Merge only on the word.

## Gotchas

- **`_convert_each` is the one silent break.** `Http404` is not `CommandFailed`,
  and nothing would have failed a test: the loop's rows cannot miss today. Task
  2 Step 5 exists because the invariant its comment states would otherwise
  become false.
- **`refused_end` hides twelve call sites.** It asserts
  `isinstance(refusal.value, CommandRejected)` inside the helper, so a
  reparented class fails twelve tests with one message that names none of them.
- **`test_command_answers.py`'s walk does not reach `games/commands/`.** It
  walks the boundary modules, so `PlaythroughNotHeld` and `SessionNotHeld` are
  unguarded either way. Only `RowNotHeld` itself is covered, because it lives in
  `games/events/dispatch.py`.
- **A route's path row is not this rule.** `_writable_runs` narrows
  `PATCH`/`DELETE /api/playthrough/{id}` to ordinary runs under a live game, so
  those routes answer 404 where a command would state a sentence. That is the
  route's own read scope and it stays. Do not widen it.
- **`Refusal.raised()` cannot pass `sentence=` to `RowNotHeld`.** It takes the
  message alone. Without the branch this is a `TypeError` at runtime, and mypy
  names it first.
