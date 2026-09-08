# Playthrough API read cutover — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/api/playthrough` reads and writes the `Playthrough` projection, keyed
by the run, stating the temporal grammar, with no reference to `games_playevent`.

**Architecture:** Five routes on one Ninja router. The three keyed routes resolve
a `Playthrough` with `owned_or_404`: the reads over `library_runs(library)`, the
writes over the library's runs whatever the mark, so `RemovePlaythrough` keeps
answering `Unchanged` for a repeat. One output schema resolves each endpoint to
its canonical string beside the two generated bound columns and the act marker.
The two request bodies take the same grammar through a pydantic
`BeforeValidator`, which `RunDraft` now carries end to end.

**Tech Stack:** Django 6, django-ninja, pydantic 2, pytest, Python 3.14.

**Spec:** `docs/superpowers/specs/2026-09-08-issue-1015-playthrough-api-read-cutover-design.md`

## Global Constraints

- Run everything through `make`. Focused run: `make test ARGS="tests/test_x.py -k name"`.
  Never `uv run pytest` directly.
- The gate is a full green `make check`, e2e included. `make check-fast` is for
  iterating only.
- Never write a `GeneratedField`: `started_lower`, `started_upper`,
  `completed_lower`, `completed_upper`, `days_to_finish` on `PlayEvent`.
- Never `instance.delete()` on a domain row; `games/removal.py` owns removal.
  Removing a *file* from the repository is not that.
- A command is dispatched outside a transaction. A test that POSTs through a
  dispatching view needs `@pytest.mark.django_db(transaction=True)`.
- Vocabulary is enforced by `make vale` over docs and comments: the projector
  *replays*, the row it writes is a *projection*, a user act *removes*, and
  `fold`, `tombstone`, `archive`, `delete` and `heal` are refused in the domain
  sense.
- Comments and docstrings in this codebase are terse. Write them normally now;
  the docs sweep trims them to seven words afterwards.
- Identifiers use complete words: `element` not `el`, `value` not `v`.

---

### Task 1: The API keys on the run and serves the projection

**Files:**
- Modify: `games/api.py:104-158` (schemas), `:224-302` (the five routes), `:41-66` (imports)
- Test: `tests/test_playthrough_api_reads.py` (create)
- Test: `tests/test_playthrough_api_writes.py:56-184` (re-key onto the run)
- Test: `tests/test_library_api_isolation.py:303-329`
- Test: `tests/test_session_playhistory_runtime_identity.py:120-140`
- Test: `tests/test_removal.py:70-95`
- Test: `tests/test_library_reconciliation.py:280-292`
- Test: `tests/test_catalog_uuid_primary_key.py:370-410`

**Interfaces:**
- Consumes: `library_runs(library)` from `games/reads/playthrough_runs.py`;
  `days_to_finish(run)` from `games/reads/playthrough_endpoints.py`;
  `owned_or_404` from `games/ownership.py`.
- Produces: `PlaythroughOut` with the fields listed below; `_readable_runs(library)`
  and `_writable_runs(library)` in `games/api.py`.

- [ ] **Step 1: Write the failing read tests**

Create `tests/test_playthrough_api_reads.py`:

```python
"""#1015: the API reads the projection."""

from datetime import date

import pytest

from games.models import Game, Playthrough
from games.reads.playthrough_runs import live_ordinary_runs, tracked_game
from games.writes.playergame import new_correlation_id, track_game
from timetracker.temporal import TemporalValue


@pytest.fixture
def user(owned_user):
    return owned_user


@pytest.fixture
def game(owned_library):
    return Game.objects.create(library=owned_library, name="Outer Wilds")


def only_run(user, game) -> Playthrough:
    """The run TrackGame states for a tracked game."""
    return live_ordinary_runs(user.library, tracked_game(user.library, game))[0]


@pytest.mark.django_db(transaction=True)
def test_the_list_states_the_run_key_and_the_game(client, user, game):
    track_game(user, game, correlation_id=new_correlation_id())
    run = only_run(user, game)
    client.force_login(user)

    body = client.get("/api/playthrough/").json()

    assert [row["id"] for row in body] == [str(run.pk)]
    assert body[0]["game"] == "Outer Wilds"
    assert body[0]["game_id"] == str(game.pk)


@pytest.mark.django_db(transaction=True)
def test_an_act_that_never_happened_states_a_null_marker(client, user, game):
    track_game(user, game, correlation_id=new_correlation_id())
    run = only_run(user, game)
    client.force_login(user)

    body = client.get(f"/api/playthrough/{run.pk}").json()

    assert body["start_recorded_at"] is None
    assert body["started"] is None
    assert body["started_lower"] is None
    assert body["completion_recorded_at"] is None
    assert body["days_to_finish"] is None


@pytest.mark.django_db(transaction=True)
def test_a_month_states_its_canonical_value_and_its_two_bounds(client, user, game):
    track_game(user, game, correlation_id=new_correlation_id())
    run = only_run(user, game)
    Playthrough.objects.filter(pk=run.pk).update(
        started=TemporalValue.from_month(2026, 3),
        completed=TemporalValue.from_day(date(2026, 4, 2)),
    )
    client.force_login(user)

    body = client.get(f"/api/playthrough/{run.pk}").json()

    assert body["started"] == "2026-03"
    assert body["started_lower"] == "2026-03-01"
    assert body["started_upper"] == "2026-03-31"
    assert body["completed"] == "2026-04-02"
    assert body["days_to_finish"] == 33


@pytest.mark.django_db(transaction=True)
def test_a_removed_run_leaves_the_list_and_answers_404(client, user, game):
    track_game(user, game, correlation_id=new_correlation_id())
    run = only_run(user, game)
    Playthrough.objects.filter(pk=run.pk).update(removed_at="2026-05-01T00:00:00Z")
    client.force_login(user)

    assert client.get("/api/playthrough/").json() == []
    assert client.get(f"/api/playthrough/{run.pk}").status_code == 404
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `make test ARGS="tests/test_playthrough_api_reads.py -x"`
Expected: FAIL. The list answers legacy rows, so `body[0]["game_id"]` raises
`KeyError` and the id does not match the run.

- [ ] **Step 3: Replace the output schema**

In `games/api.py`, drop `PlaythroughOut`'s legacy body and write:

```python
class PlaythroughOut(Schema):
    """One run, as the projection states it."""

    id: UUIDv7
    game: str = Field(..., alias="player_game.game.name")
    game_id: UUIDv7 = Field(..., alias="player_game.game.id")
    name: str
    note: str
    started: str | None
    started_lower: date | None
    started_upper: date | None
    start_recorded_at: datetime | None
    start_note: str
    completed: str | None
    completed_lower: date | None
    completed_upper: date | None
    completion_recorded_at: datetime | None
    completion_note: str
    days_to_finish: int | None
    created_at: datetime

    @staticmethod
    def resolve_started(run: Playthrough) -> str | None:
        return run.started.serialize()

    @staticmethod
    def resolve_completed(run: Playthrough) -> str | None:
        return run.completed.serialize()

    @staticmethod
    def resolve_days_to_finish(run: Playthrough) -> int | None:
        return days_to_finish(run)
```

`TemporalValue.serialize()` answers `None` for a value that states nothing, so
each resolver needs no null branch. Import `days_to_finish` from
`games.reads.playthrough_endpoints` and `Playthrough` from `games.models`.

- [ ] **Step 4: Give the router its two scopes**

```python
def _readable_runs(library: UserLibrary) -> QuerySet[Playthrough]:
    """What the two GET routes answer about."""
    return library_runs(library).select_related("player_game__game")


def _writable_runs(library: UserLibrary) -> QuerySet[Playthrough]:
    """What PATCH and DELETE find.

    Wider than the reads on purpose: RemovePlaythrough answers
    Unchanged for a run already removed, and a scope that hid it
    would answer 404 to a repeat instead.
    """
    return Playthrough.objects.select_related("player_game__game").filter(
        library=library, player_game__library=library
    )
```

Import `library_runs` from `games.reads.playthrough_runs`, `UserLibrary` and
`Playthrough` from `games.models`, and `QuerySet` from `django.db.models`.

- [ ] **Step 5: Re-key the five routes**

`GET /` answers `_readable_runs(library).order_by("-created_at", "id")`.
`GET /{playthrough_id}`, `PATCH` and `DELETE` each resolve with
`owned_or_404(_readable_runs(library) | _writable_runs(library), library, id=playthrough_id)`
— reads use the readable scope, writes the writable one. The PATCH and DELETE
bodies stop calling `run_for_row`, stop raising the `converted.sentence`
refusal, and pass the resolved run straight to `restate_run` / `remove_run`.
`PATCH` keeps `restatable_days` and `_RICHER_THAN_A_DAY` for now; Task 3 takes
both.

- [ ] **Step 6: Run the read tests**

Run: `make test ARGS="tests/test_playthrough_api_reads.py -x"`
Expected: PASS.

- [ ] **Step 7: Re-key the write tests onto the run**

In `tests/test_playthrough_api_writes.py`, every `f"/api/playthrough/{row.pk}"`
becomes `f"/api/playthrough/{run.pk}"`. Two tests change meaning:

- `test_a_row_with_no_run_answers_409` (`:177-184`) no longer has a subject: a
  legacy row id names nothing on the API. Replace it with
  `test_an_unconverted_row_id_answers_404`, which creates a `PlayEvent`, skips
  the conversion, and asserts `client.delete(f"/api/playthrough/{row.pk}")`
  answers 404.
- Add `test_a_second_delete_answers_204`, which deletes one of a game's two
  runs twice and asserts 204 both times.

- [ ] **Step 8: Fix the other callers that address a legacy row**

- `tests/test_session_playhistory_runtime_identity.py:120-140` — the
  `playthrough_world` fixture's `own_playevent` becomes the run converted from
  it. Read it with `live_ordinary_runs`, and assert
  `response.json()["id"] == str(run.pk)`.
- `tests/test_removal.py:70-95` — `client.delete(f"/api/playthrough/{run.pk}")`.
  The assertion that the legacy row keeps its own mark stays.
- `tests/test_library_reconciliation.py:280-292` — the listed ids are the runs'.
- `tests/test_catalog_uuid_primary_key.py:370-410` — read what it asserts and
  key it on the run.
- `tests/test_library_api_isolation.py:303-329` —
  `test_playevent_crud_is_library_scoped` currently passes vacuously, because
  `foreign` is a `PlayEvent` whose id names nothing. Convert library B's rows
  and use library B's *run*, so the three 404s prove scoping. Rename it
  `test_playthrough_crud_is_library_scoped`, and count `Playthrough` rather
  than `PlayEvent` for the create assertions.

- [ ] **Step 9: Run every affected module**

Run: `make test ARGS="tests/test_playthrough_api_reads.py tests/test_playthrough_api_writes.py tests/test_library_api_isolation.py tests/test_session_playhistory_runtime_identity.py tests/test_removal.py tests/test_library_reconciliation.py tests/test_catalog_uuid_primary_key.py"`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add games/api.py tests/
git commit -m "Key the playthrough API on the run and read the projection"
```

---

### Task 2: The list pages

**Files:**
- Modify: `games/api.py` (`list_playthroughs`)
- Test: `tests/test_playthrough_api_reads.py`

**Interfaces:**
- Consumes: `_readable_runs` from Task 1.
- Produces: `GET /api/playthrough/?limit=&offset=`.

- [ ] **Step 1: Write the failing paging tests**

Append to `tests/test_playthrough_api_reads.py`:

```python
@pytest.mark.django_db(transaction=True)
def test_the_list_pages_a_stable_order(client, user, owned_library):
    for index in range(3):
        game = Game.objects.create(library=owned_library, name=f"Game {index}")
        track_game(user, game, correlation_id=new_correlation_id())
    client.force_login(user)

    every_id = [row["id"] for row in client.get("/api/playthrough/").json()]
    first_page = client.get("/api/playthrough/?limit=2").json()
    second_page = client.get("/api/playthrough/?limit=2&offset=2").json()

    assert len(every_id) == 3
    assert [row["id"] for row in first_page] == every_id[:2]
    assert [row["id"] for row in second_page] == every_id[2:]


@pytest.mark.django_db(transaction=True)
def test_limit_zero_is_unbounded_and_a_negative_value_is_refused(
    client, user, owned_library
):
    for index in range(3):
        game = Game.objects.create(library=owned_library, name=f"Game {index}")
        track_game(user, game, correlation_id=new_correlation_id())
    client.force_login(user)

    assert len(client.get("/api/playthrough/?limit=0").json()) == 3
    assert client.get("/api/playthrough/?limit=-1").status_code == 422
    assert client.get("/api/playthrough/?offset=-1").status_code == 422
```

- [ ] **Step 2: Run them and watch them fail**

Run: `make test ARGS="tests/test_playthrough_api_reads.py -k page or limit"`
Expected: FAIL — `limit` is not a parameter, so `-1` answers 200.

- [ ] **Step 3: Take the two parameters**

```python
@playthrough_router.get("/", response=list[PlaythroughOut])
def list_playthroughs(
    request,
    limit: int = Query(100, ge=0),
    offset: int = Query(0, ge=0),
):
    """The library's live ordinary runs, newest first.

    `limit=0` is unbounded, as on the presets route. The order
    ends on the key, so an offset reads a stable page.
    """
    library = cast(User, request.user).library
    runs = _readable_runs(library).order_by("-created_at", "id")[offset:]
    return runs if limit == 0 else runs[:limit]
```

Import `Query` from `ninja`.

- [ ] **Step 4: Run the tests**

Run: `make test ARGS="tests/test_playthrough_api_reads.py"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add games/api.py tests/test_playthrough_api_reads.py
git commit -m "Page the playthrough list route"
```

---

### Task 3: `RunDraft` carries a temporal value

**Files:**
- Modify: `games/writes/playthrough.py:38-53` (`RunDraft`, `_stated_day`), `:180-300`
- Modify: `games/views/playthrough.py:260-266` (`_draft_from`)
- Modify: `games/api.py` (`create_playthrough`, `partial_update_playthrough`)
- Test: `tests/test_playthrough_writes.py` (every `RunDraft(...)` construction)

**Interfaces:**
- Consumes: `TemporalValue.from_day` from `timetracker/temporal.py`.
- Produces: `RunDraft(started: TemporalValue | None, completed: TemporalValue | None, note: str)`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_playthrough_writes.py`:

```python
@pytest.mark.django_db(transaction=True)
def test_a_draft_states_a_month(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Tunic")
    record_run(
        owned_user,
        game,
        RunDraft(
            started=TemporalValue.from_month(2026, 3),
            completed=None,
            note="",
        ),
        correlation_id=new_correlation_id(),
    )

    run = live_ordinary_runs(owned_library, tracked_game(owned_library, game)).get()
    assert run.started == TemporalValue.from_month(2026, 3)
```

- [ ] **Step 2: Run it and watch it fail**

Run: `make test ARGS="tests/test_playthrough_writes.py -k month -x"`
Expected: FAIL. `RunDraft` has no `completed`, and `_stated_day` calls
`TemporalValue.from_day` on a `TemporalValue`.

- [ ] **Step 3: Widen the draft**

```python
@dataclass(frozen=True, slots=True)
class RunDraft:
    """What a person stated about one run.

    Temporal values: a day, a month, a range, or none.
    The act rule turns each into an act, with no day
    where none was given.
    """

    started: TemporalValue | None
    completed: TemporalValue | None
    note: str
```

Take `_stated_day` out. In `_restate`, `started = draft.started` and
`completed = draft.completed`. In `_record_once`, state
`ActStatement(draft.started)` and `ActStatement(draft.completed)`. The
`from datetime import date` import goes if nothing else in the module uses it.

- [ ] **Step 4: Convert at the two day-shaped callers**

```python
def _draft_from(form: PlaythroughForm) -> RunDraft:
    """The run the form states, as temporal values.

    The two fields are optional, and from_day refuses None.
    """
    return RunDraft(
        started=_stated_day(form.cleaned_data["started"]),
        completed=_stated_day(form.cleaned_data["ended"]),
        note=form.cleaned_data["note"],
    )
```

and beside it in `games/views/playthrough.py`:

```python
def _stated_day(day: date | None) -> TemporalValue | None:
    """The day at day precision, or none."""
    return None if day is None else TemporalValue.from_day(day)
```

In `games/api.py`, both routes wrap their payload dates the same way for now;
Task 4 makes the payload temporal and the wrapping goes.

- [ ] **Step 5: Update every RunDraft construction in the tests**

`tests/test_playthrough_writes.py` builds `RunDraft` with plain dates in about
eighteen places. Each `started=date(...)` becomes
`started=TemporalValue.from_day(date(...))`, and each `ended=` becomes
`completed=`. Do not leave a bare `date`: `stated_date` raises
`AttributeError` on one rather than refusing it, so a missed call fails with a
confusing traceback.

- [ ] **Step 6: Run the write tests and the view tests**

Run: `make test ARGS="tests/test_playthrough_writes.py tests/test_playthrough_view_cutover.py tests/test_playthrough_api_writes.py"`
Expected: PASS.

- [ ] **Step 7: Type check**

Run: `make typecheck`
Expected: clean. A caller that still passes a `date` fails here.

- [ ] **Step 8: Commit**

```bash
git add games/writes/playthrough.py games/views/playthrough.py games/api.py tests/
git commit -m "Carry a temporal value through RunDraft"
```

---

### Task 4: The request bodies take the grammar

**Files:**
- Modify: `games/api.py:104-143` (schemas, `_RICHER_THAN_A_DAY`), `:230-286` (POST, PATCH)
- Test: `tests/test_playthrough_api_writes.py`

**Interfaces:**
- Consumes: `RunDraft` from Task 3; `TemporalValue`, `TemporalValueParseError`.
- Produces: `StatedTemporal`, an annotated pydantic type for a canonical value;
  `PlaythroughIn(game_id, started, completed, note)`;
  `UpdatePlaythroughIn(started, completed, note)`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_playthrough_api_writes.py`:

```python
@pytest.mark.django_db(transaction=True)
def test_a_patch_states_a_month(client, user, game):
    track_game(user, game, correlation_id=new_correlation_id())
    run = live_ordinary_runs(user.library, tracked_game(user.library, game)).get()
    client.force_login(user)

    response = client.patch(
        f"/api/playthrough/{run.pk}",
        {"started": "2026-03"},
        content_type="application/json",
    )

    assert response.status_code == 204
    run.refresh_from_db()
    assert run.started == TemporalValue.from_month(2026, 3)


@pytest.mark.django_db(transaction=True)
def test_a_patch_that_names_one_key_keeps_a_richer_value(client, user, game):
    track_game(user, game, correlation_id=new_correlation_id())
    run = live_ordinary_runs(user.library, tracked_game(user.library, game)).get()
    Playthrough.objects.filter(pk=run.pk).update(
        started=TemporalValue.from_month(2026, 3)
    )
    client.force_login(user)

    response = client.patch(
        f"/api/playthrough/{run.pk}",
        {"note": "second"},
        content_type="application/json",
    )

    assert response.status_code == 204
    run.refresh_from_db()
    assert run.note == "second"
    assert run.started == TemporalValue.from_month(2026, 3)


@pytest.mark.django_db(transaction=True)
def test_a_spelling_the_grammar_refuses_answers_422(client, user, game):
    track_game(user, game, correlation_id=new_correlation_id())
    run = live_ordinary_runs(user.library, tracked_game(user.library, game)).get()
    client.force_login(user)

    response = client.patch(
        f"/api/playthrough/{run.pk}",
        {"started": "2020s"},
        content_type="application/json",
    )

    assert response.status_code == 422
```

`test_a_run_stating_more_than_a_day_answers_409` (`:132-156`) states the
opposite of the second test now. Take it out in this task, and say why in the
commit: the API states every value a run can hold.

- [ ] **Step 2: Run them and watch them fail**

Run: `make test ARGS="tests/test_playthrough_api_writes.py -k month or grammar or one_key"`
Expected: FAIL — `"2026-03"` is not a `date`, so the schema answers 422 for the
first two, and the third passes for the wrong reason.

- [ ] **Step 3: Add the annotated type**

```python
def _stated_temporal(value: object) -> object:
    """Build the value a canonical string names.

    TemporalValueParseError is a ValueError, so pydantic
    answers 422 rather than a traceback.
    """
    if value is None or isinstance(value, TemporalValue):
        return value
    if isinstance(value, str):
        return TemporalValue(value)
    raise ValueError("A date is stated as a string.")
```

and beside it:

```text
#: A canonical temporal value on the wire: 2026-03, 202X, 2026-03-04~.
type StatedTemporal = Annotated[
    TemporalValue | None,
    BeforeValidator(_stated_temporal),
    PlainSerializer(lambda value: None if value is None else value.serialize()),
]
```

Import `Annotated` from `typing`, `BeforeValidator` and `PlainSerializer` from
`pydantic`, `TemporalValue` from `timetracker.temporal`.

- [ ] **Step 4: Restate the two request schemas**

```python
class PlaythroughIn(Schema):
    game_id: UUIDv7
    started: StatedTemporal = None
    completed: StatedTemporal = None
    note: str = ""


class UpdatePlaythroughIn(Schema):
    started: StatedTemporal = None
    completed: StatedTemporal = None
    note: str = ""
```

`days_to_finish` goes: the legacy column was generated, so the value was read
and dropped.

- [ ] **Step 5: Seed the PATCH off the run**

The handler keeps `exclude_unset`, and fills each absent key from the run
itself rather than from `restatable_days`:

```text
stated = payload.dict(exclude_unset=True)
restate_run(
    cast("User", request.user),
    run,
    RunDraft(
        started=stated.get("started", run.started),
        completed=stated.get("completed", run.completed),
        note=stated.get("note", run.note),
    ),
    correlation_id=new_correlation_id(),
)
```

`_RICHER_THAN_A_DAY`, the `restatable_days` import and the `days is None`
branch all go from `games/api.py`. `games/views/playthrough.py` keeps its own
`RICHER_THAN_A_DAY` and its `restatable_days` call: the form is still
day-shaped.

`create_playthrough` passes `payload.started` and `payload.completed` into
`RunDraft` with no conversion.

- [ ] **Step 6: Run the write tests**

Run: `make test ARGS="tests/test_playthrough_api_writes.py"`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add games/api.py tests/test_playthrough_api_writes.py
git commit -m "State the temporal grammar in the playthrough request bodies"
```

---

### Task 5: The bridge and the legacy schema come out

**Files:**
- Remove: `games/reads/playthrough_provenance.py`, `tests/test_playthrough_provenance.py`
- Modify: `games/api.py` (`AutoPlayEventIn`, the `PlayEvent` import)
- Modify: `tests/test_session_playhistory_identity.py:11,221-238`
- Modify: `tests/test_playthrough_api_writes.py:187-197` (the bridge guard)
- Modify: `tests/test_removal.py`, `tests/test_removal_confirmation.py:133`,
  `tests/test_library_page_isolation.py:171-172`,
  `tests/test_playthrough_view_cutover.py:87,114,134,156,178,190`,
  `tests/test_playergame_view_cutover.py:308`
- Modify: `CLAUDE.md`, `docs/superpowers/specs/2026-09-04-playthrough-wave-design.md`

**Interfaces:**
- Consumes: `live_ordinary_runs(library, player_game)` and
  `tracked_game(library, game)` from `games/reads/playthrough_runs.py`.
- Produces: no module reads `games_playevent` from `games/api.py`.

- [ ] **Step 1: Replace every `run_for_row` call in the tests**

Seven modules import it to find the run a converted legacy row became. Each
converts one row per game, so the run is the game's only live ordinary run:

```text
run = live_ordinary_runs(library, tracked_game(library, game)).get()
```

Where a test converts two rows for one game, order them the way
`live_ordinary_runs` does — `created_at`, then the key — and index the list.
`tests/test_playthrough_view_cutover.py:178-190` is the one that needs this.

- [ ] **Step 2: Run those modules**

Run: `make test ARGS="tests/test_removal.py tests/test_removal_confirmation.py tests/test_library_page_isolation.py tests/test_playthrough_view_cutover.py tests/test_playergame_view_cutover.py tests/test_playthrough_api_writes.py"`
Expected: PASS, with the module still present.

- [ ] **Step 3: Take the module and its two tests out**

```bash
git rm games/reads/playthrough_provenance.py tests/test_playthrough_provenance.py
```

Take `test_one_module_reads_the_bridge` out of
`tests/test_playthrough_api_writes.py:187-197`: it pins the module to one
reader, and there is no module left to pin.

- [ ] **Step 4: Take the legacy schema out**

`AutoPlayEventIn` in `games/api.py:133-136` is a `ModelSchema` over `PlayEvent`
that no route names. Take it out, with
`test_uuid_is_absent_from_the_playevent_model_schema` and
`test_autoplayeventin_game_field_type_still_follows_games_primary_key` in
`tests/test_session_playhistory_identity.py:221-238` and the import on line 11.
Add one case in their place, so the module still states the fact:

```python
def test_no_model_schema_covers_the_promoted_models():
    """The two cases above asserted this through AutoPlayEventIn."""
    from ninja import ModelSchema

    covered = {
        schema.Meta.model
        for schema in vars(games.api).values()
        if isinstance(schema, type)
        and issubclass(schema, ModelSchema)
        and hasattr(schema, "Meta")
    }
    assert PlayEvent not in covered
    assert Session not in covered
```

Then take the `PlayEvent` import out of `games/api.py` if nothing else names it.

- [ ] **Step 5: Correct the two documents**

- `CLAUDE.md` — the API section says the path id is the legacy row's, which
  #771 replaces. It is the run's now. The `Playthrough` model paragraph says
  `runs_for_rows` stays for the API, which #1015 owns; that sentence goes.
- `docs/superpowers/specs/2026-09-04-playthrough-wave-design.md:266-268` — the
  #1015 boundary takes the identity and the bridge module, and #771 keeps the
  table.

- [ ] **Step 6: Run vale and the affected tests**

Run: `make vale`
Run: `make test ARGS="tests/test_session_playhistory_identity.py tests/test_playthrough_api_writes.py"`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Take the legacy-row bridge out of the playthrough API"
```

---

### Task 6: The gate

**Files:**
- Remove: `docs/superpowers/plans/2026-09-08-issue-1015-playthrough-api-read-cutover.md`

- [ ] **Step 1: Count the queries a page costs**

Add to `tests/test_playthrough_api_reads.py`:

```python
@pytest.mark.django_db(transaction=True)
def test_the_list_reads_a_constant_number_of_queries(
    client, user, owned_library, django_assert_num_queries
):
    for index in range(4):
        game = Game.objects.create(library=owned_library, name=f"Game {index}")
        track_game(user, game, correlation_id=new_correlation_id())
    client.force_login(user)

    with django_assert_num_queries(3):
        assert len(client.get("/api/playthrough/").json()) == 4
```

Run it, read the number the failure prints, and pin that number — the point is
that it does not grow with the rows, so run it again with eight games to prove
the count is unchanged before you commit.

- [ ] **Step 2: Take the plan document out**

The docs sweep drops the plan and keeps the spec. Do it before the gate, so the
gate does not run over a document that is leaving.

```bash
git rm docs/superpowers/plans/2026-09-08-issue-1015-playthrough-api-read-cutover.md
```

- [ ] **Step 3: Run the full gate**

Run: `make check`
Expected: green, e2e included. Never a hand-picked subset.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "Count the queries the playthrough list costs"
```
