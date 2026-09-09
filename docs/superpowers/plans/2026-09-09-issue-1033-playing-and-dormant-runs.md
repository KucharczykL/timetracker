# Playing and Dormant runs implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An unfinished run states whether it is being played — Playing, Dormant
or Never played — computed from a clock, shown on Game detail and the
Playthrough list, and filterable.

**Architecture:** Nothing is written: no event, no column, no migration. Two
queryset annotations carry the whole feature. `activity_day` is a correlated
subquery over the library's live sessions at the run's game, truncated to a day
in the viewer's zone, falling back to the run's own `started_lower`. `activity`
is a `Case` over that day against a boundary day the viewer's
`DORMANT_AFTER_DAYS` sets. Because both are plain aliases, the filter, the quick
facet, nested relation compiles and the two screens all read one expression.

**Tech Stack:** Django 6 (`Subquery`, `OuterRef`, `Coalesce`, `TruncDate`,
`Case`/`When`), PostgreSQL 18, pytest + pytest-django, the repo's Python
component system.

**Spec:** `docs/superpowers/specs/2026-09-09-issue-1033-playing-and-dormant-runs-design.md`

## Global Constraints

- Run everything through `make`. Never raw `uv run` / `pytest` / `pnpm`.
  Focused runs: `make test ARGS="tests/test_x.py -k name -x"`.
- The verification gate before declaring done is a full `make check`, `e2e/`
  included. `make check-fast` is for iterating only.
- Python 3.14. PEP 758 bare `except A, B:` is the formatter's output; do not
  fight it.
- `make vale` enforces the refused-word list. Never write `fold`, `seam`,
  `tombstone`, `archive`, `delete` or `heal` about a projector, an event or a
  projection row. A projector **replays**; the row it leaves is a **projection**.
- Name variables with complete words. No `el`, `tpl`, `e`, `btn`.
- Name compound and primitive roles with a `TypedDict` / `NamedTuple` /
  PEP 695 alias rather than a repeated structural annotation.
- Nothing opens a server-side cursor: never `QuerySet.iterator()`.
- Build UI with `common.components`, never HTML strings or Django templates.
- The three condition words are exactly `Playing`, `Dormant`, `Never played`.
  The third is deliberately not `Unplayed`: `PlayerGameStatus.UNPLAYED` already
  spells that, and Game detail prints a status beside these rows.
- `DORMANT_AFTER_DAYS`: scope `USER`, timing `LIVE`, widget `SELECT`, choices
  7 / 14 / 30 / 60 / 90 / 180 / 365, default 30, `cast=int`.
- Both sides of the comparison are days, never instants: `>= boundary_day`.

---

## File structure

| file | responsibility |
|---|---|
| `games/reads/playthrough_activity.py` | **new.** The clock, the two annotation expressions, the three words, and the recency phrase. The one place this feature's arithmetic lives. |
| `games/models.py` | `PlaythroughQuerySet` with `annotated_for_filtering(clock=None)`, and `Playthrough.objects` built from it. |
| `timetracker/settings_registry.py` | the `DORMANT_AFTER_DAYS` definition, its choices tuple and its validator. |
| `common/criteria.py` | one additive `FilterField.choices`, preferred by `field_metadata` over a column's. |
| `games/filters.py` | `PlaythroughFilter.activity`, its handler, its `FilterField`; the corrected `filter_queryset_for_library` docstring. |
| `games/reads/playthrough_runs.py` | `library_runs()` annotates. |
| `games/reads/playthrough_numbering.py` | `numbered_for()` annotates. |
| `common/components/quick_filter.py` | the `Activity` facet. |
| `games/views/playthrough_rows.py` | the Activity column. |
| `docs/vocabulary.md`, `docs/STATUSES.md`, `CLAUDE.md` | the three condition/status pairs, and the two places that say the projection declares no manager. |

Tests land in `tests/test_playthrough_activity.py` (new), and in the existing
`tests/test_playthrough_filter.py`, `tests/test_playthrough_rows.py`,
`tests/test_game_detail_playthroughs.py`, `tests/test_settings_registry.py`.

---

### Task 1: The setting

**Files:**
- Modify: `timetracker/settings_registry.py`
- Test: `tests/test_settings_registry.py`

**Interfaces:**
- Consumes: nothing.
- Produces: setting key `"DORMANT_AFTER_DAYS"`, resolvable with
  `resolve_for_user(user, "DORMANT_AFTER_DAYS") -> int`; module constants
  `DEFAULT_DORMANT_AFTER_DAYS: Final[int] = 30`,
  `DORMANT_AFTER_DAYS_CHOICES: Final[tuple[int, ...]]`,
  `DORMANT_AFTER_DAYS_OPTIONS: Final[tuple[SettingOption, ...]]`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_settings_registry.py`:

```python
def test_dormant_after_days_is_a_live_user_select():
    definition = SETTINGS_REGISTRY["DORMANT_AFTER_DAYS"]

    assert definition.scope is SettingScope.USER
    assert definition.apply_timing is ApplyTiming.LIVE
    assert definition.widget is SettingWidget.SELECT
    assert definition.cast is int
    assert [value for value, _label in definition.choices] == [
        7,
        14,
        30,
        60,
        90,
        180,
        365,
    ]
    assert definition.default_factory() == 30


def test_dormant_after_days_refuses_a_day_count_off_the_list():
    definition = SETTINGS_REGISTRY["DORMANT_AFTER_DAYS"]

    assert definition.validator(90) == 90
    with pytest.raises(ValidationError):
        definition.validator(45)
    with pytest.raises(ValidationError):
        definition.validator(True)
```

Read the top of the file first: it already imports the registry under whichever
name that module uses (`SETTINGS_REGISTRY` or a `settings_registry()` accessor).
Use the name that file already uses; do not add a second accessor.

- [ ] **Step 2: Run it and watch it fail**

Run: `make test ARGS="tests/test_settings_registry.py -k dormant -x"`
Expected: FAIL — `KeyError: 'DORMANT_AFTER_DAYS'`.

- [ ] **Step 3: Add the constants**

Beside `PAGE_SIZE_CHOICES` in `timetracker/settings_registry.py`:

```python
DEFAULT_DORMANT_AFTER_DAYS: Final[int] = 30
DORMANT_AFTER_DAYS_CHOICES: Final[tuple[int, ...]] = (7, 14, 30, 60, 90, 180, 365)
DORMANT_AFTER_DAYS_OPTIONS: Final[tuple[SettingOption, ...]] = tuple(
    (days, f"{days} days") for days in DORMANT_AFTER_DAYS_CHOICES
)
```

- [ ] **Step 4: Add the validator**

Beside `_validate_page_size`:

```python
def _validate_dormant_after_days(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(f"Days must be a whole number (got {value!r}).")
    if value not in DORMANT_AFTER_DAYS_CHOICES:
        choices = ", ".join(str(choice) for choice in DORMANT_AFTER_DAYS_CHOICES)
        raise ValidationError(f"Days must be one of {choices} (got {value!r}).")
    return value
```

- [ ] **Step 5: Register the setting**

In the registry tuple, directly after the `DEFAULT_PAGE_SIZE` entry:

```text
        SettingDefinition(
            "DORMANT_AFTER_DAYS",
            scope=SettingScope.USER,
            apply_timing=ApplyTiming.LIVE,
            label="Dormant after",
            help_text=(
                "How long an unfinished playthrough goes unplayed before it "
                "reads Dormant instead of Playing."
            ),
            cast=int,
            default_factory=lambda: DEFAULT_DORMANT_AFTER_DAYS,
            validator=_validate_dormant_after_days,
            widget=SettingWidget.SELECT,
            choices=DORMANT_AFTER_DAYS_OPTIONS,
        ),
```

Do **not** add the key to `USER_PREFERENCE_FIELD_BY_KEY` in `games/models.py`.
A key absent from that map lands in the `extra_preferences` JSON bag, which is
what keeps this migration-free — `DEFAULT_PAGE_SIZE` is the precedent.

- [ ] **Step 6: Run the test and the neighbours**

Run: `make test ARGS="tests/test_settings_registry.py tests/test_settings_page.py tests/test_settings_api.py -x"`
Expected: PASS. The settings page and API build their rows from the registry, so
they pick the new row up with no further change; if either has a test pinning the
number of rendered rows, update that count.

- [ ] **Step 7: Commit**

```bash
git add timetracker/settings_registry.py tests/test_settings_registry.py
git commit -m "Let a person say when a run goes quiet"
```

---

### Task 2: The clock and the three words

**Files:**
- Create: `games/reads/playthrough_activity.py`
- Test: `tests/test_playthrough_activity.py`

**Interfaces:**
- Consumes: `DORMANT_AFTER_DAYS` from Task 1.
- Produces:

```python
class RunActivity(models.TextChoices):
    PLAYING = "playing", "Playing"
    DORMANT = "dormant", "Dormant"
    NEVER_PLAYED = "never_played", "Never played"


class ActivityClock(NamedTuple):
    threshold_days: int
    zone: ZoneInfo
    boundary_day: date


def activity_clock(library: UserLibrary) -> ActivityClock: ...
def recency_phrase(day: date, today: date) -> str: ...
```

- [ ] **Step 1: Write the failing test**

Create `tests/test_playthrough_activity.py`:

```python
"""The clock that says whether a run is being played."""

from datetime import date
from zoneinfo import ZoneInfo

import pytest

from games.reads.playthrough_activity import (
    activity_clock,
    recency_phrase,
)


@pytest.mark.django_db
def test_the_clock_reads_thirty_days_by_default(owned_library):
    clock = activity_clock(owned_library)

    assert clock.threshold_days == 30
    assert clock.boundary_day == date.today() - timedelta(days=30)


@pytest.mark.django_db
def test_a_personal_threshold_moves_the_boundary(owned_user, owned_library):
    set_user_setting(owned_user, "DORMANT_AFTER_DAYS", 7)

    clock = activity_clock(owned_library)

    assert clock.threshold_days == 7
    assert clock.boundary_day == date.today() - timedelta(days=7)


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2026, 9, 9), "today"),
        (date(2026, 9, 8), "yesterday"),
        (date(2026, 9, 5), "4 days ago"),
        (date(2026, 8, 9), "1 month ago"),
        (date(2026, 6, 9), "3 months ago"),
        (date(2025, 9, 9), "1 year ago"),
        (date(2023, 9, 9), "3 years ago"),
    ],
)
def test_the_recency_phrase_reads_the_distance(day: date, expected: str):
    assert recency_phrase(day, date(2026, 9, 9)) == expected


def test_a_day_in_the_future_reads_today():
    assert recency_phrase(date(2026, 9, 10), date(2026, 9, 9)) == "today"
```

Add `from datetime import timedelta` to the imports. `date.today()` reads the
process zone, which is not always the clock's — compute the expected day as
`datetime.now(clock.zone).date() - timedelta(days=...)` so the assertion cannot
flip at midnight. For `set_user_setting`, read
how `tests/test_settings_page.py` or `tests/test_duration_setting.py` writes a
personal preference and copy that helper rather than inventing one — the write
goes through the settings write path, not a raw model save, and the autouse
`_reset_settings_caches` fixture in `tests/conftest.py` keeps the 5-second
resolver cache from leaking between tests.

- [ ] **Step 2: Run it and watch it fail**

Run: `make test ARGS="tests/test_playthrough_activity.py -x"`
Expected: FAIL — `ModuleNotFoundError: games.reads.playthrough_activity`.

- [ ] **Step 3: Write the module**

Create `games/reads/playthrough_activity.py`:

```python
"""Whether an unfinished run is being played.

A clock answers, not a column. Nothing here is written:
the words are computed from the last day the game was
played and the threshold the person owns.
"""

from datetime import date, timedelta
from typing import NamedTuple
from zoneinfo import ZoneInfo

from django.db import models
from django.utils import timezone as django_timezone

from games.models import UserLibrary
from timetracker.settings_resolver import resolve_for_user, resolve_str_for_user


class RunActivity(models.TextChoices):
    """What an unfinished run's clock says.

    Not `PlayerGameStatus`: a status is stated by a person
    and a condition is counted in days. Never played is
    spelled apart from the status `Unplayed` on purpose,
    because Game detail prints both beside one game.
    """

    PLAYING = "playing", "Playing"
    DORMANT = "dormant", "Dormant"
    NEVER_PLAYED = "never_played", "Never played"


class ActivityClock(NamedTuple):
    """One request's answer to "how long is too long"."""

    threshold_days: int
    zone: ZoneInfo
    boundary_day: date


def activity_clock(library: UserLibrary) -> ActivityClock:
    """The threshold and the zone this library reads by.

    Built from the library, never passed in: a parameter
    lets one call site state the viewer's threshold and
    the next forget it.
    """
    user = library.user
    threshold_days = int(resolve_for_user(user, "DORMANT_AFTER_DAYS"))
    zone = ZoneInfo(resolve_str_for_user(user, "DISPLAY_TIME_ZONE"))
    today = django_timezone.now().astimezone(zone).date()
    return ActivityClock(
        threshold_days=threshold_days,
        zone=zone,
        boundary_day=today - timedelta(days=threshold_days),
    )


def default_activity_clock() -> ActivityClock:
    """What a read with no viewer counts by.

    The registry default in UTC. A filter compiled only to
    be validated executes nothing, so the numbers it counts
    with never reach a screen.
    """
    threshold_days = DEFAULT_DORMANT_AFTER_DAYS
    zone = ZoneInfo("UTC")
    today = django_timezone.now().astimezone(zone).date()
    return ActivityClock(
        threshold_days=threshold_days,
        zone=zone,
        boundary_day=today - timedelta(days=threshold_days),
    )


def recency_phrase(day: date, today: date) -> str:
    """How long ago that day was, in plain words.

    A day ahead of today reads `today`: a session may be
    recorded in a zone ahead of the viewer's.
    """
    days = (today - day).days
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 30:
        return f"{days} days ago"
    if days < 365:
        months = days // 30
        return f"{months} month ago" if months == 1 else f"{months} months ago"
    years = days // 365
    return f"{years} year ago" if years == 1 else f"{years} years ago"
```

Import `DEFAULT_DORMANT_AFTER_DAYS` from `timetracker.settings_registry`.

Check `DISPLAY_TIME_ZONE`'s registered key name in
`timetracker/settings_registry.py` before writing that line — read the definition
and use its exact key. `common/date_time_presentation.py:444-451` shows how the
rest of the app reaches the same zone.

- [ ] **Step 4: Run the test**

Run: `make test ARGS="tests/test_playthrough_activity.py -x"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add games/reads/playthrough_activity.py tests/test_playthrough_activity.py
git commit -m "Count the days since a game was played"
```

---

### Task 3: The two annotations

**Files:**
- Modify: `games/reads/playthrough_activity.py`
- Modify: `games/models.py` (the `Playthrough` class and a new
  `PlaythroughQuerySet` above it)
- Test: `tests/test_playthrough_activity.py`

**Interfaces:**
- Consumes: `ActivityClock`, `RunActivity`, `default_activity_clock` from Task 2.
- Produces:

```python
# games/reads/playthrough_activity.py
def activity_day_expression(clock: ActivityClock) -> models.Expression: ...
def activity_expression(clock: ActivityClock) -> models.Expression: ...


# games/models.py
class PlaythroughQuerySet(models.QuerySet):
    def annotated_for_filtering(self, clock=None) -> "PlaythroughQuerySet": ...
```

Aliases produced: `activity_day` (a `date` or `None`) and `activity` (a
`RunActivity` value or `None`).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_playthrough_activity.py`:

```python
@pytest.mark.django_db(transaction=True)
def test_a_run_with_a_recent_session_is_playing(owned_user, owned_library, game):
    tracked = a_tracked_game(owned_user, game)
    a_session(owned_library, game, days_ago=3)

    run = annotated_run(owned_library, tracked)

    assert run.activity == RunActivity.PLAYING
    assert run.activity_day == date.today() - timedelta(days=3)


@pytest.mark.django_db(transaction=True)
def test_a_run_whose_last_session_is_older_than_the_threshold_is_dormant(
    owned_user, owned_library, game
):
    tracked = a_tracked_game(owned_user, game)
    a_session(owned_library, game, days_ago=100)

    run = annotated_run(owned_library, tracked)

    assert run.activity == RunActivity.DORMANT


@pytest.mark.django_db(transaction=True)
def test_a_run_with_no_session_and_no_start_day_was_never_played(
    owned_user, owned_library, game
):
    tracked = a_tracked_game(owned_user, game)

    run = annotated_run(owned_library, tracked)

    assert run.activity == RunActivity.NEVER_PLAYED
    assert run.activity_day is None


@pytest.mark.django_db(transaction=True)
def test_a_run_with_no_session_reads_its_own_start_day(owned_user, owned_library, game):
    tracked = a_tracked_game(owned_user, game)
    start_the_run(owned_user, owned_library, tracked, day=date.today())

    run = annotated_run(owned_library, tracked)

    assert run.activity == RunActivity.PLAYING
    assert run.activity_day == date.today()


@pytest.mark.django_db(transaction=True)
def test_a_session_beats_a_later_start_day(owned_user, owned_library, game):
    """The order is a preference, not a maximum."""
    tracked = a_tracked_game(owned_user, game)
    start_the_run(owned_user, owned_library, tracked, day=date.today())
    a_session(owned_library, game, days_ago=100)

    run = annotated_run(owned_library, tracked)

    assert run.activity_day == date.today() - timedelta(days=100)
    assert run.activity == RunActivity.DORMANT


@pytest.mark.django_db(transaction=True)
def test_a_completed_run_carries_no_word(owned_user, owned_library, game):
    tracked = a_tracked_game(owned_user, game)
    a_session(owned_library, game, days_ago=3)
    complete_the_run(owned_user, owned_library, tracked, day=date.today())

    run = annotated_run(owned_library, tracked)

    assert run.activity is None


@pytest.mark.django_db(transaction=True)
def test_a_personal_threshold_moves_a_run_from_playing_to_dormant(
    owned_user, owned_library, game
):
    tracked = a_tracked_game(owned_user, game)
    a_session(owned_library, game, days_ago=10)
    assert annotated_run(owned_library, tracked).activity == RunActivity.PLAYING

    set_user_setting(owned_user, "DORMANT_AFTER_DAYS", 7)

    assert annotated_run(owned_library, tracked).activity == RunActivity.DORMANT


@pytest.mark.django_db(transaction=True)
def test_another_library_s_sessions_at_a_shared_game_move_no_word(
    owned_user, owned_library, django_user_model
):
    """A shared catalog game reads no session at all."""
    shared = Game.objects.create(library=None, name="Shared")
    tracked = a_tracked_game(owned_user, shared)
    other = django_user_model.objects.create_user(username="other", password="p")
    Session.objects.create(
        game=shared,
        timestamp_start=django_timezone.now(),
    )

    run = annotated_run(owned_library, tracked)

    assert run.activity == RunActivity.NEVER_PLAYED


@pytest.mark.django_db(transaction=True)
def test_a_late_session_and_a_start_on_that_day_read_alike(
    owned_user, owned_library, game, settings
):
    """One comparison space: both sides answer a day.

    A session at 23:30 local on the boundary day and a run
    started on that same date must give the same word, in a
    zone whose offset moves that week.
    """
    set_user_setting(owned_user, "DISPLAY_TIME_ZONE", "America/Santiago")
    set_user_setting(owned_user, "DORMANT_AFTER_DAYS", 7)
    clock = activity_clock(owned_library)
    late = datetime.combine(clock.boundary_day, time(23, 30), tzinfo=clock.zone)

    by_session = a_tracked_game(owned_user, game)
    Session.objects.create(game=game, timestamp_start=late)
    other = Game.objects.create(library=owned_library, name="Other")
    by_start = a_tracked_game(owned_user, other)
    start_the_run(owned_user, owned_library, by_start, day=clock.boundary_day)

    assert annotated_run(owned_library, by_session).activity == RunActivity.PLAYING
    assert annotated_run(owned_library, by_start).activity == RunActivity.PLAYING


@pytest.mark.django_db(transaction=True)
def test_annotating_twice_states_one_clock(owned_user, owned_library, game):
    tracked = a_tracked_game(owned_user, game)
    a_session(owned_library, game, days_ago=10)
    clock = activity_clock(owned_library)

    once = library_runs(owned_library).filter(player_game=tracked)
    twice = once.annotated_for_filtering(clock)

    assert twice.get().activity == once.get().activity
```

Write the helpers at the top of the file, copying the fixture idiom from
`tests/test_playthrough_runs_read.py:24-42` — `game`, `a_tracked_game`,
`pytestmark = pytest.mark.untracked_games`. `annotated_run` is:

```python
def annotated_run(library, tracked) -> Playthrough:
    """The one run, with its aliases."""
    return library_runs(library).filter(player_game=tracked).get()
```

`a_session(library, game, *, days_ago)` creates a `Session` with
`timestamp_start=django_timezone.now() - timedelta(days=days_ago)`. Read
`games/models.py` for `Session`'s required fields before writing it; a session's
game is what scopes it, and `Session` has no library column of its own.
`start_the_run` and `complete_the_run` dispatch `StartPlaythrough` and
`CompletePlaythrough` from `games/commands/playthrough.py` — copy the dispatch
shape from `tests/test_playthrough_command.py`.

The shared-game test needs the `other` user only to prove the point about scope;
if the fixture set makes an unowned `Session` awkward to build, assert instead
that `activity_day is None` for the shared game and drop the second user.

- [ ] **Step 2: Run it and watch it fail**

Run: `make test ARGS="tests/test_playthrough_activity.py -x"`
Expected: FAIL — `AttributeError: 'Playthrough' object has no attribute 'activity'`.

- [ ] **Step 3: Write the expressions**

Append to `games/reads/playthrough_activity.py`:

```python
def activity_day_expression(clock: ActivityClock) -> models.Expression:
    """The day the word reads.

    The latest live session at the run's game, as this
    library sees sessions, else the run's own start day.
    A preference, not a maximum: a game with sessions
    never reads its start day.

    The library is stated as the run's own column, so a
    run at a shared catalog game reads no session and one
    library's play never moves another's word.
    """
    latest_session_day = (
        Session.objects.alive()
        .filter(
            game=OuterRef("player_game__game"),
            game__library=OuterRef("library"),
            game__removed_at__isnull=True,
        )
        .order_by("-timestamp_start")
        .annotate(played_day=TruncDate("timestamp_start", tzinfo=clock.zone))
        .values("played_day")[:1]
    )
    return Coalesce(
        Subquery(latest_session_day, output_field=models.DateField()),
        F("started_lower"),
        output_field=models.DateField(),
    )


def activity_expression(clock: ActivityClock) -> models.Expression:
    """One of the three words, or nothing.

    A completed run is not unfinished, so no clock speaks
    about it and the alias is null. That null is what
    `_SetCriterion._not_in_q` keeps when a person excludes
    a word.
    """
    return Case(
        When(completion_recorded_at__isnull=False, then=Value(None)),
        When(activity_day__isnull=True, then=Value(RunActivity.NEVER_PLAYED)),
        When(activity_day__gte=clock.boundary_day, then=Value(RunActivity.PLAYING)),
        default=Value(RunActivity.DORMANT),
        output_field=models.CharField(null=True),
    )
```

Imports: `Case`, `F`, `OuterRef`, `Subquery`, `Value`, `When` from
`django.db.models`; `Coalesce` and `TruncDate` from
`django.db.models.functions`; `Session` from `games.models`.

If `Value(None)` trips the field resolver, wrap it as
`Value(None, output_field=models.CharField(null=True))`.

- [ ] **Step 4: Give Playthrough a queryset**

In `games/models.py`, directly above `class Playthrough`:

```python
class PlaythroughQuerySet(models.QuerySet):
    """The alias method, and nothing else.

    No `alive()` and no `for_library()`: every read of this
    projection states its own scope, and a scoping verb here
    would invite a read that forgets to.
    """

    def annotated_for_filtering(self, clock=None):
        """Register the two condition aliases.

        A second call states the same fact: Django's
        `add_annotation` replaces an alias without a word,
        so a caller reaching an already-annotated queryset
        would otherwise swap one clock for another in
        silence.

        No clock reads the registry default in UTC, which is
        what a filter compiled only to be validated gets.
        That context executes nothing.
        """
        from games.reads.playthrough_activity import (
            activity_day_expression,
            activity_expression,
            default_activity_clock,
        )

        if "activity" in self.query.annotations:
            return self
        resolved = clock if clock is not None else default_activity_clock()
        return self.annotate(activity_day=activity_day_expression(resolved)).annotate(
            activity=activity_expression(resolved)
        )
```

Then on `Playthrough`, beside its other class attributes:

```python
    objects = models.Manager.from_queryset(PlaythroughQuerySet)()
```

The method must live on the **queryset**, not on a manager:
`with_filter_aliases` (`common/criteria.py:1341-1351`) reads it off a queryset it
was handed, and `FilterQueryContext.for_validation` hands it
`model._default_manager.none()`. A manager-only method is invisible there and
un-chainable from `library_runs()`.

The import is function-local on purpose: `games/reads/playthrough_activity.py`
imports from `games.models`.

- [ ] **Step 5: Annotate the two reads**

In `games/reads/playthrough_runs.py`, `library_runs` returns:

```text
    return Playthrough.objects.filter(
        ...
    ).annotated_for_filtering(activity_clock(library))
```

In `games/reads/playthrough_numbering.py`, `numbered_for` wraps its base
queryset the same way, before `with_display_number`:

```python
    return with_display_number(
        Playthrough.objects.filter(
            library=library,
            player_game__library=library,
            player_game_id__in=list(player_game_ids),
        ).annotated_for_filtering(activity_clock(library))
    ).order_by(*DISPLAY_ORDER)
```

Neither takes a clock parameter: each holds the library already. Leave
`live_ordinary_runs()` alone — commands read it and a write path resolves no
display setting.

Add a one-line note to each docstring saying the read carries the condition
aliases.

- [ ] **Step 6: Run the tests**

Run: `make test ARGS="tests/test_playthrough_activity.py tests/test_playthrough_runs_read.py tests/test_playthrough_numbering.py tests/test_playthrough_projection.py -x"`
Expected: PASS.

- [ ] **Step 7: Run every read that touches these querysets**

Run: `make test ARGS="tests/test_playthrough_api_reads.py tests/test_playthrough_completions_read.py tests/test_playthrough_filter.py tests/test_game_detail_playthroughs.py -x"`
Expected: PASS. An annotation is masked out of `.count()`, `.exists()` and
`__in` subqueries, so pagination and the completion reads are untouched; if
anything fails here it is a real interaction, not a flake — read the SQL before
changing the expression.

- [ ] **Step 8: Commit**

```bash
git add games/reads/playthrough_activity.py games/models.py \
        games/reads/playthrough_runs.py games/reads/playthrough_numbering.py \
        tests/test_playthrough_activity.py
git commit -m "Let a read answer whether a run is being played"
```

---

### Task 4: A filter field may declare its own choices

**Files:**
- Modify: `common/criteria.py`
- Test: `tests/test_filters.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `FilterField.choices: tuple[ChoiceMeta, ...] | None = None`,
  preferred by `field_metadata` over `_static_choices(model_field)`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_filters.py`:

```python
def test_a_handler_field_may_declare_its_own_choices():
    """A field with no column still fills its picker."""

    @dataclass
    class _ChoiceFilter(OperatorFilter):
        condition: ChoiceCriterion | None = None

        fields: ClassVar[dict[str, FilterField]] = {
            "condition": FilterField(
                handler=lambda criterion: criterion.to_q("condition"),
                choices=(ChoiceMeta(value="a", label="A"),),
            ),
        }

        @classmethod
        def _comparison_model(cls):
            from games.models import Playthrough

            return Playthrough

    (meta,) = [
        entry for entry in field_metadata(_ChoiceFilter) if entry.name == "condition"
    ]
    assert meta.choices == [ChoiceMeta(value="a", label="A")]
```

Read the top of `tests/test_filters.py` for how it declares throwaway filter
classes; copy that shape rather than the sketch above if it differs.

- [ ] **Step 2: Run it and watch it fail**

Run: `make test ARGS="tests/test_filters.py -k declare_its_own_choices -x"`
Expected: FAIL — `TypeError: FilterField.__init__() got an unexpected keyword argument 'choices'`.

- [ ] **Step 3: Add the field**

In `common/criteria.py`, on `FilterField`, after `metadata_lookup`:

```python
    # Choices for a field whose lookup names no column — an annotation the
    # queryset registers. A handler field skips column resolution, so
    # `_static_choices` has nothing to read and the panel FilterSelect would
    # render with neither options nor a search_url. Declared here, they reach
    # the widget the same way a column's do.
    choices: tuple[ChoiceMeta, ...] | None = None
```

- [ ] **Step 4: Prefer them in field_metadata**

In `field_metadata`, replace `choices=_static_choices(model_field)` with a
declared-wins read:

```python
            declared_choices = field_spec.choices if field_spec is not None else None
            choices = (
                list(declared_choices)
                if declared_choices is not None
                else _static_choices(model_field)
            )
```

and pass `choices=choices` into the `FieldMeta`.

- [ ] **Step 5: Run the test and the filter suite**

Run: `make test ARGS="tests/test_filters.py tests/test_filter_paths.py -x"`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add common/criteria.py tests/test_filters.py
git commit -m "Let a columnless filter field state its choices"
```

---

### Task 5: The filter and the facet

**Files:**
- Modify: `games/filters.py`
- Modify: `common/components/quick_filter.py`
- Test: `tests/test_playthrough_filter.py`, `tests/test_quick_filter_bar.py`

**Interfaces:**
- Consumes: the `activity` alias (Task 3), `FilterField.choices` (Task 4),
  `RunActivity` (Task 2).
- Produces: `PlaythroughFilter.activity: ChoiceCriterion | None`, filterable
  through `?filter={"activity": {...}}`, and `QuickFacet("activity", "Activity")`
  in `QUICK_FACETS["playthroughs"]`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_playthrough_filter.py`:

```python
@pytest.mark.django_db(transaction=True)
def test_the_activity_filter_narrows_to_one_word(owned_user, owned_library):
    playing = a_run_played(owned_user, owned_library, "Recent", days_ago=2)
    dormant = a_run_played(owned_user, owned_library, "Old", days_ago=400)

    matched = execute_filter(
        PlaythroughFilter(activity=ChoiceCriterion(value=[RunActivity.PLAYING])),
        library_runs(owned_library),
        filter_query_context_for_library(owned_library),
    )

    assert {run.pk for run in matched} == {playing.pk}
    assert dormant.pk not in {run.pk for run in matched}


@pytest.mark.django_db(transaction=True)
def test_two_words_at_once_narrow_to_their_union(owned_user, owned_library):
    playing = a_run_played(owned_user, owned_library, "Recent", days_ago=2)
    dormant = a_run_played(owned_user, owned_library, "Old", days_ago=400)
    finished = a_completed_run(owned_user, owned_library, "Done")

    matched = execute_filter(
        PlaythroughFilter(
            activity=ChoiceCriterion(value=[RunActivity.PLAYING, RunActivity.DORMANT])
        ),
        library_runs(owned_library),
        filter_query_context_for_library(owned_library),
    )

    assert {run.pk for run in matched} == {playing.pk, dormant.pk}
    assert finished.pk not in {run.pk for run in matched}


@pytest.mark.django_db(transaction=True)
def test_excluding_a_word_keeps_the_completed_runs(owned_user, owned_library):
    """The alias is null there, and `_not_in_q` keeps a null row."""
    playing = a_run_played(owned_user, owned_library, "Recent", days_ago=2)
    finished = a_completed_run(owned_user, owned_library, "Done")

    matched = execute_filter(
        PlaythroughFilter(
            activity=ChoiceCriterion(
                value=[RunActivity.PLAYING], modifier=Modifier.EXCLUDES
            )
        ),
        library_runs(owned_library),
        filter_query_context_for_library(owned_library),
    )

    assert finished.pk in {run.pk for run in matched}
    assert playing.pk not in {run.pk for run in matched}


def test_a_blob_naming_the_condition_passes_validation():
    """The alias must resolve on a validation-only context."""
    parsed = parse_playthrough_filter(
        '{"activity": {"value": ["playing"], "modifier": "INCLUDES"}}'
    )

    assert parsed is not None
    assert parsed.activity.value == ["playing"]


def test_the_condition_offers_its_three_words_to_the_picker():
    (meta,) = [
        entry for entry in field_metadata(PlaythroughFilter) if entry.name == "activity"
    ]

    assert meta.kind == "set"
    assert [choice.value for choice in meta.choices] == [
        "playing",
        "dormant",
        "never_played",
    ]
```

`a_run_played(user, library, name, *, days_ago)` tracks a new game under that
name and records one session that many days ago; `a_completed_run` tracks a game
and dispatches `CompletePlaythrough`. Copy both from the helpers Task 3 wrote and
from the existing helpers at the top of `tests/test_playthrough_filter.py`.

`parse_playthrough_filter` is the eager-validation path: it compiles the filter
against `FilterQueryContext.for_validation()`, which is exactly the path that
fails if Task 3 put the alias method on a manager.

- [ ] **Step 2: Run it and watch it fail**

Run: `make test ARGS="tests/test_playthrough_filter.py -k activity -x"`
Expected: FAIL — `TypeError: PlaythroughFilter() got an unexpected keyword argument 'activity'`.

- [ ] **Step 3: Add the field**

In `games/filters.py`, on `PlaythroughFilter`, after `created_at`:

```python
    #: The clock's word, not a column: `activity` is an alias
    #: `library_runs()` registers.
    activity: ChoiceCriterion | None = None
```

and in its `fields` map:

```python
        "activity": FilterField(
            #: Delegating, not comparing: ChoiceCriterion is a set
            #: criterion, so its value is a list and its modifier
            #: says whether to include it or exclude it. A handler
            #: that built its own Q would read one word and drop
            #: the modifier. The handler exists only to keep
            #: `field_metadata` off a column that does not exist.
            handler=lambda criterion: criterion.to_q("activity"),
            label="Activity",
            choices=ACTIVITY_CHOICES,
        ),
```

Above the class, build the choices from the words themselves so the two cannot
drift:

```python
#: The picker's three words, in the order a person reads them.
ACTIVITY_CHOICES: Final[tuple[ChoiceMeta, ...]] = tuple(
    ChoiceMeta(value=value, label=label) for value, label in RunActivity.choices
)
```

Import `RunActivity` from `games.reads.playthrough_activity` and `ChoiceMeta`
from `common.criteria`. If that import is circular, move `RunActivity` into
`games/models.py` beside `PlayerGameStatus` and import it from there — check
before writing.

- [ ] **Step 4: Add the facet**

In `common/components/quick_filter.py`, in `QUICK_FACETS["playthroughs"]`, first
in the list:

```text
        QuickFacet("activity", "Activity"),
```

`ChoiceCriterion` is kind `set`, which is in `QUICK_FACET_KINDS`, so the panel
`FilterSelect` renders it and the bar's serializer round-trips it.

- [ ] **Step 5: Run the tests**

Run: `make test ARGS="tests/test_playthrough_filter.py tests/test_quick_filter_bar.py tests/test_filter_paths.py -x"`
Expected: PASS. `tests/test_filter_paths.py` asserts one rendered widget per
facet, so an optionless picker fails there — that test is the guard for Task 4.

- [ ] **Step 6: Check a saved preset and a nested compile**

Run: `make test ARGS="tests/test_filter_presets.py tests/test_filter_cross_entity.py tests/test_relation_algebra.py -x"`
Expected: PASS. A nested `PlaythroughFilter` inside `playthrough_count` compiles
against `context.queryset_for(Playthrough)`, which is `library_runs()`, so the
alias is there. If a test file in that list does not exist, run
`make test ARGS="tests/ -k 'preset or relation or cross_entity' -x"` instead.

- [ ] **Step 7: Commit**

```bash
git add games/filters.py common/components/quick_filter.py \
        tests/test_playthrough_filter.py
git commit -m "Filter the runs by what the clock says"
```

---

### Task 6: The Activity column

**Files:**
- Modify: `games/views/playthrough_rows.py`
- Test: `tests/test_playthrough_rows.py`, `tests/test_game_detail_playthroughs.py`

**Interfaces:**
- Consumes: `run.activity`, `run.activity_day` (Task 3), `recency_phrase` and
  `RunActivity` (Task 2).
- Produces: an `Activity` column in `playthrough_tabledata`, rendered on both
  the Playthrough list and Game detail.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_playthrough_rows.py`:

```python
@pytest.mark.django_db(transaction=True)
def test_a_playing_run_prints_its_badge_and_its_recency(
    owned_user, owned_library, game
):
    tracked = a_tracked_game(owned_user, game)
    a_session(owned_library, game, days_ago=4)
    run = library_runs(owned_library).filter(player_game=tracked).get()

    html = str(rendered_table([run]))

    assert "Playing" in html
    assert "last played 4 days ago" in html


@pytest.mark.django_db(transaction=True)
def test_a_never_played_run_prints_no_recency(owned_user, owned_library, game):
    tracked = a_tracked_game(owned_user, game)
    run = library_runs(owned_library).filter(player_game=tracked).get()

    html = str(rendered_table([run]))

    assert "Never played" in html
    assert "last played" not in html


@pytest.mark.django_db(transaction=True)
def test_a_completed_run_prints_a_dash_for_its_activity(
    owned_user, owned_library, game
):
    tracked = a_tracked_game(owned_user, game)
    complete_the_run(owned_user, owned_library, tracked, day=date.today())
    run = library_runs(owned_library).filter(player_game=tracked).get()

    cells = activity_cells(rendered_table([run]))

    assert cells == ["-"]
```

`rendered_table(runs)` calls `playthrough_tabledata(runs, _PRESENTATION,
origin=None, csrf_token="token")` and renders it; copy the existing helper at the
top of `tests/test_playthrough_rows.py` rather than writing a second one.
`activity_cells` reads the Activity column out of the rendered rows — if that
file has no such helper, assert on the row's cell list directly instead of
parsing HTML.

- [ ] **Step 2: Run it and watch it fail**

Run: `make test ARGS="tests/test_playthrough_rows.py -k activity -x"`
Expected: FAIL — no "Playing" in the output.

- [ ] **Step 3: Add the column**

In `games/views/playthrough_rows.py`, add to `column_list`, after
`column("Completed", priority=2)`:

```text
        column("Activity", priority=3),
```

The column carries no sort key: `_SORT_KEYS` gains no entry, and `column()`
already answers `None` for a label it does not know.

Add the cell to the row comprehension, in the same position:

```text
            _activity_cell(run, presentation),
```

and the builder:

```python
def _activity_cell(run: Playthrough, presentation: DateTimePresentation) -> Cell:
    """The clock's word, and how long ago that was.

    A completed run reads a dash: it is not unfinished, so
    no clock speaks about it.
    """
    activity = getattr(run, "activity", None)
    if activity is None:
        return "-"
    badge = Pill(label=RunActivity(activity).label)
    day = getattr(run, "activity_day", None)
    if day is None:
        return badge
    today = presentation.zone and datetime.now(presentation.zone).date()
    return Fragment(
        badge, Span(class_="ml-2 text-sm")[f"last played {recency_phrase(day, today)}"]
    )
```

Read `common/date_time_presentation.py` for the attribute holding the
presentation's `ZoneInfo` and use its real name instead of `presentation.zone`.
Import `Fragment`, `Pill` and `Span` from `common.components`, and
`RunActivity` / `recency_phrase` from `games.reads.playthrough_activity`.

The `getattr` guards are deliberate: `playthrough_tabledata` is called with rows
from two reads, and a caller that hands it an unannotated row should render a
dash rather than raise.

- [ ] **Step 4: Run the row tests**

Run: `make test ARGS="tests/test_playthrough_rows.py -x"`
Expected: PASS.

- [ ] **Step 5: Run both screens**

Run: `make test ARGS="tests/test_game_detail_playthroughs.py tests/test_playthrough_view_cutover.py tests/test_rendered_pages.py -x"`
Expected: PASS. `playthrough_tabledata` drops columns by **label** and both
screens pass `exclude_columns`, so a test pinning a column count or a cell index
needs updating — that is expected work, not a defect.

- [ ] **Step 6: Commit**

```bash
git add games/views/playthrough_rows.py tests/test_playthrough_rows.py \
        tests/test_game_detail_playthroughs.py
git commit -m "Print what the clock says beside each run"
```

---

### Task 7: The words, written down

**Files:**
- Modify: `docs/vocabulary.md`
- Modify: `docs/STATUSES.md`
- Modify: `CLAUDE.md`
- Modify: `games/filters.py` (the `filter_queryset_for_library` docstring)

**Interfaces:**
- Consumes: everything above.
- Produces: no code.

- [ ] **Step 1: Record the three pairs in the vocabulary**

In `docs/vocabulary.md`, in the **Settled** section, after the `family` entry:

```markdown
### `Playing`, `Dormant`, `Never played` — conditions, not statuses

A **condition** is a clock's answer about one run. A **status** is a person's
statement about a game, one of the six `PlayerGameStatus` words. All three
conditions meet a status that sounds like them, and none of them moves it.

| condition | the status it sounds like | why they differ |
|---|---|---|
| Dormant | Abandoned | the clock counts days; only a person abandons a game |
| Playing | Played | Played says a verdict is not stated yet, and stays true for years |
| Never played | Unplayed | Unplayed is stated at track time; the condition means no day is known |

A row may read status Played and condition Dormant, or status Unplayed and
condition Playing, and both pairs are correct. The third condition is spelled
`Never played` rather than `Unplayed` because Game detail prints a status
beside these rows, and one word for two things reads as one thing.
```

- [ ] **Step 2: Name the difference where STATUSES lists Abandoned**

In `docs/STATUSES.md`, after the paragraph ending "**Shelved** and **Abandoned**
are both unfinished — the second is final." (around line 19):

```markdown
**Abandoned is not Dormant.** Since #1033 an unfinished run also states a
condition — Playing, Dormant or Never played — which a clock computes from the
last day the game was played against the viewer's `DORMANT_AFTER_DAYS`. A status
is stated; a condition is counted. A dormant run leaves the status alone, and an
abandoned game states no condition. `docs/vocabulary.md` records all three pairs.
```

- [ ] **Step 3: Correct both places that say the projection declares no manager**

In `games/filters.py`, in `filter_queryset_for_library`'s docstring, replace:

> Playthrough is the other: the projection declares no manager, so every read
> states its own scope.

with:

> Playthrough is the other: its manager holds the condition aliases and no
> scoping verb, so every read still states its own scope.

In `CLAUDE.md`, find the sentence saying the projection declares no manager and
replace it with one saying `Playthrough` declares a queryset holding
`annotated_for_filtering` alone — no `alive()` and no `for_library()` — so every
read still states its own scope.

- [ ] **Step 4: Record the third word's verdict where it belongs**

The spec adds a third word to an issue that names two. Put the verdict in the
issue and in the wave design, not only in the spec:

```bash
gh issue comment 1033 --body "Scope: three words, not two. #679 gives every tracked game a run at track time, so a run at a game nobody has played is the common case, and calling it Dormant would say a game tracked this morning went quiet. The third word is \`Never played\` rather than \`Unplayed\`, because \`PlayerGameStatus.UNPLAYED\` already spells that and Game detail prints a status beside these rows."
```

Then add the same verdict to
`docs/superpowers/specs/2026-09-04-playthrough-wave-design.md`, in the section
naming #1033's two words (around lines 329-386), as one sentence pointing at
#1033.

The GitHub MCP server is failing to connect in this repo; use the `gh` CLI.

- [ ] **Step 5: Lint the prose**

Run: `make vale`
Expected: no findings.

- [ ] **Step 6: Commit**

```bash
git add docs/vocabulary.md docs/STATUSES.md CLAUDE.md games/filters.py \
        docs/superpowers/specs/2026-09-04-playthrough-wave-design.md
git commit -m "Say how a condition differs from a status"
```

---

### Task 8: The gate

**Files:** none — this task changes nothing unless something is red.

- [ ] **Step 1: Run the whole check**

Run: `make check`
Expected: green — lint, format-check, mypy, vale, ts-check, vitest, and the
entire pytest suite including `e2e/`.

- [ ] **Step 2: Read any failure before changing anything**

The two most likely reds, both real rather than flaky:

- a page test pinning a column count or a cell index, because
  `playthrough_tabledata` gained a column
- a settings-page test pinning a row count, because the registry gained a row

Update the expectation. If instead a **filter** test fails with
`FieldError: Cannot resolve keyword 'activity'`, the alias method is on the
manager rather than the queryset — re-read Task 3, Step 4.

- [ ] **Step 3: Commit any fixes**

```bash
git add -A
git commit -m "Fix what the gate caught"
```

- [ ] **Step 4: Open the pull request**

```bash
git push -u origin issue-1033-playing-and-dormant-runs
gh pr create --fill
```

---

## Out of scope

Named here so no task quietly grows one:

- a game-level facet across a game's runs
- a sort on the Activity column
- the condition in an API body
- narrowing the recency from the game to the run (#700, #701)
- a stored `playing` flag or a stated `stopped` endpoint

One measurement is worth taking and is **not** a blocker: `library_runs()` now
carries a correlated subquery, and the API list's `limit=0` is unbounded while
its schema states no condition. If that read is measurably slower, the fix is to
drop the alias from the API read, not to change the expression.
