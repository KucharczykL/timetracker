# SES-03 — End a running Timed session: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One command, one event, one handler that state the end instant of a
Timed `PlayerSession` that has none.

**Architecture:** A new event type `library.playersession.ended` carries a
payload of its own — two keys, not the `TimingPayload` union — and its handler
`amend`s exactly two columns of the projection row. A new `EndSession` command
resolves this library's session, refuses every state that cannot take an end,
and appends the event. Nothing calls the command when this merges; #702 owns
the surfaces.

**Tech Stack:** Python 3.14, Django 6, pydantic TypedDict payloads,
PostgreSQL 18, pytest + pytest-xdist.

**Spec:** `docs/superpowers/specs/2026-09-13-issue-691-session-end-design.md`

## Global Constraints

- **Run everything through `make`.** No `direnv exec .`, no bare `uv run` /
  `pytest` / `pnpm`. Focused runs: `make test ARGS="tests/test_x.py -k name"`.
- **Iterate with `make check-fast`; the gate is full `make check`** (lint,
  format-check, mypy, vale, ts-check, vitest, and the entire pytest suite
  including `e2e/`). Never gate on a hand-picked subset.
- **Python 3.14 only.** `except A, B:` (PEP 758) is valid here; a `SyntaxError`
  in one means the wrong interpreter, not broken source.
- **Two sentences per refusal.** `raise CommandRejected(message, sentence=…)`.
  The positional message reaches a log and may name an id; `sentence` is the
  only thing a person sees. A raise site with no `sentence` is a defect.
- **One act, one verb.** The event type, its command and its projection column
  share one verb: `end` / `EndSession` / `library.playersession.ended` /
  `ended_at`.
- **`make vale` is part of `make check`.** Refused words in docs and comments
  fail the build — notably, a projector *replays* events and leaves a
  *projection*; never `fold`. See `docs/vocabulary.md`.
- **Complete words in identifiers.** `element` not `el`, `event` not `e`.
- **No comment may reference an issue or PR number** (forward `TODO`s
  excepted). Explain intent, not history.
- **Never write a `GeneratedField`.** `effective_day`, `effective_duration`
  and `sort_instant` are computed by PostgreSQL.
- **No dispatch inside a transaction.** A test that POSTs or dispatches needs
  `@pytest.mark.django_db(transaction=True)`.
- **Branch first.** Do not implement on `main`. Rebase onto `origin/main`
  before the first edit.

---

## File Structure

| File | Responsibility in this change |
|---|---|
| `games/events/playersession.py` | Add `PlayerSessionEndedPayload`, the `PLAYERSESSION_ENDED` spec, its registration, and the `playersession_ended()` builder. |
| `games/projectors/playersession.py` | Add the `_ended` handler and its entry in `handles`. |
| `games/events/dispatch.py` | Add one `CommandName` member. |
| `games/commands/playersession.py` | Lift `_check_aware` to module level; add `_live_session`, `_timed_start`, and `EndSession`. |
| `tests/test_playersession_events.py` | Payload round-trip and refusals, the builder's day, the encoding-coupling pin. |
| `tests/test_playersession_projection.py` | The handler amends two columns; replay and rebuild reproduce the ended row. |
| `tests/test_playersession_command.py` | The happy path, every refusal, the normalizations, `Unchanged`. |

Task order is event → handler → command, because each task's tests only need
what the tasks before it produced: the handler's tests append events directly
(no command), and the command's tests read the row the handler wrote.

---

### Task 1: The `library.playersession.ended` event

**Files:**
- Modify: `games/events/playersession.py`
- Test: `tests/test_playersession_events.py`

**Interfaces:**
- Consumes: `InstantText`, `instant_text`, `day_text`, `STRICT_SCHEMA`,
  `EventSpec`, `DEFAULT_EVENT_TYPES`, `NewEvent`, `TemporalValue` — all
  already imported or importable in that module.
- Produces:
  - `PLAYERSESSION_ENDED: EventSpec[PlayerSessionEndedPayload]` —
    `event_type="library.playersession.ended"`,
    `aggregate_type="playersession"`.
  - `playersession_ended(session_id: uuid.UUID, *, ended_at: datetime,
    ended_at_zone: str | None, day_zone: str) -> NewEvent`.
  - `PlayerSessionEndedPayload` — a `TypedDict` with exactly
    `ended_at: InstantText` and `ended_at_zone: str | None`.

- [ ] **Step 1: Create the branch**

```bash
git fetch origin && git switch -c feat/issue-691-session-end origin/main
```

- [ ] **Step 2: Write the failing payload and builder tests**

Append to `tests/test_playersession_events.py`. Add
`from games.events.idempotency import _canonical_datetime` and extend the
existing `games.events.playersession` import with `PLAYERSESSION_ENDED` and
`playersession_ended`. `uuid`, `UTC`, `datetime`, `ZoneInfo`, `pytest`,
`DEFAULT_EVENT_TYPES`, `PayloadInvalid`, `instant_text`,
`playersession_created` and `RUN` are already imported there.

```python
# --- The end of a running session --------------------------------------------

AN_END = {"ended_at": "2026-01-02T01:30:00+00:00", "ended_at_zone": "Europe/Prague"}


def validated_end(payload: dict) -> dict:
    return DEFAULT_EVENT_TYPES.validate(PLAYERSESSION_ENDED.event_type, payload)


def test_the_end_event_type_is_spelled_once_and_forever():
    assert PLAYERSESSION_ENDED.event_type == "library.playersession.ended"
    assert PLAYERSESSION_ENDED.aggregate_type == "playersession"


def test_an_end_payload_round_trips():
    assert validated_end(AN_END) == AN_END


def test_an_end_may_state_no_zone():
    payload = AN_END | {"ended_at_zone": None}

    assert validated_end(payload) == payload


def test_an_end_payload_refuses_a_second_spelling_of_the_day_zone():
    with pytest.raises(PayloadInvalid):
        validated_end(AN_END | {"day_zone": "Europe/Prague"})


def test_an_end_payload_refuses_a_non_canonical_instant():
    with pytest.raises(PayloadInvalid):
        validated_end(AN_END | {"ended_at": "2026-01-02T01:30:00Z"})


def test_an_end_payload_refuses_a_missing_instant():
    with pytest.raises(PayloadInvalid):
        validated_end({"ended_at_zone": None})


def test_an_end_names_no_references():
    fields = DEFAULT_EVENT_TYPES.reference_fields_for(PLAYERSESSION_ENDED.event_type)

    assert fields == {}


def test_an_end_is_about_the_session_the_caller_names():
    session_id = uuid.uuid7()

    event = playersession_ended(
        session_id,
        ended_at=datetime(2026, 1, 1, 23, 30, tzinfo=UTC),
        ended_at_zone=None,
        day_zone="Europe/Prague",
    )

    assert event.aggregate_id == session_id


def test_an_end_takes_the_day_its_zone_reads():
    event = playersession_ended(
        uuid.uuid7(),
        ended_at=datetime(2026, 1, 1, 23, 30, tzinfo=UTC),
        ended_at_zone=None,
        day_zone="Europe/Prague",
    )

    #: Half past midnight in Prague.
    assert event.effective_time.canonical == "2026-01-02"


def test_an_end_may_land_on_a_later_day_than_the_creation_did():
    """The event dates the act; the row dates the session.

    A reader of the trail may not assume one session's events all
    carry one day.
    """
    session_id = uuid.uuid7()

    created = playersession_created(
        RUN,
        timing={
            "mode": "timed",
            "started_at": "2026-01-01T22:00:00+00:00",
            "started_at_zone": None,
            "ended_at": None,
            "ended_at_zone": None,
            "day_zone": "Europe/Prague",
        },
        device=None,
        release=None,
        note="",
        emulated=False,
        session_id=session_id,
    )
    ended = playersession_ended(
        session_id,
        ended_at=datetime(2026, 1, 2, 1, 0, tzinfo=UTC),
        ended_at_zone=None,
        day_zone="Europe/Prague",
    )

    assert created.effective_time.canonical == "2026-01-01"
    assert ended.effective_time.canonical == "2026-01-02"


def test_the_built_end_validates():
    event = playersession_ended(
        uuid.uuid7(),
        ended_at=datetime(2026, 1, 2, 1, 30, tzinfo=UTC),
        ended_at_zone="Europe/Prague",
        day_zone="Europe/Prague",
    )

    assert validated_end(event.payload) == event.payload


def test_the_payload_and_the_fingerprint_spell_an_instant_alike():
    """An end is safe to fingerprint only because these two agree.

    They are independently written expressions. Truncate either and
    every honest retry of one statement answers a conflict, with
    nothing else failing.
    """
    stated = datetime(2026, 1, 1, 23, 30, 15, 123456, tzinfo=ZoneInfo("Asia/Tokyo"))

    assert instant_text(stated) == _canonical_datetime(stated)
```

- [ ] **Step 3: Run the tests to verify they fail**

```bash
make test ARGS="tests/test_playersession_events.py -k end"
```

Expected: FAIL — `ImportError: cannot import name 'PLAYERSESSION_ENDED'`.

- [ ] **Step 4: Add the payload, the spec and the builder**

In `games/events/playersession.py`, append after the `playersession_created`
function. Nothing above it changes.

```python
@with_config(STRICT_SCHEMA)
class PlayerSessionEndedPayload(TypedDict):
    """The end a running session was given.

    A payload of its own rather than `TimingPayload`: that union
    states a whole mode and serves whole statements, while an end
    states two columns and leaves the other six as the creation
    left them.

    `day_zone` is absent on purpose. The row already holds it and
    the act does not restate it -- under `extra="forbid"` a key is
    a fact somebody may state, and a second spelling of a zone the
    row carries is one this event has no use for.
    """

    ended_at: InstantText
    ended_at_zone: str | None


PLAYERSESSION_ENDED = EventSpec(
    "library.playersession.ended",
    aggregate_type="playersession",
    payload=PlayerSessionEndedPayload,
)

DEFAULT_EVENT_TYPES.register(PLAYERSESSION_ENDED)


def playersession_ended(
    session_id: uuid.UUID,
    *,
    ended_at: datetime,
    ended_at_zone: str | None,
    day_zone: str,
) -> NewEvent:
    """The library stated when a running session ended.

    `effective_time` carries the *end's* day, read in the zone the
    library counts days in. That is not the rule `stated_day_of`
    applies: it reads the start, and so does the `effective_day`
    column generated from it. For a session crossing midnight the
    two disagree permanently, which is the point -- the event dates
    the act, the row dates the session, and neither answers the
    other's question.
    """
    return PLAYERSESSION_ENDED.new(
        aggregate_id=session_id,
        effective_time=TemporalValue.parse(
            day_text(ended_at.astimezone(ZoneInfo(day_zone)).date())
        ),
        payload={
            "ended_at": instant_text(ended_at),
            "ended_at_zone": ended_at_zone,
        },
    )
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
make test ARGS="tests/test_playersession_events.py"
```

Expected: PASS, including the tests that were already there.

- [ ] **Step 6: Type-check and lint**

```bash
make lint-fix && make typecheck && make vale
```

Expected: clean. `ZoneInfo`, `datetime` and `uuid` are already imported in
`games/events/playersession.py`; if ruff reports an unused import it means one
was removed by mistake — restore it rather than deleting the usage.

- [ ] **Step 7: Commit**

```bash
git add games/events/playersession.py tests/test_playersession_events.py
git commit -m "feat: record the end of a running session as an event"
```

---

### Task 2: The projector handler

**Files:**
- Modify: `games/projectors/playersession.py`
- Test: `tests/test_playersession_projection.py`

**Interfaces:**
- Consumes: `PLAYERSESSION_ENDED` and `playersession_ended(...)` from Task 1;
  `Projector.amend(model, identity, **columns)`, which issues a bare `UPDATE`
  over the columns it is handed and raises `ProjectionRowMissing` when no row
  matches.
- Produces: `PlayerSessions.handles` maps `PLAYERSESSION_ENDED` to `_ended`, so
  replay and rebuild carry the end.

- [ ] **Step 1: Write the failing handler tests**

Append to `tests/test_playersession_projection.py`, after the existing rebuild
tests. Extend the `games.events.playersession` import with
`playersession_ended`. Everything else used here is already imported in that
file (`uuid`, `date`, `timedelta`, `transaction`, `lock_stream`,
`DEFAULT_REGISTRY`, `replay`, `rebuild_projections`, `RebuildMode`, `dispatch`,
`TrackGame`, `PlayerSession`, `Playthrough`, `START`, `append_session`,
`a_timed_statement`).

```python
# --- The end of a running session --------------------------------------------


def append_end(
    library,
    actor,
    session,
    *,
    ended_at,
    key,
    ended_at_zone=None,
    day_zone="Europe/Prague",
):
    """Append one end event, as dispatch would."""
    with transaction.atomic():
        stream = lock_stream(library)
        return stream.append(
            [
                playersession_ended(
                    session.pk,
                    ended_at=ended_at,
                    ended_at_zone=ended_at_zone,
                    day_zone=day_zone,
                )
            ],
            actor=actor,
            correlation_id=uuid.uuid7(),
            idempotency_key=key,
        )


def test_the_end_event_has_a_current_state_handler():
    handlers = DEFAULT_REGISTRY.handlers_for("library.playersession.ended")

    assert len(handlers) == 1


@pytest.mark.django_db(transaction=True)
def test_the_end_handler_writes_two_columns_and_leaves_the_rest(
    owned_user, owned_library, run
):
    append_session(
        owned_library, owned_user, run, timing=a_timed_statement(), key="create"
    )
    session = PlayerSession.objects.get()
    untouched = (
        "timing_mode",
        "started_at",
        "started_at_zone",
        "stated_day",
        "stated_duration",
        "day_zone",
        "note",
        "emulated",
    )
    before = {column: getattr(session, column) for column in untouched}

    append_end(
        owned_library,
        owned_user,
        session,
        ended_at=START + timedelta(hours=2),
        ended_at_zone="Asia/Tokyo",
        key="end",
    )

    session.refresh_from_db()
    assert (session.ended_at, session.ended_at_zone) == (
        START + timedelta(hours=2),
        "Asia/Tokyo",
    )
    assert {column: getattr(session, column) for column in untouched} == before


@pytest.mark.django_db(transaction=True)
def test_an_ended_row_measures_the_elapsed_time(owned_user, owned_library, run):
    append_session(
        owned_library, owned_user, run, timing=a_timed_statement(), key="create"
    )
    session = PlayerSession.objects.get()

    append_end(
        owned_library,
        owned_user,
        session,
        ended_at=START + timedelta(hours=2),
        key="end",
    )

    session.refresh_from_db()
    assert session.effective_duration == timedelta(hours=2)


@pytest.mark.django_db(transaction=True)
def test_an_end_moves_neither_the_sort_instant_nor_the_day(
    owned_user, owned_library, run
):
    """The row dates the session by its start, whatever day the end lands on.

    The end here is a full day later, so the rule that reads the end
    would report 2026-01-03.
    """
    append_session(
        owned_library, owned_user, run, timing=a_timed_statement(), key="create"
    )
    session = PlayerSession.objects.get()
    before = (session.sort_instant, session.effective_day)

    append_end(
        owned_library,
        owned_user,
        session,
        ended_at=START + timedelta(days=1),
        key="end",
    )

    session.refresh_from_db()
    assert (session.sort_instant, session.effective_day) == before
    assert session.effective_day == date(2026, 1, 2)


@pytest.mark.django_db(transaction=True)
def test_an_ended_session_replays(owned_user, owned_library, run):
    append_session(
        owned_library, owned_user, run, timing=a_timed_statement(), key="create"
    )
    session = PlayerSession.objects.get()
    append_end(
        owned_library,
        owned_user,
        session,
        ended_at=START + timedelta(hours=2),
        key="end",
    )
    before = list(PlayerSession.objects.order_by("pk").values())

    PlayerSession.objects.all().delete()
    replay(owned_library)

    assert list(PlayerSession.objects.order_by("pk").values()) == before


@pytest.mark.django_db(transaction=True)
def test_a_rebuild_reproduces_an_ended_session(owned_user, owned_library, game):
    dispatch(
        TrackGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="track",
    )
    tracked_run = Playthrough.objects.get(player_game__game=game)
    append_session(
        owned_library, owned_user, tracked_run, timing=a_timed_statement(), key="create"
    )
    session = PlayerSession.objects.get()
    append_end(
        owned_library,
        owned_user,
        session,
        ended_at=START + timedelta(hours=2),
        key="end",
    )
    before = list(PlayerSession.objects.order_by("pk").values())

    report = rebuild_projections(owned_library, mode=RebuildMode.CHECK)

    assert [
        (table.only_live, table.only_rebuilt, table.differing)
        for table in report.tables
        if table.table == "games_playersession"
    ] == [(0, 0, 0)]
    assert list(PlayerSession.objects.order_by("pk").values()) == before
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
make test ARGS="tests/test_playersession_projection.py -k end"
```

Expected: FAIL — `test_the_end_event_has_a_current_state_handler` asserts
`len(handlers) == 1` and gets `0`; the others leave `ended_at` as `None`.

- [ ] **Step 3: Add the handler**

In `games/projectors/playersession.py`: extend the
`games.events.playersession` import with `PLAYERSESSION_ENDED`, add the method
to `PlayerSessions` after `_created`, and add its entry to `handles`.

```python
def _ended(self, event: RecordedEvent) -> None:
    """Two columns; the other six stay as the creation left them.

    `amend` rather than `project`: an event that changes part of
    a row knows nothing of the columns the creation wrote, and
    its refusal of a missing row is what keeps a rebuild honest.

    No mode is re-read here, and none can be: `amend` is a bare
    UPDATE over the columns it is handed. The mode was checked by
    the command under dispatch's lock, and the CHECK constraints
    hold thereafter.
    """
    payload = event.payload
    self.amend(
        PlayerSession,
        event.aggregate_id,
        ended_at=instant_from_text(payload["ended_at"]),
        ended_at_zone=payload["ended_at_zone"],
    )


handles: ClassVar[HandlerMap] = {
    PLAYERSESSION_CREATED: _created,
    PLAYERSESSION_ENDED: _ended,
}
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
make test ARGS="tests/test_playersession_projection.py"
```

Expected: PASS, including every test that was already there.

- [ ] **Step 5: Type-check and lint**

```bash
make lint-fix && make typecheck && make vale
```

Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add games/projectors/playersession.py tests/test_playersession_projection.py
git commit -m "feat: amend a session's row with the end it was given"
```

---

### Task 3: The `EndSession` command

**Files:**
- Modify: `games/events/dispatch.py:98` (one new `CommandName` member)
- Modify: `games/commands/playersession.py`
- Test: `tests/test_playersession_command.py`

**Interfaces:**
- Consumes: `playersession_ended(...)` from Task 1, projected by Task 2's
  handler; `_live_run(context, playthrough_id) -> Playthrough` (already
  imported at `games/commands/playersession.py:13`);
  `library_row(context, reads, refusal, **lookup)` and `Refusal` from
  `games.commands.scope`; `known_zone(name) -> bool` defined in this module.
- Produces:
  - `CommandName.PLAYERSESSION_END = "library.playersession.end"`.
  - `_check_aware(*instants: datetime | None) -> None` at module level in
    `games/commands/playersession.py`, no longer a `CreateSession`
    `@staticmethod`.
  - `EndSession(session_id: uuid.UUID, ended_at: datetime,
    ended_at_zone: str | None)`.

- [ ] **Step 1: Add the command name**

In `games/events/dispatch.py`, directly after `PLAYERSESSION_CREATE` in
`CommandName`:

```python
    PLAYERSESSION_END = "library.playersession.end"
```

- [ ] **Step 2: Write the failing command tests**

Append to `tests/test_playersession_command.py`. Extend the
`games.commands.playersession` import with `EndSession`; `uuid`, `UTC`,
`datetime`, `timedelta`, `pytest`, `timezone`, `dispatch`, `CommandOutcome`,
`CommandRejected`, `Game`, `LibraryEvent`, `PlayerGame`, `PlayerSession`,
`PlayerSessionTimingMode`, `Playthrough`, `START`, `record`, `a_timed`,
`a_duration_only`, `a_corrected` and the `second_library` fixture are already
there.

```python
# --- Ending a running session ------------------------------------------------

AN_END = START + timedelta(hours=2)


def ends(library, actor, session, *, ended_at, ended_at_zone=None, key=None):
    result = dispatch(
        EndSession(
            session_id=session.pk, ended_at=ended_at, ended_at_zone=ended_at_zone
        ),
        actor=actor,
        library=library,
        idempotency_key=key or str(uuid.uuid7()),
    )
    session.refresh_from_db()
    return result


def refused_end(
    library, actor, session_id, *, ended_at=AN_END, ended_at_zone=None
) -> CommandRejected:
    with pytest.raises(CommandRejected) as refusal:
        dispatch(
            EndSession(
                session_id=session_id, ended_at=ended_at, ended_at_zone=ended_at_zone
            ),
            actor=actor,
            library=library,
            idempotency_key=str(uuid.uuid7()),
        )
    assert refusal.value.sentence
    return refusal.value


def test_it_ends_a_running_session(owned_user, owned_library, run):
    session = record(owned_library, owned_user, run, a_timed())

    result = ends(
        owned_library, owned_user, session, ended_at=AN_END, ended_at_zone="Asia/Tokyo"
    )

    assert result.outcome is CommandOutcome.APPENDED
    assert (session.ended_at, session.ended_at_zone) == (AN_END, "Asia/Tokyo")
    assert session.effective_duration == timedelta(hours=2)
    assert (
        LibraryEvent.objects.filter(event_type="library.playersession.ended").count()
        == 1
    )


def test_an_end_equal_to_the_start_is_recorded(owned_user, owned_library, run):
    """Started by mistake and ended at once; removal is the other remedy."""
    session = record(owned_library, owned_user, run, a_timed())

    ends(owned_library, owned_user, session, ended_at=START)

    assert session.ended_at == START
    assert session.effective_duration == timedelta(0)


def test_a_blank_zone_is_recorded_as_no_zone(owned_user, owned_library, run):
    session = record(owned_library, owned_user, run, a_timed())

    ends(owned_library, owned_user, session, ended_at=AN_END, ended_at_zone="   ")

    assert session.ended_at_zone is None


def test_an_empty_zone_normalizes_to_no_zone():
    """One statement, one digest, whichever way the caller spelled it."""
    blank = EndSession(session_id=uuid.uuid7(), ended_at=AN_END, ended_at_zone="")

    assert blank.ended_at_zone is None


def test_a_naive_end_is_refused_at_construction():
    with pytest.raises(CommandRejected) as refusal:
        EndSession(
            session_id=uuid.uuid7(),
            ended_at=datetime(2026, 1, 2, 1, 30),
            ended_at_zone=None,
        )

    assert refusal.value.sentence


def test_restating_the_same_end_changes_nothing(owned_user, owned_library, run):
    session = record(owned_library, owned_user, run, a_timed())
    ends(
        owned_library, owned_user, session, ended_at=AN_END, ended_at_zone="Asia/Tokyo"
    )

    result = ends(
        owned_library, owned_user, session, ended_at=AN_END, ended_at_zone="Asia/Tokyo"
    )

    assert result.outcome is CommandOutcome.UNCHANGED
    assert (
        LibraryEvent.objects.filter(event_type="library.playersession.ended").count()
        == 1
    )


def test_the_same_instant_in_another_zone_is_refused(owned_user, owned_library, run):
    session = record(owned_library, owned_user, run, a_timed())
    ends(
        owned_library, owned_user, session, ended_at=AN_END, ended_at_zone="Asia/Tokyo"
    )

    refused_end(
        owned_library,
        owned_user,
        session.pk,
        ended_at=AN_END,
        ended_at_zone="Europe/Prague",
    )


def test_a_second_end_is_refused(owned_user, owned_library, run):
    session = record(owned_library, owned_user, run, a_timed())
    ends(owned_library, owned_user, session, ended_at=AN_END)

    refused_end(
        owned_library, owned_user, session.pk, ended_at=AN_END + timedelta(hours=1)
    )


def test_an_end_before_the_start_is_refused(owned_user, owned_library, run):
    session = record(owned_library, owned_user, run, a_timed())

    refused_end(
        owned_library, owned_user, session.pk, ended_at=START - timedelta(seconds=1)
    )


def test_a_duration_only_session_has_no_end_to_state(owned_user, owned_library, run):
    session = record(owned_library, owned_user, run, a_duration_only())

    refused_end(owned_library, owned_user, session.pk, ended_at=AN_END)


def test_a_corrected_session_already_has_an_end(owned_user, owned_library, run):
    session = record(owned_library, owned_user, run, a_corrected())

    refused_end(owned_library, owned_user, session.pk, ended_at=AN_END)


def test_a_zone_no_tzdata_knows_is_refused(owned_user, owned_library, run):
    session = record(owned_library, owned_user, run, a_timed())

    refused_end(
        owned_library,
        owned_user,
        session.pk,
        ended_at=AN_END,
        ended_at_zone="Mars/Olympus_Mons",
    )


def test_an_unknown_session_is_refused(owned_user, owned_library, run):
    refused_end(owned_library, owned_user, uuid.uuid7(), ended_at=AN_END)


def test_a_removed_session_is_refused(owned_user, owned_library, run):
    """Arranged with an UPDATE: nothing states a session's mark yet."""
    session = record(owned_library, owned_user, run, a_timed())
    PlayerSession.objects.filter(pk=session.pk).update(removed_at=timezone.now())

    refused_end(owned_library, owned_user, session.pk, ended_at=AN_END)


def test_ending_under_a_removed_run_is_refused(owned_user, owned_library, run):
    session = record(owned_library, owned_user, run, a_timed())
    Playthrough.objects.filter(pk=run.pk).update(removed_at=timezone.now())

    refused_end(owned_library, owned_user, session.pk, ended_at=AN_END)


def test_ending_under_a_removed_game_is_refused(owned_user, owned_library, run):
    session = record(owned_library, owned_user, run, a_timed())
    PlayerGame.objects.filter(pk=run.player_game_id).update(removed_at=timezone.now())

    refused_end(owned_library, owned_user, session.pk, ended_at=AN_END)


def test_a_session_another_library_holds_is_refused(
    owned_user, owned_library, second_library
):
    game = Game.objects.create(library=second_library, name="Elsewhere")
    tracked = PlayerGame.objects.create(
        id=uuid.uuid7(),
        library=second_library,
        game=game,
        tracked_at=timezone.now(),
    )
    other_run = Playthrough.objects.create(
        id=uuid.uuid7(),
        library=second_library,
        player_game=tracked,
        kind="ordinary",
        created_at=timezone.now(),
    )
    elsewhere = PlayerSession.objects.create(
        id=uuid.uuid7(),
        library=second_library,
        playthrough=other_run,
        device=None,
        timing_mode=PlayerSessionTimingMode.TIMED,
        started_at=START,
        started_at_zone=None,
        ended_at=None,
        ended_at_zone=None,
        stated_day=None,
        stated_duration=None,
        day_zone="Europe/Prague",
        note="",
        emulated=False,
        created_at=timezone.now(),
    )

    refused_end(owned_library, owned_user, elsewhere.pk, ended_at=AN_END)
```

- [ ] **Step 3: Run the tests to verify they fail**

```bash
make test ARGS="tests/test_playersession_command.py -k end"
```

Expected: FAIL — `ImportError: cannot import name 'EndSession'`.

- [ ] **Step 4: Lift `_check_aware` to module level**

In `games/commands/playersession.py`, delete the `_check_aware` staticmethod
from `CreateSession` and put this function above `CreateSession`, beside
`known_zone`:

```python
def _check_aware(*instants: datetime | None) -> None:
    """Instants that name a moment on every host.

    Module-level rather than a method: two commands check their
    input's shape before the fingerprint, and neither reads state.
    """
    for instant in instants:
        if instant is None:
            continue
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise CommandRejected(
                f"{instant!r} states no offset, so it names no instant and "
                "would read differently on another host.",
                sentence="That time is missing its time zone.",
            )
```

Then change the two call sites inside `CreateSession.__post_init__` from
`self._check_aware(started_at, ended_at)` to `_check_aware(started_at, ended_at)`.

- [ ] **Step 5: Add the resolution helpers**

Below `_check_aware` in the same module:

```python
def _live_session(context: CommandContext, session_id: uuid.UUID) -> PlayerSession:
    """The session, refused if nothing may be stated about it."""
    session = library_row(
        context,
        #: The plain manager. `alive()` is a verb every read states
        #: for itself, and a restore names a removed row.
        PlayerSession.objects.all(),
        Refusal(
            message=(
                f"This library holds no session {session_id}. A stated fact "
                "belongs to a session the library records."
            ),
            sentence="That session is not available.",
        ),
        pk=session_id,
    )
    #: Reused whole, and for its scope as much as its marks: it
    #: resolves the run through `library_playthrough`, so it proves
    #: the run this session names is this library's -- the registered
    #: reference the ownership audit walks, which a `library=` on the
    #: session alone would miss.
    _live_run(context, session.playthrough_id)
    #: Under dispatch's lock: the mark cannot move. Nothing states one
    #: yet; resolving a session is where the rule belongs.
    if session.removed_at is not None:
        raise CommandRejected(
            f"This library removed session {session_id}, so it states no "
            "further facts about it.",
            sentence=(
                "That session was removed from your library. Restore it "
                "before recording this."
            ),
        )
    return session


def _timed_start(session: PlayerSession) -> tuple[datetime, str]:
    """A Timed row's start and the zone its day is read in.

    The mode is refused before either value is read, so a corrected
    row is told what it is rather than told it already has an end:
    the remedy differs.
    """
    if session.timing_mode == PlayerSessionTimingMode.DURATION_ONLY:
        raise CommandRejected(
            f"Session {session.pk} states a written day and a duration, so it "
            "holds no instants and has no end to give.",
            sentence=(
                "This session records how long it lasted on a day, so it has "
                "no end to state."
            ),
        )
    if session.timing_mode == PlayerSessionTimingMode.CORRECTED:
        raise CommandRejected(
            f"Session {session.pk} already states both instants and an "
            "override, so its end is a correction rather than a first "
            "statement.",
            sentence=(
                "This session's time was already corrected, so it already has "
                "an end. Correct it again to change it."
            ),
        )
    started_at, day_zone = session.started_at, session.day_zone
    if started_at is None or day_zone is None:
        #: `playersession_timed_columns` forbids this. Stated rather
        #: than cast away, so a relaxed constraint is met here with a
        #: sentence instead of inside the builder as a TypeError.
        raise CommandRejected(
            f"Timed session {session.pk} states no start or no day zone, which "
            "the timed-columns constraint forbids. The row is wrong, not the "
            "statement.",
            sentence="We cannot read that session's start time.",
        )
    return started_at, day_zone
```

- [ ] **Step 6: Add the command**

At the end of `games/commands/playersession.py`:

```python
@dataclass(frozen=True, slots=True)
class EndSession(Command):
    """State when a running Timed session ended."""

    command_name: ClassVar[CommandName] = CommandName.PLAYERSESSION_END
    #: A UUID, because Command fingerprints its fields.
    session_id: uuid.UUID
    ended_at: datetime
    #: No default. Null is a zone nobody stated, which a caller says
    #: rather than falls into: a forgotten argument is a TypeError at
    #: the call site, not a session silently recorded as stating none.
    ended_at_zone: str | None

    def __post_init__(self) -> None:
        #: One spelling of a zone nobody stated, so a restatement
        #: fingerprints alike. A browser reporting none posts an empty
        #: string, which `known_zone` would refuse rather than record
        #: as unset.
        stated = (self.ended_at_zone or "").strip()
        object.__setattr__(self, "ended_at_zone", stated or None)
        #: Before the fingerprint rather than inside build(): dispatch
        #: fingerprints the input first, and a naive datetime has no
        #: canonical form there, so a build-time refusal would never
        #: run and the person would meet a TypeError instead.
        _check_aware(self.ended_at)

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        session = _live_session(context, self.session_id)
        started_at, day_zone = _timed_start(session)
        if session.ended_at is not None:
            if (session.ended_at, session.ended_at_zone) == (
                self.ended_at,
                self.ended_at_zone,
            ):
                return Unchanged("This session already ends then.")
            raise CommandRejected(
                f"Session {self.session_id} already ends at {session.ended_at}, "
                "and a second end would say it stopped twice.",
                sentence=(
                    "This session already has an end. Correct the one it has "
                    "instead of stating another."
                ),
            )
        if self.ended_at < started_at:
            raise CommandRejected(
                f"Session {self.session_id} would end at {self.ended_at}, before "
                f"it started at {started_at}, and no session does.",
                sentence="This session would end before it started. Check the time.",
            )
        #: The only guard there is. The zone feeds no generated column
        #: and the one CHECK on it refuses a blank string alone, so an
        #: unknown name violates nothing and is stored permanently.
        if self.ended_at_zone is not None and not known_zone(self.ended_at_zone):
            raise CommandRejected(
                f"{self.ended_at_zone!r} is not a time zone this installation "
                "can read, and the column would take it silently.",
                sentence=f"{self.ended_at_zone} is not a time zone we know.",
            )
        return [
            playersession_ended(
                session.pk,
                ended_at=self.ended_at,
                ended_at_zone=self.ended_at_zone,
                day_zone=day_zone,
            )
        ]
```

Extend this module's imports: `playersession_ended` from
`games.events.playersession`, and `PlayerSession, PlayerSessionTimingMode`
from `games.models` (which currently imports `Device` alone).

- [ ] **Step 7: Run the tests to verify they pass**

```bash
make test ARGS="tests/test_playersession_command.py"
```

Expected: PASS, including every `CreateSession` test — the lifted
`_check_aware` must not have changed their behaviour.

- [ ] **Step 8: Type-check and lint**

```bash
make lint-fix && make typecheck && make vale
```

Expected: clean. If mypy reports `started_at` as `datetime | None` inside
`build`, the `_timed_start` return annotation was dropped — it is the narrowing.

- [ ] **Step 9: Commit**

```bash
git add games/events/dispatch.py games/commands/playersession.py tests/test_playersession_command.py
git commit -m "feat: state the end of a running session as a command"
```

---

### Task 4: The verification gate

**Files:** none — this task changes nothing and gates everything.

- [ ] **Step 1: Confirm no command-boundary registry work is outstanding**

```bash
make test ARGS="tests/test_command_answers.py tests/test_command_scope_guard.py tests/test_iterator_guard.py"
```

Expected: PASS with no edit. `EndSession` raises only `CommandRejected`, which
is answered directly; it adds no foreign key, so
`AUDITED_PROJECTION_REFERENCES` is unchanged; and `_live_session` resolves
through `library_row`, so the scope guard finds no bare manager `.get()`.

- [ ] **Step 2: Run the full gate**

```bash
make check
```

Expected: green — lint, format-check, mypy, vale, ts-check, vitest, and the
entire pytest suite including `e2e/`. This is the gate; `make check-fast` is
not a substitute.

- [ ] **Step 3: Push and open the pull request**

```bash
git push -u origin feat/issue-691-session-end
```

```bash
gh pr create --title "feat: end a running Timed session (#691)" --body "Implements #691 per docs/superpowers/specs/2026-09-13-issue-691-session-end-design.md. One command, one event, one handler; nothing calls EndSession yet — #702 owns the surfaces."
```

Merge with `gh pr merge --merge` when the checks pass. After it merges, reap
the local branch and the remote one.

---

## What this deliberately leaves undone

Nothing calls `EndSession` when this merges, which makes it incomplete rather
than inconsistent — the same way #689 merged. Out of scope: every screen and
route, the session form's "end plus manual duration" reading, the correction
commands, removal and restoration, the legacy conversion, and any read of
`ended_at`.
