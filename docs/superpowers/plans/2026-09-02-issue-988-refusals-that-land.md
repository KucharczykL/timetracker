# A refusal lands where it can be read — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Three refusals reach the person who caused them. A second `is_valid()`
states no sentence twice, a refused confirmation says its reason apart from its
question and can actually be reached, and one function states the name key the
database compares by.

**Architecture:** `CatalogGraphForm` remembers its validation pass and computes
its answer fresh, because `answer()` writes sentences after `is_valid()`
returns. `ConfirmPage` grows a third slot that draws through `FieldErrors`, and
`remove_game_for_request` raises instead of toasting so that slot has a caller.
`common/naming.py` holds `name_key()`, imported by the form, the service and
`Platform.clean`.

**Tech Stack:** Django 6, Python 3.14, PostgreSQL 18, the in-house Python
component system, pytest.

**Spec:** `docs/superpowers/specs/2026-09-02-issue-988-refusals-that-land-design.md`

## Global Constraints

- **Drive everything through `make`.** Never `direnv exec .`, never a bare
  `uv run` / `pnpm` / `pytest`. Focused runs: `make test ARGS="…"`.
- **The verification gate is the full `make check`**, including `e2e/`. Use
  `make check-fast` only while iterating.
- **Nothing destroys a record.** `remove()` / `restore()` from
  `games/removal.py`; a confirmation is one `confirm_and_remove()` call.
- **Build UI with Python components**, htpy form only: static attributes as
  kwargs, children via `[]`.
- **Full words in identifiers**, Python and TypeScript.
- **Refused words** are enforced by `make vale` over docs *and code comments*.
  See `docs/vocabulary.md`.
- **No dispatch inside a transaction.** A test that POSTs through a dispatching
  view needs `@pytest.mark.django_db(transaction=True)`.
- **Name primitive roles** with a PEP 695 alias: `type NameKey = str`.

---

## File Structure

**Created**

| Path | Responsibility |
|---|---|
| `common/naming.py` | `NameKey`, `name_key()` — the one key the database compares names by |
| `tests/test_name_key.py` | The helper, and each of its three readers agreeing with the database |

**Modified**

| Path | Change |
|---|---|
| `games/catalog_form.py` | `is_valid()` remembers the pass and reads the answer fresh; `_validate_names` calls `name_key` |
| `games/catalog_writes.py` | `_refuse_taken_names` calls `name_key` |
| `games/models.py` | `Platform.clean` calls `name_key` |
| `common/components/primitives.py` | `ConfirmPage` grows the `refusal` slot |
| `games/views/removal.py` | `confirm_and_apply` passes every sentence into that slot |
| `games/views/playergame_writes.py` | `remove_game_for_request` raises instead of toasting |
| `docs/catalog.md` | The uniqueness rule names its case rule |
| `tests/test_catalog_graph_form.py` | Asking twice; asking after `answer()` |
| `tests/test_components.py` | The confirmation's third slot |
| `tests/test_confirmation_refusals.py` | Every sentence, apart from the question |
| `tests/test_playergame_game_views.py` | A refused removal renders 409 |

---

## Task 1: One validation, one answer

**Files:**
- Modify: `games/catalog_form.py:262,425-437`
- Test: `tests/test_catalog_graph_form.py`

**Interfaces:**
- Consumes: `reads_as_stated`, `_validate_set`, `_rows_by_key` — all already in
  the module.
- Produces: an `is_valid()` a renderer may call, which Task 4 of #998 and any
  later placement fix both need.

`_validate_names` and `_validate_releases` each pass over a row that already
carries an error, so their sentences do not double. `LAST_EDITION_IN_FORM`
(`form_errors.append`) and `LAST_RELEASE` (`block.form.add_error`) have no such
guard. Remember the pass; recompute the answer.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_catalog_graph_form.py`. Build the bound form with the
`posted()` / `block()` / `graph_form()` helpers the neighbouring tests use; do
not add a second set.

```python
def test_asking_twice_states_the_sentences_of_one_pass(owned_library, plain_game):
    """`LAST_RELEASE` and `LAST_EDITION_IN_FORM` have no row-level guard."""
    form = graph_form(
        posted(block(name="Deluxe", releases=[])),
        game=plain_game.game,
        library=owned_library,
    )

    assert not form.is_valid()
    first = [list(form.form_errors)] + [
        list(block.form.non_field_errors()) for block in form.blocks
    ]
    assert not form.is_valid()
    second = [list(form.form_errors)] + [
        list(block.form.non_field_errors()) for block in form.blocks
    ]

    assert second == first


def test_a_sentence_the_service_stated_makes_the_form_invalid(
    owned_library, plain_game
):
    """`answer()` writes after `is_valid()` returned, and the page re-renders."""
    form = graph_form(
        posted(block(name="Deluxe")), game=plain_game.game, library=owned_library
    )
    assert form.is_valid()

    form.answer(GraphRefused(DUPLICATE_EDITION_NAME, key=_key(form.blocks[0].form)))

    assert not form.is_valid()
```

`GraphRefused` is already imported in that file; import `DUPLICATE_EDITION_NAME`
and `_key` beside the existing `games.catalog_form` / `games.catalog_writes`
imports. `plain_game` is a `DefaultGraph` NamedTuple, not a Game — every call
site in the file reads `plain_game.game`, and so do these.

- [ ] **Step 2: Run them and watch them fail**

Run: `make test ARGS="tests/test_catalog_graph_form.py -k 'asking_twice or service_stated'"`

`ARGS` is interpolated unquoted into the pytest line, so a `-k` expression
carries its own quotes or the shell hands `or` to pytest as a path.

Expected: the first FAILs on a doubled sentence, the second FAILs because
`is_valid()` re-runs the pass and cannot see the added error as decisive.

- [ ] **Step 3: Make the change**

In `games/catalog_form.py`, beside `self.form_errors: list[str] = []` (line 262):

```python
        self._read = False
```

Replace `is_valid()` (lines 425-437):

A method body in a fence marked `python` is dedented by `ruff format`, and
`make check` then fails on the doc. Mark it `text`.

```text
    def is_valid(self) -> bool:
        """Every sentence that stands, however often asked."""
        if not self.is_bound:
            return False
        self._read_once()
        return not self.form_errors and not any(
            form.errors for form in self._rows_by_key().values()
        )

    def _read_once(self) -> None:
        """One pass over the rows and then over the set.

        A row states its own sentence once, because a field it
        already refused it does not read again. The set has no such
        guard: a second pass would state `LAST_EDITION_IN_FORM` and
        `LAST_RELEASE` beside the first. The answer above is read
        fresh every time, because `answer()` puts a service refusal
        on a row, or on `form_errors`, after this has returned, and
        the page then draws the form again.
        """
        if self._read:
            return
        self._read = True
        #: Every row, not up to the first false one: `_validate_set`
        #: reads each row's `cleaned_data`, and a row nobody read
        #: holds none.
        for block in self.blocks:
            reads_as_stated(block.form)
            going = block.removed
            for row in block.rows:
                reads_as_stated(row, going=going)
        self._validate_set()
```

The answer reads the same rule the pass counted by: `reads_as_stated` already
takes the non-identifying errors off a row stated as going, so `form.errors` on
such a row is empty unless its identity is wrong.

Measured while writing these: the row-level `answer()` case **already**
answers False, because `reads_as_stated` re-reads the child form and a bound
Django form caches `_errors`, so `add_error` on a row is seen. It stays as a
guard against remembering the verdict. The live defect is the other branch —
`answer()` on a refusal that names no row appends to `form_errors`, which the
old expression never read, so the form called itself valid while carrying a
refusal. A fourth test covers it.

- [ ] **Step 4: Run them and watch them pass**

Run: `make test ARGS="tests/test_catalog_graph_form.py tests/test_catalog_submit.py"`
Expected: PASS, whole files, no regression. `_validate_set` still moves the mark
to the first surviving row, and it still does so once.

- [ ] **Step 5: Commit**

```bash
git add games/catalog_form.py tests/test_catalog_graph_form.py
git commit -m "Let the catalog form state its sentences once"
```

---

## Task 2: The confirmation holds a slot for the reason

**Files:**
- Modify: `common/components/primitives.py:1937-1978`
- Test: `tests/test_components.py`

**Interfaces:**
- Consumes: `FieldErrors` (same module, line 1527).
- Produces: `ConfirmPage(refusal=…)` for Task 3.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_components.py`, beside the existing `ConfirmPage` tests:

```python
def test_the_confirmation_draws_a_refusal_before_the_question():
    """A reason inside the prompt reads as part of the standing question."""
    rendered = str(
        ConfirmPage(
            title="Remove game",
            message="Remove Elite from your library?",
            refusal=["The library no longer tracks it.", "Try again."],
            post_url="/remove/",
            csrf_token="x",
            cancel_url="/games/",
        )
    )

    assert "The library no longer tracks it." in rendered
    assert "Try again." in rendered
    assert rendered.index("no longer tracks") < rendered.index("Remove Elite")


def test_a_confirmation_nobody_refused_draws_no_error_list():
    rendered = str(
        ConfirmPage(
            title="Remove game",
            message="Remove Elite from your library?",
            post_url="/remove/",
            csrf_token="x",
            cancel_url="/games/",
        )
    )

    assert _FIELD_ERROR_CLASS.split()[0] not in rendered
```

Import `_FIELD_ERROR_CLASS` from `common.components.primitives` if the file does
not already read it; otherwise assert on `"<ul"` absence in the same way the
neighbouring tests assert on markup.

- [ ] **Step 2: Run them and watch them fail**

Run: `make test ARGS="tests/test_components.py -k confirmation"`
Expected: the first FAILs with `TypeError: ConfirmPage() got an unexpected
keyword argument 'refusal'`.

- [ ] **Step 3: Make the change**

In `common/components/primitives.py`:

```python
def ConfirmPage(
    *,
    title: str,
    message: Children,
    post_url: str,
    csrf_token: str,
    cancel_url: str,
    confirm_label: str = "Confirm",
    confirm_color: ButtonColor = "red",
    details: Children = None,
    refusal: Sequence[str] = (),
) -> Node:
    """Full-page confirmation: a prompt, a POST ``<form>`` (the confirm action)
    and a cancel link back to the origin. The no-JS replacement for the htmx
    confirmation modals — reusable across delete/refund/split/reset flows.

    Three slots, and neither of the two extra ones can live in ``message``,
    which renders inside a ``<p>``. ``refusal`` is why the last POST was
    turned down; it draws through ``FieldErrors`` above the prompt, so a
    person reads the reason and then the question that still stands, and so
    no page states a second way to draw a refusal. ``details`` is block
    content after the prompt (the data a removal would take with it).
    """
    refused = FieldErrors(refusal)
    return Div(
        class_=f"mx-auto w-full {FORM_MAX_WIDTH_CLASS} p-5 @container",
    )[
        Form(method="post", action=post_url)[
            Safe(
                f'<input type="hidden" name="csrfmiddlewaretoken" value="{csrf_token}">'
            ),
            DialogTitle(title),
            *([refused] if refused is not None else []),
            P(class_="text-heading text-center mt-5")[*as_children(message)],
            *(
                [Div(class_="text-heading text-center mt-3")[*as_children(details)]]
                if details
                else []
            ),
            Div(class_="flex flex-col gap-2 mt-6")[
                ControlButton(
                    color=confirm_color,
                    type="submit",
                )[confirm_label],
                ControlButton(href=cancel_url, color="gray")["Cancel"],
            ],
        ]
    ]
```

`Sequence` is already imported in that module.

- [ ] **Step 4: Run it and watch it pass**

Run: `make test ARGS="tests/test_components.py"`
Expected: PASS, whole file.

- [ ] **Step 5: Commit**

```bash
git add common/components/primitives.py tests/test_components.py
git commit -m "Give the confirmation page a slot for the reason it was refused"
```

---

## Task 3: The reason stops being part of the question

**Files:**
- Modify: `games/views/removal.py:50-76`
- Test: `tests/test_confirmation_refusals.py`

**Interfaces:**
- Consumes: `ConfirmPage(refusal=…)` from Task 2.
- Produces: nothing new. `confirm_and_apply` keeps its signature.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_confirmation_refusals.py`:

```python
SECOND = "Reload the page and try again."


def test_a_refusal_keeps_every_sentence_it_carried(post_request):
    """`messages[0]` threw the rest away."""

    def refuse():
        raise ValidationError([REFUSAL, SECOND])

    response = confirm_and_apply(
        post_request(),
        action=refuse,
        title="Remove edition",
        message="Remove it?",
        confirm_label="Remove",
        fallback="games:list_games",
    )
    body = response.content.decode()

    assert response.status_code == 409
    assert REFUSAL in body
    assert SECOND in body
    assert f"{REFUSAL} Remove it?" not in body
```

- [ ] **Step 2: Run it and watch it fail**

Run: `make test ARGS="tests/test_confirmation_refusals.py -k every_sentence"`
Expected: FAIL — `SECOND` is absent and the joined prompt is present.

- [ ] **Step 3: Make the change**

In `games/views/removal.py`:

```text
    def confirmation(refusal: Sequence[str] = (), status: int = 200) -> HttpResponse:
        return render_page(
            request,
            ConfirmPage(
                title=title,
                message=message,
                refusal=refusal,
                details=details,
                post_url=request.get_full_path(),
                csrf_token=get_token(request),
                cancel_url=return_url(
                    request, fallback=fallback, fallback_args=fallback_args
                ),
                confirm_label=confirm_label,
            ),
            title=title,
            status=status,
        )
```

and, in the handler:

```python
    except ValidationError as refusal:
        #: The service refuses on state, and state moves: another tab
        #: may have taken the sibling this removal counted on. A 500
        #: would read as our fault rather than as a stale page.
        return confirmation(refusal.messages, status=409)
```

`Sequence` is already imported at line 10.

- [ ] **Step 4: Run it and watch it pass**

Run: `make test ARGS="tests/test_confirmation_refusals.py tests/test_removal_helper.py tests/test_removal_confirmation.py"`
Expected: PASS, all three files.

- [ ] **Step 5: Commit**

```bash
git add games/views/removal.py tests/test_confirmation_refusals.py
git commit -m "Say why a confirmation was refused apart from the question"
```

---

## Task 4: A refused removal reaches that page

**Files:**
- Modify: `games/views/playergame_writes.py:1-4,59-74`
- Test: `tests/test_playergame_game_views.py`

**Interfaces:**
- Consumes: the `confirm_and_apply` contract — "an `action` that refuses puts
  its sentence back on the confirmation".
- Produces: the first real caller of the 409 branch. Before this task every
  live action either cannot raise (`remove(instance)` is an `UPDATE`) or does
  not (`session.py:355,376` save a Session), and `remove_game`'s refusal became
  a toast plus a redirect that read as success.

`track_game_for_request` and `record_facts_for_request` keep the toast: neither
runs under a confirmation, and the page they answer stays where it is.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_playergame_game_views.py`. `untrack_game` tolerates an
untracked game, so provoke the refusal at the seam:

```python
@pytest.mark.django_db(transaction=True)
def test_a_refused_removal_re_renders_the_confirmation(
    monkeypatch, logged_in, owned_library
):
    """The toast said nothing happened while the redirect said it did."""
    game = Game.objects.create(library=owned_library, name="Elite")

    def refuse(*_args, **_kwargs):
        raise CommandFailed("The library cannot stop tracking it.", 409)

    monkeypatch.setattr("games.views.playergame_writes.untrack_game", refuse)

    response = logged_in.post(reverse("games:remove_game", args=[game.pk]))

    assert response.status_code == 409
    assert "cannot stop tracking it" in response.content.decode()
    game.refresh_from_db()
    assert game.removed_at is None
```

`CommandFailed(message, status_code)` takes its code positionally
(`games/writes/answers.py:39`); every existing raise site passes it that way,
and the keyword `status=` raises `TypeError` from inside the stub, where
neither `except` clause is looking for it. `logged_in` is the module's own
fixture (`client` force-logged in as `owned_user`); the view is
`@login_required` and an anonymous `client` would answer 302 to the login page
for the wrong reason. Import `CommandFailed` from `games.writes.answers`. The
module sets no `pytestmark`, so the decorator goes on the test — the view
dispatches, and dispatch opens its own transaction.

- [ ] **Step 2: Run it and watch it fail**

Run: `make test ARGS="tests/test_playergame_game_views.py -k refused_removal"`
Expected: FAIL with `assert 302 == 409`.

- [ ] **Step 3: Make the change**

In `games/views/playergame_writes.py`, the module docstring:

```python
"""The request-shaped half of the write path.

games/writes/playergame.py raises. A view that stays on its page toasts
and answers False; one that stands behind a confirmation re-raises, so
the confirmation states the sentence itself.
"""
```

Add `from django.core.exceptions import ValidationError` to the imports, and
replace `remove_game_for_request`:

```python
def remove_game_for_request(request: HttpRequest, game: Game) -> None:
    """Untrack it, then take the row out.

    This order, and no transaction around it: dispatch opens its own
    and refuses to nest. A failure between the two leaves a game no
    list shows, and running the act again completes it.

    A refused command rises as a `ValidationError`, which is what
    `confirm_and_apply` reads: the confirmation comes back with the
    sentence on it and a 409. A toast here would have said no while
    the redirect said yes.
    """
    try:
        untrack_game(
            cast("User", request.user), game, correlation_id=new_correlation_id()
        )
    except CommandFailed as failure:
        raise ValidationError(failure.message) from failure
    remove(game)
```

The `request` parameter stays: `untrack_game` reads the actor off it.

- [ ] **Step 4: Run it and watch it pass**

Run: `make test ARGS="tests/test_playergame_game_views.py tests/test_playergame_view_cutover.py"`
Expected: PASS. No test asserts a toast or a redirect on a refused removal
today, and no test reads this function's return, so nothing else moves. If one
turns up, it asserts the 409 page instead — do not keep both.

- [ ] **Step 5: Commit**

```bash
git add games/views/playergame_writes.py tests/test_playergame_game_views.py
git commit -m "Let a refused game removal answer on its confirmation page"
```

---

## Task 5: One name key

**Files:**
- Create: `common/naming.py`
- Modify: `games/catalog_form.py:457,460`, `games/catalog_writes.py:196,198`,
  `games/models.py:451-452`, `docs/catalog.md:23`
- Test: `tests/test_name_key.py`

**Interfaces:**
- Consumes: nothing. `common/naming.py` imports no Django, so `games/models.py`
  can read it and cannot cycle. This is why the key does not live in
  `games/catalog_writes.py`, which imports `games.models`.
- Produces: `name_key()` for all three readers.

`casefold()` is not SQL `lower()`. `Straße`.casefold() is `strasse`, and the
database reads `straße`, so the form refuses a pair the constraint accepts.
`Platform.clean` has the same mismatch pointing the other way: it compares
`Lower(Trim(...))` to `.casefold()`, so a private `Straße` passes a shadow check
against a shared `STRASSE` — and no constraint stands behind that method, so the
wrong row is written and stays.

`catalog_writes.py:375` (`stored.name.strip() != state.name.strip()`) is not a
key. It asks whether a stored row is being renamed, exactly and case
sensitively. Leave it.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_name_key.py`:

```python
"""One key, and the three readers that must agree with the database."""

import pytest
from django.core.exceptions import ValidationError
from django.db.models.functions import Lower, Trim

from common.naming import name_key
from games.models import Platform

pytestmark = pytest.mark.django_db

#: The database reads this pair as two keys and `casefold()` as one.
DIVERGING = ("Straße", "STRASSE")


@pytest.mark.parametrize(
    "value",
    [
        *DIVERGING,
        " Deluxe ",
        #: SQL lowercases this to one character and Python to two.
        pytest.param(
            "İ",
            marks=pytest.mark.xfail(
                reason="simple case mapping; #998 takes the residue", strict=True
            ),
        ),
    ],
)
def test_the_key_is_what_the_database_compares(value):
    stored = Platform.objects.create(name=value)
    read = (
        Platform.objects.filter(pk=stored.pk)
        .annotate(key=Lower(Trim("name")))
        .values_list("key", flat=True)
        .first()
    )

    assert name_key(value) == read


def test_two_names_the_constraint_separates_are_two_names():
    assert name_key(DIVERGING[0]) != name_key(DIVERGING[1])


def test_a_private_platform_may_not_shadow_a_shared_one_in_another_case(
    owned_library,
):
    Platform.objects.create(name="STRASSE")

    with pytest.raises(ValidationError):
        Platform(name="strasse", library=owned_library).full_clean()
```

The `İ` parameter is `xfail(strict=True)` rather than dropped, so the one
divergence the fix does not close stays measured and a later fix to it fails
loudly. Measured against this database (PostgreSQL 18, builtin provider,
`C.UTF-8`): `lower('Straße')` is `straße`, `lower('İ')` is the single character
`i`, and `btrim` takes spaces where `str.strip()` takes every whitespace
character.

Add to `tests/test_catalog_graph_form.py`:

```python
def test_the_form_accepts_two_names_the_constraint_accepts(owned_library, plain_game):
    """`casefold()` read `Straße` and `STRASSE` as one name; the database does not."""
    form = graph_form(
        posted(block(name="Straße"), block(name="STRASSE")),
        game=plain_game.game,
        library=owned_library,
    )

    assert form.is_valid(), form.blocks[1].form.errors
```

And to `tests/test_state_catalog_graph.py`, the same pair through
`state_catalog_graph`, asserting two written Editions rather than a
`GraphRefused`. Mirror that file's own state-building helpers.

- [ ] **Step 2: Run them and watch them fail**

Run: `make test ARGS="tests/test_name_key.py"` → collection error, no module.
Then, one file at a time — `-k` is a `store` option, so two of them in one
command silently keep the last and collect both files whole:

```
make test ARGS="tests/test_catalog_graph_form.py -k two_names"
make test ARGS="tests/test_state_catalog_graph.py -k accepts"
```

Expected: FAIL — the form refuses, and the service raises `GraphRefused`.

- [ ] **Step 3: Make the change**

Create `common/naming.py`:

```python
"""What two names have to share to be one name.

The database compares an Edition name by `Lower(Trim(name))`, and
`Platform.clean` compares two Platforms the same way. `str.casefold()`
is not that function — it reads `Straße` and `STRASSE` as one name
where the database reads two — so every side states the key here.
"""

#: The comparison form of a name, never stored and never shown.
type NameKey = str


def name_key(value: str) -> NameKey:
    """What the database compares two names by."""
    return value.strip().lower()
```

In `games/catalog_form.py`, inside `_validate_names`:

```python
            if name_key(name) in taken:
                block.form.add_error("name", DUPLICATE_NAME_IN_FORM)
                valid = False
            taken.add(name_key(name))
```

In `games/catalog_writes.py`, inside `_refuse_taken_names`:

```python
    taken = {name_key(edition.name) for edition in untouched} - {""}
    for state in surviving:
        wanted = name_key(state.name)
```

In `games/models.py`, inside `Platform.clean`:

```python
            .filter(
                normalized_name=name_key(self.name),
                normalized_group=name_key(self.group),
            )
```

Type the two `taken` sets as `set[NameKey]`.

In `docs/catalog.md`, the paragraph at line 23:

```text
A name is unique among one Game's live Editions, ignoring surrounding space and
case as the database reads them: `Lower(Trim(name))`. `common/naming.py` states that
same key for every side that compares two names in Python, because `casefold()`
states a different one. Two Games may each hold an Edition of the same name. No
name is not a name, thus two unnamed Editions of one Game may stand, and the
constraint `unique_live_edition_name_per_game` excludes them.
```

- [ ] **Step 4: Run them and watch them pass**

Run: `make test ARGS="tests/test_name_key.py tests/test_catalog_graph_form.py tests/test_state_catalog_graph.py tests/test_catalog_identity.py"`
Expected: PASS, with the `İ` parameter xfailing as declared.

Then `make vale`, which reads the changed paragraph in `docs/catalog.md`.

- [ ] **Step 5: Commit**

```bash
git add common/naming.py games/catalog_form.py games/catalog_writes.py \
  games/models.py docs/catalog.md tests/test_name_key.py \
  tests/test_catalog_graph_form.py tests/test_state_catalog_graph.py
git commit -m "Compare two names by the key the database compares them by"
```

---

## Task 6: The gate, and the verdict on the defect nobody builds

**Files:**
- Modify: nothing in the tree. This task writes to GitHub and runs the gate.

- [ ] **Step 1: Run the full gate**

Run: `make check`
Expected: green, `e2e/` included. Never a hand-picked subset.

- [ ] **Step 2: Record the deferral verdict**

Comment on #988 with why its first defect closes unbuilt: #992 already moved
`LEGACY_IDENTITY_TAKEN` onto the Game form, and #889 takes the sentence, the
mirror and the two flat columns together, so a better placement has nothing to
inherit it.

Edit #601's follow-up line — it reads "a catalog refusal lands in the wrong
place, three ways" — to say two ways, and name #889 as the owner of the third.

A verdict that lives only in a chat is a verdict a later reader finds as an
omission.

- [ ] **Step 3: Open the pull request**

```bash
git push -u origin claude/issue-988-refusals-that-land
gh pr create --fill
```
