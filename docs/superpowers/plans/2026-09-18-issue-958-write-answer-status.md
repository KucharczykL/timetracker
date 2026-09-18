# Reading a refused command's status — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the request-shaped write wrappers a return type that carries the
refusal, so a view answers the status the boundary stated instead of a copied
literal.

**Architecture:** One `NamedTuple` with a single field and a custom `__bool__`
replaces `bool` on six wrappers. Because `__bool__` answers "the write landed",
every existing truthiness call site keeps its meaning and is left alone. Three
views then read `answer.refusal.status_code` where they copied a number or
answered 200.

**Tech Stack:** Django 6, Python 3.14, pytest, mypy, ruff.

**Spec:** `docs/superpowers/specs/2026-09-17-issue-958-write-answer-status-design.md`

**Issue:** <https://github.com/KucharczykL/timetracker/issues/958>

## Global Constraints

- Drive everything through `make`. No raw `uv run` / `pytest` / `pnpm`, and no
  `direnv exec .` wrap.
- Wrap every pytest target in the shared lock:
  `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make test ARGS="…"`.
- `make check` (full, including `e2e/`) is the gate before push. `make check-fast`
  is for iterating only.
- Never `instance.delete()`, never write a `GeneratedField`, never bare
  `git stash`.
- Comments explain obscure intent only; no issue or PR references in them.
- Prose in docs and comments passes `make vale`; see `docs/vocabulary.md`.
- Unabbreviated identifiers.

## The one gotcha that governs every task

`WriteAnswer.__bool__` does **not** narrow `answer.refusal` for mypy. A custom
`__bool__` tells the type checker nothing about a field.

```python
if answer:  # fine for a caller that only asks whether it landed
    ...
if not answer.refusal:  # wrong: reads as "no refusal", but does not narrow
    ...
if answer.refusal is None:  # the only form that narrows
    return redirect(...)
status = answer.refusal.status_code  # narrowed here
```

Every place that reaches for `status_code` narrows with `is None` / `is not None`
first.

## File structure

| File | Responsibility after this change |
| --- | --- |
| `games/writes/answers.py` | Adds `WriteAnswer` beside `CommandFailed`. |
| `games/views/playergame_writes.py` | Two wrappers answer `WriteAnswer`. |
| `games/views/playthrough_writes.py` | Four wrappers answer `WriteAnswer`. |
| `games/views/playthrough.py` | `record_completed` passes the new type through. |
| `games/views/purchase.py` | The refund reads the status. |
| `games/views/game.py` | `edit_game` re-renders at the refusal's status. |
| `games/views/session.py` | Both session forms re-render at the refusal's status. |
| `tests/test_command_answers.py` | States `WriteAnswer`'s truthiness. |
| `tests/test_playergame_view_cutover.py` | Three tests take the status as a parameter. |
| `tests/test_refused_form_status.py` | New: the session forms' status. |
| `tests/test_catalog_submit.py` | Its double answers a real `WriteAnswer`. |

Untouched on purpose: `remove_game_for_request`, `restore_game_for_request` and
`remove_run_for_request` keep raising; `add_game` keeps its 302;
`games/views/removal.py` and `games/views/historical_playtime_entry.py` already
read the status.

---

### Task 0: Rebase

- [ ] **Step 1: Take the branch onto current main**

```bash
git fetch origin && git rebase origin/main
```

Expected: clean. Resolve anything in
`docs/superpowers/specs/2026-09-17-issue-958-write-answer-status-design.md` in
favour of this branch's version.

---

### Task 1: `WriteAnswer`

**Files:**
- Modify: `games/writes/answers.py` (after the `CommandFailed` class)
- Test: `tests/test_command_answers.py`

**Interfaces:**
- Consumes: `CommandFailed` from the same module.
- Produces: `WriteAnswer(refusal: CommandFailed | None)`, truthy when `refusal`
  is `None`. Every later task imports it from `games.writes.answers`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_command_answers.py`:

```python
def test_a_landed_write_is_truthy_and_a_refused_one_is_not():
    landed = WriteAnswer(None)
    refused = WriteAnswer(CommandFailed("Nothing was recorded.", CONFLICT_STATUS))

    assert landed
    assert not refused
    assert landed.refusal is None
    assert refused.refusal is not None
    assert refused.refusal.status_code == CONFLICT_STATUS
```

Add `WriteAnswer` (and `CONFLICT_STATUS` if absent) to that file's existing
import from `games.writes.answers`.

- [ ] **Step 2: Run it and watch it fail**

```bash
flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make test ARGS="tests/test_command_answers.py -k truthy -x"
```

Expected: `ImportError: cannot import name 'WriteAnswer'`.

- [ ] **Step 3: Add the type**

In `games/writes/answers.py`, directly after the `CommandFailed` class body:

```python
class WriteAnswer(NamedTuple):
    """What a request-shaped write left a view to answer with."""

    refusal: CommandFailed | None

    def __bool__(self) -> bool:
        """True when the write landed."""
        return self.refusal is None
```

`NamedTuple` is already imported at the top of that module.

- [ ] **Step 4: Run it and watch it pass**

```bash
flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make test ARGS="tests/test_command_answers.py -x"
```

Expected: PASS, and the module's two completeness guards still pass —
`WriteAnswer` is not an `Exception`, so neither guard sees it.

- [ ] **Step 5: Commit**

```bash
git add games/writes/answers.py tests/test_command_answers.py
git commit -m "feat: carry a refusal out of a request-shaped write"
```

---

### Task 2: The two PlayerGame wrappers answer it

**Files:**
- Modify: `games/views/playergame_writes.py` (module docstring,
  `track_game_for_request`, `record_facts_for_request`)
- Modify: `games/views/playthrough.py:326-341` (`record_completed`'s annotation)
- Test: `tests/test_playergame_view_cutover.py:252-254`,
  `tests/test_catalog_submit.py:258`

**Interfaces:**
- Consumes: `WriteAnswer` from Task 1.
- Produces:
  - `track_game_for_request(request, game, *, correlation_id) -> WriteAnswer`
  - `record_facts_for_request(request, game, *, status=None, mastered=None, correlation_id) -> WriteAnswer`
  - `record_completed(request, game, correlation_id) -> WriteAnswer`

No call site of these changes in this task. All eight truthiness reads
(`purchase.py:596`, `game.py:324`, `game.py:333`, `game.py:457`,
`playthrough_acts.py:57`, `playthrough_acts.py:78`, `playthrough.py:226`,
`playthrough.py:425`) and all three discards (`session.py:265`,
`playthrough_acts.py:62`, `playthrough.py:386`) keep working through `__bool__`.

- [ ] **Step 1: Point the doubles at the real type**

`tests/test_playergame_view_cutover.py:252-254` currently reads:

```python
    monkeypatch.setattr(
        "games.views.game.track_game_for_request",
        lambda request, game, *, correlation_id: False,
    )
```

Make it answer the type the function answers:

```python
    monkeypatch.setattr(
        "games.views.game.track_game_for_request",
        lambda request, game, *, correlation_id: WriteAnswer(
            CommandFailed("Nothing was recorded; try again.", CONFLICT_STATUS)
        ),
    )
```

`tests/test_catalog_submit.py:258` currently reads
`"games.views.game.record_facts_for_request", return_value=False`. Change
`return_value` to the same `WriteAnswer(CommandFailed(...))`. Import
`CommandFailed`, `CONFLICT_STATUS` and `WriteAnswer` from `games.writes.answers`
in both files.

- [ ] **Step 2: Run both files and watch them still pass**

```bash
flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make test ARGS="tests/test_playergame_view_cutover.py tests/test_catalog_submit.py"
```

Expected: PASS. A falsy `WriteAnswer` is what the old `False` meant, so nothing
moves. This is the step that proves `__bool__` carries the migration.

- [ ] **Step 3: Change the two signatures**

In `games/views/playergame_writes.py`, add `WriteAnswer` to the existing
`from games.writes.answers import CommandFailed` line, then in each of
`track_game_for_request` and `record_facts_for_request`:

- return annotation `bool` → `WriteAnswer`
- `return False` → `return WriteAnswer(failure)`
- `return True` → `return WriteAnswer(None)`
- the docstring's "False on failure" → "the refusal on failure"

Module docstring, second sentence: "A view that stays on its page toasts
and answers False" → "A view that stays on its page toasts and answers the
refusal".

- [ ] **Step 4: Retype `record_completed`**

`games/views/playthrough.py:326-341`: annotation `-> bool` → `-> WriteAnswer`,
and its closing docstring line "Answers False on a refusal, which toasted
already." → "Answers the refusal, which toasted already." Import `WriteAnswer`
from `games.writes.answers`. The body is a bare `return record_facts_for_request(...)`
and does not change.

mypy fails here if this is skipped: a `-> bool` function returning `WriteAnswer`
is an error.

- [ ] **Step 5: Type-check and run the affected suites**

```bash
make typecheck
flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make test ARGS="tests/test_playergame_view_cutover.py tests/test_catalog_submit.py tests/test_playergame_game_views.py tests/test_playergame_write_path.py"
```

Expected: mypy clean, tests PASS.

- [ ] **Step 6: Commit**

```bash
git add games/views/playergame_writes.py games/views/playthrough.py tests/test_playergame_view_cutover.py tests/test_catalog_submit.py
git commit -m "feat: answer a PlayerGame write with its refusal"
```

---

### Task 3: The four Playthrough wrappers answer it

**Files:**
- Modify: `games/views/playthrough_writes.py` (module docstring and the four
  `bool` wrappers)

**Interfaces:**
- Consumes: `WriteAnswer` from Task 1.
- Produces: `record_run_for_request`, `restate_run_for_request`,
  `start_run_for_request` and `complete_run_for_request` all answer
  `WriteAnswer`. Their parameters do not change.

No caller reads a status from these today, and none is changed here. They take
the type so the two write modules state one idea.

- [ ] **Step 1: Change the four signatures**

Add `WriteAnswer` to the `from games.writes.answers import CommandFailed` line.
In each of the four functions: annotation `bool` → `WriteAnswer`,
`return False` → `return WriteAnswer(failure)`, `return True` →
`return WriteAnswer(None)`, and the docstring's "False on a refusal" → "the
refusal on a refusal".

`record_run_for_request` keeps its tail intact — the `recorded.tracked_the_game`
info message still runs before `return WriteAnswer(None)`:

```python
    if recorded.tracked_the_game:
        messages.info(request, f"{game} is now tracked in your library.")
    return WriteAnswer(None)
```

`remove_run_for_request` is untouched; it raises.

Module docstring, second sentence: "A view that stays on its page toasts and
answers False." → "A view that stays on its page toasts and answers the
refusal."

- [ ] **Step 2: Type-check and run the playthrough suites**

```bash
make typecheck
flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make test ARGS="tests/test_playthrough_view_cutover.py tests/test_playthrough_writes.py tests/test_playthrough_companion_status.py"
```

Expected: mypy clean, tests PASS with no source change at any call site —
`playthrough_acts.py:57` and `:78` bind the answer to `stated` and read it as a
condition, which `__bool__` preserves.

- [ ] **Step 3: Commit**

```bash
git add games/views/playthrough_writes.py
git commit -m "feat: answer a Playthrough write with its refusal"
```

---

### Task 4: The refund reads the status

**Files:**
- Modify: `games/views/purchase.py:595-615`
- Test: `tests/test_playergame_view_cutover.py:375-402` and `:447-483`

**Interfaces:**
- Consumes: `record_facts_for_request -> WriteAnswer` from Task 2.
- Produces: nothing later tasks read.

- [ ] **Step 1: Parametrize both refund tests over two statuses**

`test_a_failed_refund_answers_409_and_swaps_nothing` states the number in its
name and its assertion. Rename it and take the status as a parameter:

```python
@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("status", [CONFLICT_STATUS, DEFECT_STATUS])
def test_a_failed_refund_answers_the_refusals_status_and_swaps_nothing(
    logged_in, owned_user, owned_library, monkeypatch, status
):
    ...

    def refuse(*args, **kwargs):
        raise CommandFailed("Nothing was recorded; try again.", status)

    #: Patched where the call is made, not where it is named.
    monkeypatch.setattr("games.views.playergame_writes.record_facts", refuse)
    response = logged_in.post(reverse("games:refund_purchase", args=[purchase.id]))

    #: htmx swaps nothing outside 2xx, so the row stands.
    assert response.status_code == status
    assert response.content == b""
    assert "show-toast" in response.headers["HX-Trigger"]
    purchase.refresh_from_db()
    assert purchase.date_refunded is None
```

Do the same to `test_a_partly_applied_refund_says_how_far_it_went`: add the
parametrize decorator and the `status` parameter, raise it from that test's own
double, and assert `response.status_code == status` in place of its `409`. Its
`"1 of 2 games were abandoned"` assertion stays — the sentence stands at both
statuses.

Import `CONFLICT_STATUS` and `DEFECT_STATUS` from `games.writes.answers` at the
top of the file rather than inside the test functions.

The double raises `CommandFailed` directly because `answered()` lives inside
`record_facts` and the patch stands in front of it. That is why a 500 needs no
conflict type.

- [ ] **Step 2: Run them and watch the 500 case fail**

```bash
flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make test ARGS="tests/test_playergame_view_cutover.py -k refund -x"
```

Expected: the `409` parameters PASS and both `500` parameters FAIL with
`assert 409 == 500`. That failure is the hole the issue names.

- [ ] **Step 3: Read the status in the view**

`games/views/purchase.py`, the refund loop. Replace the `if not …:` head and the
literal:

```python
    for abandoned, game in enumerate(games):
        answer = record_facts_for_request(
            request,
            game,
            status=PlayerGameStatus.ABANDONED,
            correlation_id=correlation_id,
        )
        if answer.refusal is not None:
            if abandoned:
                #: Say how far it went: the earlier games are
                #: abandoned already and no rollback takes them
                #: back. Refunding again restates the same fact,
                #: which build() absorbs, so a retry is safe.
                messages.error(
                    request,
                    f"{abandoned} of {len(games)} games were abandoned before "
                    "this one. Refunding again is safe.",
                )
            #: A redirect would swap into a cell.
            #: htmx swaps nothing outside 2xx.
            #: The toast rides the middleware's header.
            return HttpResponse(status=answer.refusal.status_code)
```

The three existing comments are kept verbatim. Nothing below the loop changes.

- [ ] **Step 4: Run them and watch all four pass**

```bash
make typecheck
flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make test ARGS="tests/test_playergame_view_cutover.py"
```

Expected: mypy clean, four refund parameters PASS.

- [ ] **Step 5: Commit**

```bash
git add games/views/purchase.py tests/test_playergame_view_cutover.py
git commit -m "fix: answer the refund with the status the refusal states"
```

---

### Task 5: `edit_game` re-renders at the refusal's status

**Files:**
- Modify: `games/views/game.py:455-492` (`edit_game`)
- Test: `tests/test_playergame_view_cutover.py:425-442`

**Interfaces:**
- Consumes: `record_facts_for_request -> WriteAnswer` from Task 2.
- Produces: nothing later tasks read.

- [ ] **Step 1: Parametrize the re-render test**

`test_a_failed_edit_re_renders_the_form` asserts 200. Keep its comment about the
redirect, take the status as a parameter:

```python
@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("status", [CONFLICT_STATUS, DEFECT_STATUS])
def test_a_failed_edit_re_renders_the_form(
    logged_in, tracked_game, monkeypatch, status
):
    def refuse(*args, **kwargs):
        raise CommandFailed("Nothing was recorded; try again.", status)

    monkeypatch.setattr("games.views.playergame_writes.record_facts", refuse)
    response = logged_in.post(
        reverse("games:edit_game", args=[tracked_game.id]),
        {**GAME_PAYLOAD, "status": "completed"},
    )

    #: A redirect would read as a save that landed.
    assert response.status_code == status
    assert "show-toast" in response.headers["HX-Trigger"]
    row = PlayerGame.objects.get(game=tracked_game)
    assert row.status == PlayerGameStatus.UNPLAYED
```

- [ ] **Step 2: Run it and watch both parameters fail**

```bash
flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make test ARGS="tests/test_playergame_view_cutover.py -k failed_edit -x"
```

Expected: FAIL with `assert 200 == 409`.

- [ ] **Step 3: Hold the refusal and answer its status**

In `edit_game`, declare the status before the validation branch — put it
directly above the `#: Both read; see \`add_game\`…` comment:

```python
    refused_status = 200
```

Then in the branch at `games/views/game.py:457`, replace the truthiness read:

```python
        written = submitted_game_or_form_error(form, graph, references)
        if written is not None:
            answer = record_facts_for_request(
                request,
                written,
                status=form.cleaned_data["status"],
                mastered=form.cleaned_data["mastered"],
                correlation_id=new_correlation_id(),
            )
            if answer.refusal is None:
                return redirect(return_url(request, fallback="games:list_games"))
            refused_status = answer.refusal.status_code
            #: The graph is written. Drawing it from storage rather
            #: than from the post is what makes the resubmit below
            #: land on those rows instead of making new ones.
            graph = CatalogGraphForm(
                None, game=written, library=library, presentation=presentation
            )
            references = ReferenceSetForm(None, target=written, library=library)
```

The sense inverts — the old code redirected on success inside `if …:`, and the
new code returns early on `refusal is None`. Narrowing on `answer.refusal is None`
rather than on `answer` is what lets mypy read `.status_code` two lines down.

Finally, pass it at the tail `render_page(...)` call, beside `title="Edit Game"`:

```python
status = (refused_status,)
```

The same return also serves a form the person must correct, which is why the
local starts at 200 rather than the render moving into a branch.

- [ ] **Step 4: Run it and watch both parameters pass**

```bash
make typecheck
flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make test ARGS="tests/test_playergame_view_cutover.py tests/test_catalog_submit.py tests/test_playergame_game_views.py"
```

Expected: mypy clean, tests PASS. Watch `test_catalog_submit.py` in particular:
its double makes `edit_game` and `add_game` refuse, so a mistake in the new
branch shows up there.

- [ ] **Step 5: Commit**

```bash
git add games/views/game.py tests/test_playergame_view_cutover.py
git commit -m "fix: answer a refused game edit with the refusal's status"
```

---

### Task 6: Both session forms re-render at the refusal's status

**Files:**
- Modify: `games/views/session.py` — `_render_session_form` (`:295`),
  `add_session` (`:309-356`), `edit_session` (`:369-397`)
- Create: `tests/test_refused_form_status.py`

**Interfaces:**
- Consumes: nothing from earlier tasks. These two views catch `CommandFailed`
  themselves; `WriteAnswer` does not reach them.
- Produces: `_render_session_form(request, form, title, status=200)`.

`resume_session` (`:405-421`) is untouched: it redirects, and a redirect states
no status of the refusal's.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_refused_form_status.py`:

```python
"""A form rendered again after a refused command answers its status."""

import pytest
from django.urls import reverse

from games.writes.answers import CONFLICT_STATUS, DEFECT_STATUS, CommandFailed

pytestmark = pytest.mark.django_db(transaction=True)


def _refuse(status):
    def refuse(*args, **kwargs):
        raise CommandFailed("Nothing was recorded; try again.", status)

    return refuse


@pytest.mark.parametrize("status", [CONFLICT_STATUS, DEFECT_STATUS])
def test_a_refused_new_session_renders_the_form_at_the_refusals_status(
    logged_in, tracked_game, monkeypatch, status
):
    monkeypatch.setattr("games.views.session.record_session", _refuse(status))
    response = logged_in.post(
        reverse("games:add_session"), _session_payload(tracked_game)
    )

    #: A redirect would read as a save that landed.
    assert response.status_code == status
    assert "show-toast" in response.headers["HX-Trigger"]


@pytest.mark.parametrize("status", [CONFLICT_STATUS, DEFECT_STATUS])
def test_a_refused_session_edit_renders_the_form_at_the_refusals_status(
    logged_in, owned_user, tracked_game, monkeypatch, status
):
    logged_in.post(reverse("games:add_session"), _session_payload(tracked_game))
    session = PlayerSession.objects.get()
    monkeypatch.setattr("games.views.session.restate_session", _refuse(status))
    response = logged_in.post(
        reverse("games:edit_session", args=[session.id]),
        _session_payload(tracked_game),
    )

    assert response.status_code == status
    assert "show-toast" in response.headers["HX-Trigger"]
```

`_session_payload` and the `logged_in` / `tracked_game` fixtures: copy the
helper from `tests/test_playergame_view_cutover.py:169-185` rather than
importing it across test modules, or lift it into `tests/session_rows.py`,
which `tests/test_session_writes.py` already imports from as `session_rows`. Import `PlayerSession` and
`PlayerGame` from `games.models` as that helper needs them.

- [ ] **Step 2: Run them and watch all four fail**

```bash
flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make test ARGS="tests/test_refused_form_status.py -x"
```

Expected: FAIL with `assert 200 == 409`.

- [ ] **Step 3: Give the renderer a status**

`games/views/session.py:295`:

```python
def _render_session_form(
    request: HttpRequest, form: SessionForm, title: str, status: int = 200
):
```

and pass `status=status` to the `render_page(...)` call inside it, beside
`scripts=`. Keep the function's existing annotation style.

- [ ] **Step 4: Hold the refusal in both views**

`add_session`: declare `refused_status = 200` directly above
`if request.method == "POST":`, set it in the handler, and pass it at the tail.

```python
            except CommandFailed as failure:
                messages.error(request, failure.message)
                refused_status = failure.status_code
```

```python
# TODO: re-add custom buttons #91
return _render_session_form(request, form, "Add New Session", status=refused_status)
```

`edit_session`: declare `refused_status = 200` directly above
`if form.is_valid():`, set it in its `except` the same way, and make the tail:

```python
    return _render_session_form(request, form, "Edit Session", status=refused_status)
```

Both views render that tail for a form the person must correct as well, which is
why each local starts at 200.

- [ ] **Step 5: Run them and watch all four pass**

```bash
make typecheck
flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make test ARGS="tests/test_refused_form_status.py tests/test_playergame_view_cutover.py tests/test_rendered_pages.py"
```

Expected: mypy clean, tests PASS.

- [ ] **Step 6: Commit**

```bash
git add games/views/session.py tests/test_refused_form_status.py
git commit -m "fix: answer a refused session form with the refusal's status"
```

---

### Task 7: The gate

**Files:** none.

- [ ] **Step 1: Prove the prose is clean**

```bash
make vale
make format
make lint
```

Expected: vale reports no findings, format leaves the tree unchanged.

- [ ] **Step 2: Run the whole gate**

```bash
flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make check > /tmp/check.log 2>&1
echo "exit: $?"
```

Read the exit code, not a grep of the output — ruff prints "All checks passed!"
even when a later stage fails.

Expected: exit 0.

- [ ] **Step 3: Commit anything the format pass moved, then stop**

Push and open the pull request only on the user's word. Merge with
`gh pr merge --merge`, never squash or rebase, and only when the user says
merge.

---

## What this plan does not do

- `remove_game_for_request`, `restore_game_for_request` and
  `remove_run_for_request` keep raising. `confirm_and_apply` already reads the
  status, and `restore_and_return` redirects, which states none.
- `add_game` keeps its 302 on both refusals: a refused `track_game` takes the
  inserted row back out, and re-rendering would invite a second game.
- `CommandFailed` keeps `status_code`. The alternative imports the conflict
  types into the view layer and derives again what `CONFLICT_ANSWERS` states
  once.
- No schema change, no migration, no new dependency.

## Self-review notes

Spec coverage, section by section:

| Spec section | Task |
| --- | --- |
| What a wrapper answers | 1 |
| Why the refund keeps its wrapper | 4 (no view catches the leaf) |
| Where it applies — six wrappers, `record_completed` | 2, 3 |
| Which views read the status — the refund | 4 |
| Every re-render reads it too | 5, 6 |
| The status stays on the exception | none needed; nothing changes |
| What a test notices | 1, 2, 4, 5, 6 |
