# Inconsistent-row answer implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A command that refuses because a row is wrong answers 500, logs an ERROR with a traceback, and says one sentence, instead of a silent 409.

**Architecture:** One `CommandRejected` subclass, `RowInconsistent`, declared beside its parent so the boundary-classification test forces its placement. `answered()` gets a clause ahead of `except CommandRejected` that logs and answers `DEFECT_STATUS`. Four raise sites switch type; their by-hand logs and sentences go. `Refusal` refuses the type.

**Tech Stack:** Python 3.14, Django, pytest (`make test ARGS=…`), ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-09-16-issue-1057-inconsistent-row-answer-design.md`

## Global Constraints

- Run everything through `make`; never bare `pytest`/`uv run`.
- Gate before push: full `make check`, including `e2e/`. `make check-fast` while iterating.
- Complete-word identifiers; no issue numbers in comments; `make vale` refuses `fold`, `seam`, `heal`, `tombstone`, `archive`, `delete`.
- Step 0 already done: branch rebased on `origin/main` (`f198ec43`).
- Commit messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

---

### Task 1: The type and the boundary

**Files:**
- Modify: `games/events/dispatch.py:177-190` (after `CommandRejected`)
- Modify: `games/writes/answers.py:21,68-76,99-102,155-162`
- Test: `tests/test_command_answers.py`

**Interfaces:**
- Produces: `games.events.dispatch.RowInconsistent(message: str)` — subclass of `CommandRejected`, no `sentence` keyword, `sentence` attribute always `None`.
- Produces: `games.writes.answers.REFUSED_BY_AN_INCONSISTENT_ROW: str` with one `{subject}` placeholder: `"This {subject}'s record could not be read, so nothing was changed. The problem has been reported."`
- Produces: `answered()` answers `RowInconsistent` with `CommandFailed(sentence, DEFECT_STATUS)` and `logger.exception("[answers]: a command refused an inconsistent %s.", subject)`.

- [ ] **Step 1: Failing tests.** Add to `tests/test_command_answers.py`, importing `RowInconsistent` from `games.events.dispatch` and `REFUSED_BY_AN_INCONSISTENT_ROW` from `games.writes.answers`. Reuse `_FOR_A_DEVELOPER` as the argument.
  - `test_an_inconsistent_row_is_a_defect`: raise `RowInconsistent(_FOR_A_DEVELOPER)` under `answered("session")`; assert `status_code == DEFECT_STATUS` and `message == REFUSED_BY_AN_INCONSISTENT_ROW.format(subject="session")`.
  - `test_an_inconsistent_row_says_nothing_of_the_program`: `"0192f3d4" not in message` and `"#676" not in message`.
  - `test_an_inconsistent_row_is_logged_with_its_cause` (`capture_games_logger`): raise it `from CommandRejected("the scope miss")`; last record `levelname == "ERROR"`, `exc_info is not None`, `"#676" in caplog.text`, `"the scope miss" in caplog.text`.
  - `test_an_inconsistent_row_states_no_sentence`: `pytest.raises(TypeError)` on `RowInconsistent("x", sentence="y")`; and `RowInconsistent("x").sentence is None`.
  - Extend `test_every_sentence_interpolates_and_leaves_no_brace` with the new constant.
- [ ] **Step 2: Run** `make test ARGS="tests/test_command_answers.py -x"`. Expect ImportError on `RowInconsistent`.
- [ ] **Step 3: Type.** In `games/events/dispatch.py` after `CommandRejected`:

```python
class RowInconsistent(CommandRejected):
    """A row the command read cannot be read as the schema promises.

    Answered as a defect: the person can state nothing different, so
    the boundary owns the sentence and the argument is for the log.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
```

- [ ] **Step 4: Boundary.** In `games/writes/answers.py`: import `RowInconsistent`; add the constant beside `REFUSED_BY_DATABASE` with a `#:` note that it is worded about the reading because on the tzdata branch the row is right; add it to `ANSWERED_DIRECTLY`; insert the clause **before** `except CommandRejected` (order is load-bearing, say so in a `#:` comment):

```python
    except RowInconsistent as error:
        #: Ahead of its parent, which would answer it as a rule.
        #: The traceback carries the argument and every cause.
        logger.exception("[answers]: a command refused an inconsistent %s.", subject)
        raise CommandFailed(
            REFUSED_BY_AN_INCONSISTENT_ROW.format(subject=subject), DEFECT_STATUS
        ) from error
```

- [ ] **Step 5: Run** `make test ARGS="tests/test_command_answers.py"`. All pass, including `test_every_boundary_exception_is_classified` (remove the type from `ANSWERED_DIRECTLY` once to see it fail; put it back).
- [ ] **Step 6: Commit** `feat: answer an inconsistent row as a defect`.

---

### Task 2: The scope guard

**Files:**
- Modify: `games/commands/scope.py:11-26`
- Test: `tests/test_command_scope.py`

**Interfaces:**
- Consumes: `RowInconsistent` from Task 1.
- Produces: `Refusal.__post_init__` raising `TypeError` when `issubclass(self.raises, RowInconsistent)`.

- [ ] **Step 1: Failing test.** `test_a_scope_miss_is_never_a_defect`: `pytest.raises(TypeError, match="RowInconsistent")` around `refusal(raises=RowInconsistent)`. Also a subclass of `RowInconsistent` declared in the test is refused.
- [ ] **Step 2: Run** `make test ARGS="tests/test_command_scope.py -x"`; fails because construction succeeds.
- [ ] **Step 3: Guard.** `Refusal` is `frozen=True`; `__post_init__` may raise:

```python
    def __post_init__(self) -> None:
        #: A miss is a rule with a sentence. RowInconsistent takes none,
        #: and mypy reads type[CommandRejected] without its constructor.
        if issubclass(self.raises, RowInconsistent):
            raise TypeError(
                f"Refusal.raises cannot be {self.raises.__name__}: a scope miss "
                "is not an inconsistent row, and the type states no sentence."
            )
```

- [ ] **Step 4: Run** the file; pass. **Step 5: Commit** `feat: a scope miss is never an inconsistent row`.

---

### Task 3: The four sites

**Files:**
- Modify: `games/commands/playersession.py:3,21,49,53-57,205-225,288-308`
- Modify: `games/commands/playthrough.py:3,14,37,39-43,576-597`
- Test: `tests/test_playersession_command.py:14-16,504-523,780-812,2025-2040`
- Test: `tests/test_playthrough_command.py:19-21,2080-2090,2274-2277`

**Interfaces:**
- Consumes: `RowInconsistent` from Task 1.
- Produces: no `INCONSISTENT_SESSION`, no `INCONSISTENT_PLAYTHROUGH`, no `logger` in either commands module.

- [ ] **Step 1: Rewrite the site tests first.**
  - `refused_end` (`test_playersession_command.py:504`): add keyword `raising: type[CommandRejected] = CommandRejected`; `pytest.raises(raising)`; assert sentence only when `saying is not None` (default stays required for rule tests; pass `saying=None, raising=RowInconsistent` for defect tests). Update the tzdata test (~line 791) to `raising=RowInconsistent, saying=None` and assert `"tzdata" in str(refusal)`.
  - `test_a_timed_row_with_no_start_is_refused` (~810): `pytest.raises(RowInconsistent)`; assert `"timed-columns constraint" in str(refusal.value)`.
  - `test_a_session_naming_a_foreign_run_is_refused_by_name` (~2025): drop `capture_games_logger` and the record assertions; `pytest.raises(RowInconsistent)`; assert `str(session.pk)`, `str(session.library_id)` and `str(session.playthrough_id)` are in `str(refusal.value)`; assert `refusal.value.__cause__ is not None`.
  - `test_playthrough_command.py` ~2083: `pytest.raises(RowInconsistent)`; drop the caplog block; assert `str(run.pk)`, `str(stranger.library.pk)`, `str(run.library_id)`, `assignment_model.__name__` and `"playthrough"` (the field name) in `str(refusal.value)`; keep `run.removed_at is None`.
  - `test_playthrough_command.py` ~2276: same shape; drop the caplog line.
  - Remove `INCONSISTENT_*` from both import blocks; import `RowInconsistent` from `games.events.dispatch`.
- [ ] **Step 2: Run** `make test ARGS="tests/test_playersession_command.py tests/test_playthrough_command.py -x"`; fails on the type.
- [ ] **Step 3: Sites.** In both modules: import `RowInconsistent`; remove `import logging` and `logger = …` (no other use in either file — grep to confirm); remove the `INCONSISTENT_*` constants and their `#:` notes.
  - `_session_run`: replace the `logger.error` + `raise CommandRejected(…, sentence=…)` with one `raise RowInconsistent(f"Session {session.pk} of library {session.library_id} names playthrough {session.playthrough_id}, which this library does not hold; the ownership audit reports it, and no command states a fact about it.") from refusal`. Trim the docstring line about "the log names the rest" to say the argument names the rest.
  - `_timed_start`, no-start branch: `RowInconsistent(f"Timed session {session.pk} of library {session.library_id} states no start or no day zone, which the timed-columns constraint forbids.")`. Keep the `#:` note; drop its last clause about "a sentence".
  - `_timed_start`, tzdata branch: `RowInconsistent(f"Session {session.pk} of library {session.library_id} counts its day in {day_zone!r}, which this installation's tzdata can no longer read.")`.
  - `_refuse_a_foreign_referrer`: one `raise RowInconsistent(...)` whose argument names `foreign.referrer.model.__name__`, `foreign.referrer.field_name`, the joined `foreign.library_ids`, `run.pk` and `run.library_id`, then "the ownership audit reports it; removing the run would strand it." Docstring: "Refuse a foreign row naming the run."
- [ ] **Step 4: Run** the two files; pass. Then `make lint` (unused `logging` import would fail here).
- [ ] **Step 5: Commit** `feat: four broken-row refusals are inconsistent rows`.

---

### Task 4: Consumers, docs, gate

**Files:**
- Modify: `games/views/removal.py:76-80` (comment only)
- Modify: `CLAUDE.md:200-204,954-975`
- Modify: spec (if anything drifted)

- [ ] **Step 1: Comment.** Reword the `#:` in `confirm_and_apply` to: "State moves: another tab may have won. The status is the refusal's own — 409 for a stale page, 500 for a row or a constraint that refused — because the answers disagree about what to do next."
- [ ] **Step 2: CLAUDE.md.** Playthrough bullet (~line 200): replace "neutral `INCONSISTENT_PLAYTHROUGH` sentence and `games` logger error naming both libraries (#1062)" with "`RowInconsistent`, which the boundary answers as a defect (#1057)"; same for `INCONSISTENT_SESSION` in the next sentence. "A refused command becomes an answer" bullet: add the fourth way — `RowInconsistent` becomes `CommandFailed` at `DEFECT_STATUS` with `logger.exception`, sentence `REFUSED_BY_AN_INCONSISTENT_ROW`. "A rejection carries two sentences" bullet: add one sentence — a raise site whose cause is the row, not the statement, raises `RowInconsistent(message)` and writes no sentence; `Refusal` refuses the type.
- [ ] **Step 3: Gate.** `make vale`, then full `make check` to a log file; read the exit code, not grep:

```bash
make check > /tmp/check-1057.log 2>&1; echo EXIT=$?
```

- [ ] **Step 4: Commit** `docs: the inconsistent-row answer`. Then open the PR with the spec and plan linked; body ends with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.

---

## Gotchas

- Clause order in `answered()`: a `RowInconsistent` clause after `except CommandRejected` is dead code and every test in Task 1 fails at 409.
- The classification walk reads `games/events/` only. The type must stay in `dispatch.py`.
- `_session_run` wraps `library_playthrough`'s `CommandRejected`; keep `from refusal`, the log test reads the cause.
- `capture_games_logger` attaches at WARNING; `logger.exception` records at ERROR with `exc_info` — assert `records[-1]`, not `records[0]`, in case a warning precedes.
- `make vale` runs on code comments: no `fold`, `seam`, `heal` in the new `#:` notes.
- Removing `logging` from the two command modules: ruff F401 fails `make lint` if `import logging` stays.

## Follow-up issues to file

None. #958 and #908 already track the two adjacent gaps the spec names.
