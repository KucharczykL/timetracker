# Companion Status Changes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Offer the status a lifecycle act implies beside that act — two checkboxes on the run form and two one-press actions on each run row — appending both events under one `correlation_id`.

**Architecture:** Nothing is inferred. Each surface dispatches its lifecycle command first, then, where the person asked for it, `record_facts` for the status, both under the submit's own `correlation_id`. One read decides whether Played may be offered at all, and both the render gate and the clean gate call it, so a posted box cannot demote a game the form never offered it for.

**Tech Stack:** Django 6, Python 3.14, pytest + pytest-django, the Python component system in `common/components/`.

**Spec:** `docs/superpowers/specs/2026-09-09-issue-683-companion-status-changes-design.md`

## Global Constraints

- **Never `instance.delete()`, never assign `Game.status`.** A PlayerGame fact is
  stated with `record_facts` / `record_facts_for_request`; a run is stated with
  the helpers in `games/writes/playthrough.py`.
- **No dispatch inside a transaction.** `run_in_transaction` refuses to nest, so
  no new view carries `@transaction.atomic`. Every test that POSTs through one
  needs `@pytest.mark.django_db(transaction=True)`.
- **No route mutates on GET.** Both new routes are `@require_POST`.
- **Every new route is classified** in `games/views/returns.py`, or
  `tests/test_returns_classification.py` fails.
- **Mutating links carry their origin** — `action_url(name, *args, origin=…)`,
  never bare `reverse()`; every mutating view ends with
  `redirect(return_url(request, fallback=…))`.
- **Buttons are `ControlButton` / `ButtonGroup`.** A state-changing member takes
  `method="post"`, `action=…` and `csrf_token=…`; it renders a no-JS `<form>`.
- **Complete words in identifiers**, and comments no longer than they need to be.
- **Refused words** (`fold`, `seam`, `tombstone`, `archive`, `delete` next to a
  record, `heal`): `make vale` fails the build on them in comments and docs.
- **The gate is `make check`, `e2e/` included.** `make check-fast` while
  iterating.
- The status word is **Completed**, never "Finished". `PlayerGameStatus` values
  are `unplayed`, `played`, `completed`, `retired`, `shelved`, `abandoned`.

---

## File Structure

| File | Responsibility |
|---|---|
| `games/reads/companion_status.py` | *new.* One read: may a start offer Played for this game? |
| `games/forms.py` | `PlaythroughForm`: `also_mark_played` / `also_mark_completed` replace `mark_as_finished`; render gate and clean gate both call the read |
| `games/views/playthrough.py` | Pass the game to the form; gate each companion on the draft's acts |
| `games/views/playthrough_acts.py` | *new.* The two POST views: `start_playthrough`, `complete_playthrough` |
| `games/urls.py` | Two routes |
| `games/views/returns.py` | Both names in `ORIGIN_AWARE` |
| `games/views/playthrough_rows.py` | `_actions` gains the act the run's state allows; `playthrough_tabledata` takes `csrf_token` |
| `games/views/game.py` | Thread `csrf_token` into the Playthroughs section |
| `tests/test_playthrough_companion_status.py` | *new.* Every behaviour in the spec's Verification table |

Task order is dependency order: Task 1 is the read both gates share, Task 2 the
form, Task 3 the form's two hosting views, Task 4 the two act routes, Task 5 the
row actions that reach them, Task 6 the sweep.

---

### Task 1: The read that decides whether Played may be offered

**Files:**
- Create: `games/reads/companion_status.py`
- Test: `tests/test_playthrough_companion_status.py`

**Interfaces:**
- Consumes: `tracked_game(library, game)` from `games/reads/playthrough_runs.py`,
  which answers the live `PlayerGame` row for a pair or `None`.
- Produces: `played_is_offered(library: UserLibrary, game: Game | None) -> bool`.

The rule from the spec: a start makes a game Played only where the game was
never played. A game the library does not track yet counts as offerable —
recording a run tracks it, and a game tracked by this submit was Unplayed a
moment ago. `game=None` is the generic Add form before a game is picked, which
renders the box and re-decides against the posted game at clean time.

- [ ] **Step 1: Write the failing test**

Create `tests/test_playthrough_companion_status.py` with this content:

```python
"""#683: the status a lifecycle act offers."""

import pytest

from games.models import Game, PlayerGameStatus
from games.reads.companion_status import played_is_offered
from games.writes.playergame import new_correlation_id, record_facts, track_game

#: TrackGame states the run, so the real command runs.
pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.untracked_games]


@pytest.fixture
def game(owned_library) -> Game:
    return Game.objects.create(library=owned_library, name="Outer Wilds")


@pytest.fixture
def tracked(owned_user, game) -> Game:
    track_game(owned_user, game, correlation_id=new_correlation_id())
    return game


def state(owned_user, game, status: PlayerGameStatus) -> None:
    record_facts(owned_user, game, status=status, correlation_id=new_correlation_id())


def test_an_untracked_game_is_offered_played(owned_library, game):
    assert played_is_offered(owned_library, game) is True


def test_a_game_with_no_name_yet_is_offered_played(owned_library):
    """The generic Add form, before a game is picked."""
    assert played_is_offered(owned_library, None) is True


def test_an_unplayed_game_is_offered_played(owned_library, tracked):
    assert played_is_offered(owned_library, tracked) is True


@pytest.mark.parametrize(
    "status",
    [
        PlayerGameStatus.PLAYED,
        PlayerGameStatus.COMPLETED,
        PlayerGameStatus.RETIRED,
        PlayerGameStatus.SHELVED,
        PlayerGameStatus.ABANDONED,
    ],
)
def test_every_stronger_status_is_offered_nothing(
    owned_user, owned_library, tracked, status
):
    """A checked box here would walk the status back."""
    state(owned_user, tracked, status)

    assert played_is_offered(owned_library, tracked) is False
```

- [ ] **Step 2: Run it and watch it fail**

Run: `make test ARGS="tests/test_playthrough_companion_status.py -x"`

Expected: collection error, `ModuleNotFoundError: No module named 'games.reads.companion_status'`.

- [ ] **Step 3: Write the read**

Create `games/reads/companion_status.py`:

```python
"""Which status a lifecycle act may offer."""

from games.models import Game, PlayerGameStatus, UserLibrary
from games.reads.playthrough_runs import tracked_game


def played_is_offered(library: UserLibrary, game: Game | None) -> bool:
    """True where a start would newly make the game Played.

    A game completed once stays completed, so a start
    states nothing about it and the box does not render.
    An untracked game counts: recording a run tracks it,
    and a game tracked by this submit was Unplayed a
    moment ago. No game at all is the generic Add form
    before one is picked, which decides again at clean
    time against the game the submit names.
    """
    if game is None:
        return True
    tracked = tracked_game(library, game)
    return tracked is None or tracked.status == PlayerGameStatus.UNPLAYED
```

- [ ] **Step 4: Run it and watch it pass**

Run: `make test ARGS="tests/test_playthrough_companion_status.py -x"`

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add games/reads/companion_status.py tests/test_playthrough_companion_status.py
git commit -m "Read whether a start may offer Played"
```

---

### Task 2: Two boxes on the run form

**Files:**
- Modify: `games/forms.py:1031-1094` (`PlaythroughForm`)
- Test: `tests/test_playthrough_form.py`

**Interfaces:**
- Consumes: `played_is_offered(library, game)` from Task 1.
- Produces: `PlaythroughForm(..., library=…, presentation=…, locked_game=None, offered_game=None)`.
  `offered_game: Game | None` is the game whose status decides the render gate —
  the Add-for-game and Edit views pass one, the generic Add view passes `None`.
  `cleaned_data["also_mark_played"]` and `cleaned_data["also_mark_completed"]`
  are always present and always `bool`.

Three defects go with `mark_as_finished`: the word "Finished" (it is Completed
since #672), the unconditional fire, and `initial={"mark_as_finished": True}`,
which handed a `BooleanField` a dict that is merely truthy. The replacements
declare `initial=True` outright.

The render gate takes the field out of `self.fields` entirely, so `FormFields`
draws nothing. The clean gate re-decides against the posted game, because the
generic Add form renders the box before any game is picked and a posted
`also_mark_played=on` must not demote a Completed game.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_playthrough_form.py`:

```python
@pytest.mark.django_db
def test_both_boxes_render_checked_for_an_untracked_game(user, game):
    form = PlaythroughForm(
        library=user.library, presentation=PRESENTATION, offered_game=game
    )

    assert form.fields["also_mark_played"].label == "Also mark this game Played"
    assert form.fields["also_mark_played"].initial is True
    assert form.fields["also_mark_completed"].label == "Also mark this game Completed"
    assert form.fields["also_mark_completed"].initial is True
    assert "mark_as_finished" not in form.fields


@pytest.mark.django_db(transaction=True)
@pytest.mark.untracked_games
def test_a_completed_game_renders_no_played_box(owned_user, owned_library):
    from games.models import PlayerGameStatus
    from games.writes.playergame import new_correlation_id, record_facts, track_game

    game = Game.objects.create(library=owned_library, name="Tunic")
    track_game(owned_user, game, correlation_id=new_correlation_id())
    record_facts(
        owned_user,
        game,
        status=PlayerGameStatus.COMPLETED,
        correlation_id=new_correlation_id(),
    )

    form = PlaythroughForm(
        library=owned_library, presentation=PRESENTATION, offered_game=game
    )

    assert "also_mark_played" not in form.fields
    assert "also_mark_completed" in form.fields


@pytest.mark.django_db(transaction=True)
@pytest.mark.untracked_games
def test_a_posted_played_box_is_dropped_for_a_completed_game(owned_user, owned_library):
    """The generic Add form renders the box before a game is picked."""
    from games.models import PlayerGameStatus
    from games.writes.playergame import new_correlation_id, record_facts, track_game

    game = Game.objects.create(library=owned_library, name="Tunic")
    track_game(owned_user, game, correlation_id=new_correlation_id())
    record_facts(
        owned_user,
        game,
        status=PlayerGameStatus.COMPLETED,
        correlation_id=new_correlation_id(),
    )

    form = PlaythroughForm(
        {
            "game": str(game.pk),
            "started": "2026-01-02",
            "ended": "",
            "note": "",
            "also_mark_played": "on",
            "also_mark_completed": "on",
        },
        library=owned_library,
        presentation=PRESENTATION,
    )

    assert form.is_valid(), form.errors
    assert form.cleaned_data["also_mark_played"] is False
    assert form.cleaned_data["also_mark_completed"] is True


@pytest.mark.django_db
def test_an_unticked_box_cleans_to_false(user, game):
    form = PlaythroughForm(
        {"game": str(game.pk), "started": "", "ended": "", "note": ""},
        library=user.library,
        presentation=PRESENTATION,
        offered_game=game,
    )

    assert form.is_valid(), form.errors
    assert form.cleaned_data["also_mark_played"] is False
    assert form.cleaned_data["also_mark_completed"] is False
```

- [ ] **Step 2: Run them and watch them fail**

Run: `make test ARGS="tests/test_playthrough_form.py -x"`

Expected: `TypeError: PlaythroughForm.__init__() got an unexpected keyword argument 'offered_game'`.

- [ ] **Step 3: Replace the field**

In `games/forms.py`, delete the `mark_as_finished` declaration:

```
    mark_as_finished = forms.BooleanField(
        required=False,
        initial={"mark_as_finished": True},
        label="Set game status to Finished",
    )
```

and put these two in its place, still in the class body:

```
    #: Rendered only on an Unplayed game: a start states
    #: nothing about one already played or stronger, and a
    #: checked box there would walk the status back.
    also_mark_played = forms.BooleanField(
        required=False,
        initial=True,
        label="Also mark this game Played",
    )
    also_mark_completed = forms.BooleanField(
        required=False,
        initial=True,
        label="Also mark this game Completed",
    )
```

Add `offered_game` to `__init__`'s keyword-only parameters, beside
`locked_game`, and take the field out where the status is stronger. The new
lines at the end of `__init__`:

```
        #: The status decides the render, and clean()
        #: decides again against the game that was posted.
        if not played_is_offered(library, offered_game):
            del self.fields["also_mark_played"]
```

Add the clean method under `clean_game`:

```
    def clean(self) -> dict[str, Any]:
        """Drop a box this game is offered no status by.

        The generic Add form renders the Played box before
        a game is picked, so a posted one is decided here
        against the game the submit names. A field the
        render gate took out cleans to False on its own.
        """
        cleaned = super().clean()
        cleaned.setdefault("also_mark_played", False)
        cleaned.setdefault("also_mark_completed", False)
        game = cleaned.get("game")
        if game is not None and not played_is_offered(self.library, game):
            cleaned["also_mark_played"] = False
        return cleaned
```

Add the imports `from typing import Any` (if absent) and
`from games.reads.companion_status import played_is_offered` at the top of
`games/forms.py`.

- [ ] **Step 4: Run them and watch them pass**

Run: `make test ARGS="tests/test_playthrough_form.py -x"`

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add games/forms.py tests/test_playthrough_form.py
git commit -m "Offer Played and Completed as two boxes"
```

---

### Task 3: The form's two hosting views act on the boxes

**Files:**
- Modify: `games/views/playthrough.py:184-264` (`add_playthrough`),
  `games/views/playthrough.py:335-402` (`_record_completed`, `edit_playthrough`)
- Test: `tests/test_playthrough_companion_status.py`,
  `tests/test_playthrough_view_cutover.py:57-77`,
  `tests/test_playergame_view_cutover.py:284-318`

**Interfaces:**
- Consumes: `played_is_offered` (Task 1); `PlaythroughForm(..., offered_game=…)`
  and its two cleaned booleans (Task 2); `record_facts_for_request` and
  `RunDraft` as they already are.
- Produces: `_record_companion_status(request, game, draft, form, correlation_id) -> None`
  in `games/views/playthrough.py` — the one place both hosting views state the
  companion.

Each box acts only where the draft states the matching act. That is read off the
`RunDraft`, not off the form's date fields: `_recorded_draft` states both acts
whether or not a day was given (adding a run records both), while
`_edited_draft` states an act only where the person recorded one, so a note-only
edit states neither. Reading the draft makes one rule serve both views.

Watch out: three shipped tests post `mark_as_finished` and must be renamed to
`also_mark_completed`. Two of them
(`tests/test_playergame_view_cutover.py::test_adding_a_play_event_records_completed`
and `tests/test_playthrough_view_cutover.py::test_marking_finished_states_the_status_under_one_correlation_id`)
go through `add_playthrough`, whose draft states a completion regardless of the
blank date field, so they keep passing on a rename alone.
`tests/test_playergame_view_cutover.py::test_editing_a_play_event_records_completed_too`
goes through `edit_playthrough` with both date fields blank against a run that
states no act — under the new rule that submit states no completion, so the
test must post `"ended": "2026-01-02"` for the status to follow.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_playthrough_companion_status.py`:

```python
from django.urls import reverse

from games.models import LibraryEvent, PlayerGame, Playthrough


@pytest.fixture
def logged_in(client, owned_user):
    client.force_login(owned_user)
    return client


def status_of(owned_library) -> str:
    return PlayerGame.objects.get(library=owned_library).status


def test_a_first_start_states_played(logged_in, owned_library, game):
    logged_in.post(
        reverse("games:add_playthrough"),
        {
            "game": str(game.pk),
            "started": "2026-01-02",
            "ended": "",
            "note": "",
            "also_mark_played": "on",
        },
    )

    assert status_of(owned_library) == PlayerGameStatus.PLAYED


def test_the_pair_shares_one_correlation(logged_in, owned_library, game):
    logged_in.post(
        reverse("games:add_playthrough"),
        {
            "game": str(game.pk),
            "started": "2026-01-02",
            "ended": "",
            "note": "",
            "also_mark_played": "on",
        },
    )

    correlations = set(
        LibraryEvent.objects.filter(library=owned_library).values_list(
            "correlation_id", flat=True
        )
    )
    assert len(correlations) == 1


def test_a_start_on_a_completed_game_states_nothing(
    owned_user, logged_in, owned_library, tracked
):
    """The box never rendered, so a posted one is dropped."""
    state(owned_user, tracked, PlayerGameStatus.COMPLETED)

    logged_in.post(
        reverse("games:add_playthrough"),
        {
            "game": str(tracked.pk),
            "started": "2026-01-02",
            "ended": "",
            "note": "",
            "also_mark_played": "on",
        },
    )

    assert status_of(owned_library) == PlayerGameStatus.COMPLETED


def test_a_completion_states_completed(logged_in, owned_library, game):
    logged_in.post(
        reverse("games:add_playthrough"),
        {
            "game": str(game.pk),
            "started": "2026-01-02",
            "ended": "2026-02-03",
            "note": "",
            "also_mark_completed": "on",
        },
    )

    assert status_of(owned_library) == PlayerGameStatus.COMPLETED


def test_a_note_only_edit_states_no_status(
    owned_user, logged_in, owned_library, tracked
):
    """Both boxes ticked, and neither act is stated."""
    run = Playthrough.objects.get(player_game__game=tracked)

    logged_in.post(
        reverse("games:edit_playthrough", args=[run.pk]),
        {
            "game": str(tracked.pk),
            "started": "",
            "ended": "",
            "note": "read the manual",
            "also_mark_played": "on",
            "also_mark_completed": "on",
        },
    )

    run.refresh_from_db()
    assert run.note == "read the manual"
    assert status_of(owned_library) == PlayerGameStatus.UNPLAYED
```

- [ ] **Step 2: Run them and watch them fail**

Run: `make test ARGS="tests/test_playthrough_companion_status.py -x"`

Expected: `test_a_first_start_states_played` fails with
`assert 'unplayed' == 'played'` — nothing reads the new box yet.

- [ ] **Step 3: Act on the boxes**

In `games/views/playthrough.py`, add the companion helper beside
`_record_completed`:

```python
def _record_companion_status(
    request: HttpRequest,
    game: Game,
    draft: RunDraft,
    form: PlaythroughForm,
    correlation_id: uuid.UUID,
) -> None:
    """State the status the stated acts imply.

    Each box acts only where the draft states its act, so
    a note-only edit states nothing. Completed goes second
    and wins: a submit that states both acts leaves the
    game Completed, not Played.

    Every answer is discarded on purpose. A refused status
    toasts, and the run it belongs to stands.
    """
    if draft.started is not None and form.cleaned_data["also_mark_played"]:
        record_facts_for_request(
            request,
            game,
            status=PlayerGameStatus.PLAYED,
            correlation_id=correlation_id,
        )
    if draft.completed is not None and form.cleaned_data["also_mark_completed"]:
        _record_completed(request, game, correlation_id)
```

In `add_playthrough`, pass the game whose status gates the render and call the
helper. The form construction becomes:

```python
    form = PlaythroughForm(
        request.POST or None,
        initial=initial,
        library=library,
        presentation=date_time_presentation_for_request(request),
        offered_game=initial.get("game"),
    )
```

and the success branch becomes:

```
    if form.is_valid():
        game = form.cleaned_data["game"]
        correlation_id = new_correlation_id()
        draft = _recorded_draft(form)
        if record_run_for_request(
            request, game, draft, correlation_id=correlation_id
        ):
            _record_companion_status(request, game, draft, form, correlation_id)
            return redirect(
                return_url(
                    request,
                    fallback="games:view_game",
                    fallback_args=[game.id, game.url_slug],
                )
            )
```

In `edit_playthrough`, add `offered_game=game` beside `locked_game=game` in the
form construction, and make the success branch:

```
    if form.is_valid():
        correlation_id = new_correlation_id()
        draft = _edited_draft(form, run)
        if restate_run_for_request(
            request, run, draft, correlation_id=correlation_id
        ):
            _record_companion_status(request, game, draft, form, correlation_id)
            return redirect(
                return_url(
                    request,
                    fallback="games:view_game",
                    fallback_args=[game.id, game.url_slug],
                )
            )
```

- [ ] **Step 4: Run them and watch them pass**

Run: `make test ARGS="tests/test_playthrough_companion_status.py -x"`

Expected: 13 passed.

- [ ] **Step 5: Move the three shipped tests onto the new name**

In `tests/test_playthrough_view_cutover.py:71` and
`tests/test_playergame_view_cutover.py:293`, replace the key
`"mark_as_finished": "on"` with `"also_mark_completed": "on"`.

In `tests/test_playergame_view_cutover.py`, the edit case at line 315 needs the
act as well as the box, because a blank field beside no stated act now states
nothing. Its payload becomes:

```
        {
            "game": str(tracked_game.id),
            "started": "",
            "ended": "2026-01-02",
            "note": "",
            "also_mark_completed": "on",
        },
```

- [ ] **Step 6: Run the three and watch them pass**

Run: `make test ARGS="tests/test_playthrough_view_cutover.py tests/test_playergame_view_cutover.py -x"`

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add games/views/playthrough.py tests/test_playthrough_companion_status.py \
        tests/test_playthrough_view_cutover.py tests/test_playergame_view_cutover.py
git commit -m "State the status the run form's boxes ask for"
```

---

### Task 4: Two POST routes that state today's act

**Files:**
- Create: `games/views/playthrough_acts.py`
- Modify: `games/urls.py:69-85`, `games/views/returns.py:40-68`
- Test: `tests/test_playthrough_companion_status.py`

**Interfaces:**
- Consumes: `played_is_offered` (Task 1); `_editable_runs(library)` and
  `_record_completed` — both currently private to `games/views/playthrough.py`,
  so this task renames them to `editable_runs` and `record_completed` and
  updates their four call sites in that module.
- Produces: view functions `start_playthrough(request, playthrough_id)` and
  `complete_playthrough(request, playthrough_id)`, routed as
  `games:start_playthrough` and `games:complete_playthrough`, both taking
  `<uuidv7:playthrough_id>`.

Both state today's day. A day that is not today belongs in the edit form, which
holds every precision the grammar knows. Neither confirms: each is reversible
through the correction commands #1010 shipped.

Neither gates on the run's state. `StartPlaythrough` refuses a second statement
of an endpoint in its own words, and a second gate here could disagree with it —
the same reasoning `_actions` already records for Remove.

The status companion does gate, because `record_facts` would not answer
`Unchanged` for a demotion: stating Played on a Completed game would walk it
back, so `played_is_offered` decides.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_playthrough_companion_status.py`:

```python
from django.utils import timezone


def test_starting_a_run_states_today_and_played(logged_in, owned_library, tracked):
    run = Playthrough.objects.get(player_game__game=tracked)

    logged_in.post(reverse("games:start_playthrough", args=[run.pk]))

    run.refresh_from_db()
    assert run.start_recorded_at is not None
    assert run.started_lower == timezone.localdate()
    assert status_of(owned_library) == PlayerGameStatus.PLAYED


def test_completing_a_run_states_today_and_completed(logged_in, owned_library, tracked):
    run = Playthrough.objects.get(player_game__game=tracked)
    logged_in.post(reverse("games:start_playthrough", args=[run.pk]))

    logged_in.post(reverse("games:complete_playthrough", args=[run.pk]))

    run.refresh_from_db()
    assert run.completion_recorded_at is not None
    assert run.completed_upper == timezone.localdate()
    assert status_of(owned_library) == PlayerGameStatus.COMPLETED


def test_a_start_on_a_completed_game_leaves_the_status(
    owned_user, logged_in, owned_library, tracked
):
    state(owned_user, tracked, PlayerGameStatus.COMPLETED)
    run = Playthrough.objects.get(player_game__game=tracked)

    logged_in.post(reverse("games:start_playthrough", args=[run.pk]))

    run.refresh_from_db()
    assert run.start_recorded_at is not None
    assert status_of(owned_library) == PlayerGameStatus.COMPLETED


def test_neither_act_answers_a_get(logged_in, tracked):
    run = Playthrough.objects.get(player_game__game=tracked)

    for name in ("games:start_playthrough", "games:complete_playthrough"):
        assert logged_in.get(reverse(name, args=[run.pk])).status_code == 405


def test_an_act_keeps_the_run_note(logged_in, owned_user, owned_library, tracked):
    """The restatement carries the note, so no describe fires."""
    run = Playthrough.objects.get(player_game__game=tracked)
    logged_in.post(
        reverse("games:edit_playthrough", args=[run.pk]),
        {"game": str(tracked.pk), "started": "", "ended": "", "note": "12h"},
    )

    logged_in.post(reverse("games:start_playthrough", args=[run.pk]))

    run.refresh_from_db()
    assert run.note == "12h"
```

- [ ] **Step 2: Run them and watch them fail**

Run: `make test ARGS="tests/test_playthrough_companion_status.py -k act_or_start_or_complet -x"`

Expected: `NoReverseMatch: Reverse for 'start_playthrough' not found.`

- [ ] **Step 3: Rename the two helpers the new module shares**

In `games/views/playthrough.py`, rename `_editable_runs` to `editable_runs` and
`_record_completed` to `record_completed`, and update every call: two in
`edit_playthrough` and `remove_playthrough` for the first, two in
`_record_companion_status` for the second. Both are now part of the module's
surface, so their docstrings stay as they are.

- [ ] **Step 4: Write the two views**

Create `games/views/playthrough_acts.py`:

```python
"""One press states one endpoint, dated today."""

import uuid
from typing import cast
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from games.commands.playthrough import ActStatement
from games.models import Game, PlayerGameStatus, Playthrough
from games.ownership import owned_or_404
from games.reads.companion_status import played_is_offered
from games.views.playergame_writes import record_facts_for_request
from games.views.playthrough import editable_runs, record_completed
from games.views.playthrough_writes import restate_run_for_request
from games.views.returns import return_url
from games.writes.playergame import new_correlation_id
from games.writes.playthrough import RunDraft
from timetracker.temporal import TemporalValue


def _today() -> ActStatement:
    """The act happened when it was pressed."""
    return ActStatement(TemporalValue.from_day(timezone.localdate()))


def _run_of(request: HttpRequest, playthrough_id: UUID) -> Playthrough:
    library = cast("User", request.user).library
    return owned_or_404(editable_runs(library), library, id=playthrough_id)


def _back_to(request: HttpRequest, game: Game) -> HttpResponse:
    return redirect(
        return_url(
            request,
            fallback="games:view_game",
            fallback_args=[game.id, game.url_slug],
        )
    )


def _state_endpoint(
    run: Playthrough,
    request: HttpRequest,
    correlation_id: uuid.UUID,
    *,
    started: ActStatement | None = None,
    completed: ActStatement | None = None,
) -> bool:
    """State one endpoint, and nothing else.

    The run's own note rides along, so the restatement
    describes nothing and the endpoint the caller did not
    name is left alone.

    A run that states this endpoint already is refused by
    the command in its own words. No gate here: a second
    one could disagree with it.
    """
    return restate_run_for_request(
        request,
        run,
        RunDraft(started=started, completed=completed, note=run.note),
        correlation_id=correlation_id,
    )


@login_required
@require_POST
def start_playthrough(request: HttpRequest, playthrough_id: UUID) -> HttpResponse:
    """Record that this run started today."""
    run = _run_of(request, playthrough_id)
    game = run.player_game.game
    library = cast("User", request.user).library
    correlation_id = new_correlation_id()
    if _state_endpoint(run, request, correlation_id, started=_today()) and (
        played_is_offered(library, game)
    ):
        #: Discarded on purpose: a refused status toasts,
        #: and the act it belongs to stands.
        record_facts_for_request(
            request,
            game,
            status=PlayerGameStatus.PLAYED,
            correlation_id=correlation_id,
        )
    return _back_to(request, game)


@login_required
@require_POST
def complete_playthrough(request: HttpRequest, playthrough_id: UUID) -> HttpResponse:
    """Record that this run was completed today."""
    run = _run_of(request, playthrough_id)
    game = run.player_game.game
    correlation_id = new_correlation_id()
    if _state_endpoint(run, request, correlation_id, completed=_today()):
        record_completed(request, game, correlation_id)
    return _back_to(request, game)
```

- [ ] **Step 5: Route them**

In `games/urls.py`, add `playthrough_acts` to the `games.views` import list and
these two entries after the `remove_playthrough` path:

```
    path(
        "playthrough/<uuidv7:playthrough_id>/start",
        playthrough_acts.start_playthrough,
        name="start_playthrough",
    ),
    path(
        "playthrough/<uuidv7:playthrough_id>/complete",
        playthrough_acts.complete_playthrough,
        name="complete_playthrough",
    ),
```

In `games/views/returns.py`, add `"games:complete_playthrough"` and
`"games:start_playthrough"` to `ORIGIN_AWARE`, in alphabetical order — each
mutates and then redirects to its origin. `IN_PLACE` is the bucket for a route
that answers with a partial swap, and neither of these does.

- [ ] **Step 6: Run them and watch them pass**

Run: `make test ARGS="tests/test_playthrough_companion_status.py tests/test_returns_classification.py -x"`

Expected: all pass, the classification guard included.

- [ ] **Step 7: Commit**

```bash
git add games/views/playthrough_acts.py games/views/playthrough.py games/urls.py \
        games/views/returns.py tests/test_playthrough_companion_status.py
git commit -m "Add two routes that state a run's endpoint today"
```

---

### Task 5: The act each run row allows

**Files:**
- Modify: `games/views/playthrough_rows.py:39-135`,
  `games/views/game.py:955-982` (`_playthroughs_section`) and its caller in
  `view_game`, `games/views/playthrough.py:120-181` (`list_playthroughs`)
- Test: `tests/test_playthrough_rows.py`, `tests/test_game_detail_playthroughs.py`

**Interfaces:**
- Consumes: the two routes from Task 4; `stated_start` / `stated_completion`
  from `games/reads/playthrough_endpoints.py`, already imported by the row
  module.
- Produces: `playthrough_tabledata(runs, presentation, exclude_columns=(), *, origin, sort_terms=(), sortable=False, csrf_token="")`.
  `csrf_token` defaults to empty, so a caller that renders no act — a test, a
  future read-only embed — needs no change; a POST member with no token still
  renders, and Django refuses the submit, which is why both live callers pass
  one.

The row builder is shared by the Game detail section and the Playthroughs list
page. Both get the act: it is one builder, and there is no reason the list page
should show a run whose act it cannot state. The spec names Game detail because
that is where #1012 put the rows.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_playthrough_rows.py`:

```python
def actions_of(owned_library, run, presentation, **options) -> str:
    """The last cell of the one row, stringified."""
    data = tabledata_of(owned_library, run, presentation, **options)
    [row] = data["rows"]
    return str(row["cell_data"][-1])


def test_a_run_with_no_start_offers_start(owned_library, run, presentation):
    actions = actions_of(owned_library, run, presentation, csrf_token="token")

    assert f"/playthrough/{run.pk}/start" in actions
    assert f"/playthrough/{run.pk}/complete" not in actions
    assert 'method="post"' in actions
    assert "token" in actions


def test_a_started_run_offers_complete(owned_user, owned_library, run, presentation):
    _state_start(owned_user, run)

    actions = actions_of(owned_library, run, presentation, csrf_token="token")

    assert f"/playthrough/{run.pk}/complete" in actions
    assert f"/playthrough/{run.pk}/start" not in actions


def test_a_finished_run_offers_neither(owned_user, owned_library, run, presentation):
    _state_start(owned_user, run)
    _state_completion(owned_user, run)

    actions = actions_of(owned_library, run, presentation, csrf_token="token")

    assert f"/playthrough/{run.pk}/start" not in actions
    assert f"/playthrough/{run.pk}/complete" not in actions
    assert f"/playthrough/edit/{run.pk}" in actions
```

and these two helpers, above the tests:

```python
def _state_start(owned_user, run) -> None:
    from games.commands.playthrough import ActStatement
    from games.writes.playthrough import RunDraft, restate_run

    restate_run(
        owned_user,
        run,
        RunDraft(
            started=ActStatement(TemporalValue.from_day(date(2026, 1, 2))),
            completed=None,
            note=run.note,
        ),
        correlation_id=new_correlation_id(),
    )
    run.refresh_from_db()


def _state_completion(owned_user, run) -> None:
    from games.commands.playthrough import ActStatement
    from games.writes.playthrough import RunDraft, restate_run

    restate_run(
        owned_user,
        run,
        RunDraft(
            started=None,
            completed=ActStatement(TemporalValue.from_day(date(2026, 2, 3))),
            note=run.note,
        ),
        correlation_id=new_correlation_id(),
    )
    run.refresh_from_db()
```

- [ ] **Step 2: Run them and watch them fail**

Run: `make test ARGS="tests/test_playthrough_rows.py -x"`

Expected: `TypeError: playthrough_tabledata() got an unexpected keyword argument 'csrf_token'`.

- [ ] **Step 3: Build the act into the row**

In `games/views/playthrough_rows.py`, give `playthrough_tabledata` a
keyword-only `csrf_token: str = ""` parameter and pass it into the `_actions`
call, which becomes `_actions(run, origin, csrf_token)`.

Replace `_actions` with:

```python
def _actions(run: Playthrough, origin: OriginUrl | None, csrf_token: str) -> Cell:
    """The act this run allows, then edit and remove.

    One press states today. A day that is not today
    belongs in the edit form, which holds every precision
    the grammar knows.

    Remove renders on the last run too: the command owns
    that refusal, and a second gate can disagree with it.
    """
    return ButtonGroup(
        [
            _act_member(run, origin, csrf_token),
            {
                "href": action_url("games:edit_playthrough", run.pk, origin=origin),
                "slot": Icon("edit", size=ICON_BUTTON_SIZE_CLASS),
                "color": "gray",
            },
            {
                "href": action_url("games:remove_playthrough", run.pk, origin=origin),
                "slot": Icon("delete", size=ICON_BUTTON_SIZE_CLASS),
                "color": "red",
            },
        ]
    )


def _act_member(
    run: Playthrough, origin: OriginUrl | None, csrf_token: str
) -> ButtonGroupMember:
    """Start, complete, or nothing left to state.

    An empty member renders nothing: ButtonGroup skips a
    dict with no slot.
    """
    if stated_start(run) is None:
        return {
            "slot": Icon("play", size=ICON_BUTTON_SIZE_CLASS),
            "title": "Started today",
            "color": "green",
            "method": "post",
            "action": action_url("games:start_playthrough", run.pk, origin=origin),
            "csrf_token": csrf_token,
        }
    if stated_completion(run) is None:
        return {
            "slot": Icon("finish", size=ICON_BUTTON_SIZE_CLASS),
            "title": "Completed today",
            "color": "green",
            "method": "post",
            "action": action_url("games:complete_playthrough", run.pk, origin=origin),
            "csrf_token": csrf_token,
        }
    return {}
```

Add `ButtonGroupMember` to the `common.components` import at the top of the
module.

- [ ] **Step 4: Run them and watch them pass**

Run: `make test ARGS="tests/test_playthrough_rows.py -x"`

Expected: all pass.

- [ ] **Step 5: Give both pages a token**

In `games/views/game.py`, add `csrf_token: str` as the last parameter of
`_playthroughs_section` and pass it into `playthrough_tabledata`. In
`view_game`, import `get_token` from `django.middleware.csrf` (if it is not
imported already) and pass `get_token(request)` in the
`_playthroughs_section(...)` call.

In `games/views/playthrough.py`, `list_playthroughs` does the same: import
`get_token` and pass `csrf_token=get_token(request)` to `playthrough_tabledata`.

- [ ] **Step 6: Assert the button reaches the page**

Append to `tests/test_game_detail_playthroughs.py`:

```python
def test_the_section_offers_the_act_the_run_allows(logged_in, game):
    """A tracked game's run states no act yet."""
    run = Playthrough.objects.get(player_game__game=game)

    body = section(logged_in, game)

    assert f"/playthrough/{run.pk}/start" in body
    assert "csrfmiddlewaretoken" in body
```

- [ ] **Step 7: Run both files and watch them pass**

Run: `make test ARGS="tests/test_playthrough_rows.py tests/test_game_detail_playthroughs.py -x"`

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add games/views/playthrough_rows.py games/views/game.py \
        games/views/playthrough.py tests/test_playthrough_rows.py \
        tests/test_game_detail_playthroughs.py
git commit -m "Offer each run the act its state allows"
```

---

### Task 6: Replay, and the gate

**Files:**
- Test: `tests/test_playthrough_companion_status.py`
- Modify: whatever `make check` reports

**Interfaces:**
- Consumes: everything Tasks 1-5 produced.
- Produces: nothing new. This task proves the pair replays and leaves the tree
  green.

The correlated pair is two events in one stream, and replay must leave the same
two rows whichever order the projectors see them in. `PlayerGames` and
`Playthroughs` share the `CURRENT_STATE` family, where order within a family is
registration order and does not matter — one event type has one owner. This test
states that as a fact rather than a belief.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_playthrough_companion_status.py`:

```python
from games.events.rebuild import RebuildMode, rebuild_projections


def test_the_pair_replays_to_the_same_rows(logged_in, owned_library, game):
    logged_in.post(
        reverse("games:add_playthrough"),
        {
            "game": str(game.pk),
            "started": "2026-01-02",
            "ended": "2026-02-03",
            "note": "12h",
            "also_mark_completed": "on",
        },
    )
    before = (
        status_of(owned_library),
        Playthrough.objects.get(player_game__game=game).completed_upper,
    )

    rebuild_projections(owned_library, mode=RebuildMode.REBUILD)

    after = (
        status_of(owned_library),
        Playthrough.objects.get(player_game__game=game).completed_upper,
    )
    assert after == before
```

`rebuild_projections` replays the whole stream into shadow tables and swaps
them in. `tests/test_playthrough_projection.py:322` is the shipped example of
the same call.

- [ ] **Step 2: Run it and watch it pass**

Run: `make test ARGS="tests/test_playthrough_companion_status.py -x"`

Expected: all pass. A failure here is a real one — it says a correlated pair
does not survive replay.

- [ ] **Step 3: Sweep for the old field name**

Run: `grep -rn "mark_as_finished" --include=*.py --include=*.ts --include=*.md .`

Expected: nothing outside `docs/superpowers/`, which records the words the
codebase gave up and is held to no later rule. Fix anything else the grep names.

- [ ] **Step 4: Run the gate**

Run: `make check`

Expected: green — lint, format-check, mypy, vale, ts-check, vitest, and the
whole pytest suite with `e2e/`. `make vale` reads the comments this plan added:
none of them says `fold`, `seam`, `tombstone`, `archive`, `heal`, or `delete`
next to a record.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "Prove the correlated pair survives replay"
```

---

## Self-Review

**Spec coverage.** Every row of the spec's Verification table has a test:

| Spec row | Test |
|---|---|
| a first start on an Unplayed game states Played | Task 3, `test_a_first_start_states_played` |
| a start on a Completed game states nothing | Task 2, `test_a_completed_game_renders_no_played_box` and `test_a_posted_played_box_is_dropped_for_a_completed_game`; Task 3, `test_a_start_on_a_completed_game_states_nothing` |
| a completion states Completed | Task 3, `test_a_completion_states_completed`; Task 4, `test_completing_a_run_states_today_and_completed` |
| a completion on a game already Completed | `RecordPlayerGameFacts` answers `Unchanged`; Task 4, `test_a_start_on_a_completed_game_leaves_the_status` covers the neighbouring case |
| the boxes act only on a stated act | Task 3, `test_a_note_only_edit_states_no_status` |
| the row actions | Task 5, three tests over the three states |
| the pair shares a correlation | Task 3, `test_the_pair_shares_one_correlation` |
| a refused status leaves the run | every companion answer is discarded on purpose, which the helper docstrings state; `record_facts_for_request` toasts |
| replay | Task 6 |
| routes | Task 4, `test_neither_act_answers_a_get` plus `tests/test_returns_classification.py` |

**One deviation from the spec, recorded.** The spec classified the two routes as
`IN_PLACE`; they redirect to their origin, which is `ORIGIN_AWARE` in this
codebase's own words. The spec has been corrected to match.

**One reading the spec left open.** The spec names Game detail as the home of
the row actions. `playthrough_tabledata` is one builder shared with the
Playthroughs list page, so both pages get them. Splitting the builder to keep
the list page bare would cost more than it buys.
