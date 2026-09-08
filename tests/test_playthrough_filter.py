"""#1013: the filter reads the projection."""

import uuid

import pytest
from django.utils import timezone

from games.filters import PlaythroughFilter, filter_query_context_for_library
from games.models import Game, Playthrough, PlaythroughKind
from games.reads.playthrough_endpoints import days_to_finish
from games.reads.playthrough_runs import library_runs
from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.django_db

#: The marker each endpoint states its act with.
MARKERS = {"started": "start_recorded_at", "completed": "completion_recorded_at"}

#: One run per shape the endpoint can state.
SHAPES = {
    "day": "2025-03-15",
    "month": "2025-03",
    "year": "2025",
    "decade": "202X",
    "range": "2025-03-10/2025-03-20",
    "open start": "/2025-03-20",
    "open end": "2025-03-10/",
}

ENDPOINTS = ("started", "completed")


def state(run: Playthrough, **values: object) -> None:
    """Write columns a command would state, without one.

    Both endpoints generate their bound columns, so an UPDATE is
    the only way to state a shape a command would refuse.
    """
    Playthrough.objects.filter(pk=run.pk).update(**values)


def one_run(library, name: str) -> Playthrough:
    """The run a newly tracked game is born with."""
    game = Game.objects.create(library=library, name=name)
    return Playthrough.objects.get(player_game__game=game)


def matched(library, filter_object) -> set[str]:
    """The shapes this filter answers."""
    queryset = library_runs(library).filter(
        filter_object.to_q(filter_query_context_for_library(library))
    )
    return {
        run.player_game.game.name.removeprefix("Game ")
        for run in queryset.select_related("player_game__game")
    }


@pytest.fixture
def shaped_runs(owned_library):
    """One run per shape, each stating the named endpoint."""

    def make(endpoint: str) -> None:
        for shape, text in SHAPES.items():
            run = one_run(owned_library, f"Game {shape}")
            state(
                run,
                **{
                    MARKERS[endpoint]: timezone.now(),
                    endpoint: TemporalValue.parse(text),
                },
            )

    return make


@pytest.fixture
def other_library(django_user_model):
    """A second library, whose runs this one never reads."""
    owner = django_user_model.objects.create_user(username="other-owner", password="p")
    return owner.library


def test_the_scope_states_all_four_things(owned_library, other_library):
    """A removed run, an imported one and another library's
    reach no page and no count."""
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    run = Playthrough.objects.get(player_game__game=game)
    imported = Playthrough.objects.create(
        pk=uuid.uuid7(),
        library=owned_library,
        player_game=run.player_game,
        kind=PlaythroughKind.IMPORTED_HISTORY,
        created_at=timezone.now(),
    )
    removed = Playthrough.objects.create(
        pk=uuid.uuid7(),
        library=owned_library,
        player_game=run.player_game,
        kind=PlaythroughKind.ORDINARY,
        created_at=timezone.now(),
        removed_at=timezone.now(),
    )
    theirs = Playthrough.objects.get(
        player_game__game=Game.objects.create(library=other_library, name="Tunic")
    )

    scoped = set(library_runs(owned_library).values_list("pk", flat=True))

    assert run.pk in scoped
    assert imported.pk not in scoped
    assert removed.pk not in scoped
    assert theirs.pk not in scoped


def test_the_scope_states_the_library_beside_the_parent(owned_library, other_library):
    """A run naming another library's tracked game is the drift
    `audit_library_ownership` reports, and neither library reads
    it."""
    game = Game.objects.create(library=other_library, name="Hollow Knight")
    theirs = Playthrough.objects.get(player_game__game=game)
    crossed = Playthrough.objects.create(
        pk=uuid.uuid7(),
        library=owned_library,
        player_game=theirs.player_game,
        kind=PlaythroughKind.ORDINARY,
        created_at=timezone.now(),
    )

    assert crossed.pk not in set(
        library_runs(owned_library).values_list("pk", flat=True)
    )
    assert crossed.pk not in set(
        library_runs(other_library).values_list("pk", flat=True)
    )


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_equality_overlaps(owned_library, shaped_runs, endpoint):
    """A run stated as 2025 may well have happened that day."""
    shaped_runs(endpoint)

    assert matched(
        owned_library, PlaythroughFilter.where(**{endpoint: "2025-03-15"})
    ) == set(SHAPES)


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_equality_outside_every_interval_answers_nothing(
    owned_library, shaped_runs, endpoint
):
    """Only the two shapes the day still falls inside answer."""
    shaped_runs(endpoint)

    assert matched(
        owned_library, PlaythroughFilter.where(**{endpoint: "2024-01-01"})
    ) == {"decade", "open start"}


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_after_is_certain(owned_library, shaped_runs, endpoint):
    """A run is after March only where the earliest day it can
    name is after March."""
    shaped_runs(endpoint)

    assert (
        matched(
            owned_library, PlaythroughFilter.where(**{f"{endpoint}__gt": "2025-03-31"})
        )
        == set()
    )


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_before_is_certain(owned_library, shaped_runs, endpoint):
    """And before March only where the latest day it can name
    is before March."""
    shaped_runs(endpoint)

    assert (
        matched(
            owned_library, PlaythroughFilter.where(**{f"{endpoint}__lt": "2025-03-01"})
        )
        == set()
    )


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_negation_is_certain(owned_library, shaped_runs, endpoint):
    """Not that day means no day the value can name is that
    day, so an interval holding it answers neither side."""
    shaped_runs(endpoint)

    assert (
        matched(
            owned_library, PlaythroughFilter.where(**{f"{endpoint}__ne": "2025-03-15"})
        )
        == set()
    )


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_between_overlaps(owned_library, shaped_runs, endpoint):
    """Between March 1 and March 31 answers every shape that
    can name a day in March."""
    shaped_runs(endpoint)

    assert matched(
        owned_library,
        PlaythroughFilter.where(
            **{f"{endpoint}__between": ("2025-03-01", "2025-03-31")}
        ),
    ) == set(SHAPES)


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_not_between_is_certain(owned_library, shaped_runs, endpoint):
    """Outside 2024 means no day the value can name is in it."""
    shaped_runs(endpoint)

    assert matched(
        owned_library,
        PlaythroughFilter.where(
            **{f"{endpoint}__not_between": ("2024-01-01", "2024-12-31")}
        ),
    ) == {"day", "month", "year", "range", "open end"}


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_an_act_with_no_day_answers_neither_side(owned_library, endpoint):
    """It answers `is null`, and the marker answers the act."""
    state(
        one_run(owned_library, "Game no day"),
        **{MARKERS[endpoint]: timezone.now(), endpoint: None},
    )

    assert (
        matched(owned_library, PlaythroughFilter.where(**{endpoint: "2025-03-15"}))
        == set()
    )
    assert (
        matched(
            owned_library, PlaythroughFilter.where(**{f"{endpoint}__ne": "2025-03-15"})
        )
        == set()
    )
    assert matched(
        owned_library, PlaythroughFilter.where(**{f"{endpoint}__isnull": True})
    ) == {"no day"}
    act = "is_started" if endpoint == "started" else "is_completed"
    assert matched(owned_library, PlaythroughFilter.where(**{act: True})) == {"no day"}


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_an_act_nobody_recorded_answers_no_act(owned_library, endpoint):
    """A tracked game's run states neither act until somebody
    does, and `is null` on the value is not that question."""
    one_run(owned_library, "Game untouched")

    act = "is_started" if endpoint == "started" else "is_completed"
    assert matched(owned_library, PlaythroughFilter.where(**{act: True})) == set()
    assert matched(owned_library, PlaythroughFilter.where(**{act: False})) == {
        "untouched"
    }


#: One run per span the two bounds can state, keyed by the word
#: its game is named after.
SPANS = {
    "same day": ("2025-03-01", "2025-03-01"),
    "next day": ("2025-03-01", "2025-03-02"),
    "thirty": ("2025-03-01", "2025-03-30"),
    "month": ("2025-03", "2025-03"),
    "backwards": ("2025-03-02", "2025-03-01"),
    "unfinished": ("2025-03-01", None),
}


@pytest.fixture
def spans(owned_library) -> None:
    """A run per span, one of them completed before it started."""
    now = timezone.now()
    for name, (started, completed) in SPANS.items():
        run = one_run(owned_library, f"Game {name}")
        values: dict[str, object] = {
            "start_recorded_at": now,
            "started": TemporalValue.parse(started),
        }
        if completed is not None:
            values["completion_recorded_at"] = now
            values["completed"] = TemporalValue.parse(completed)
        state(run, **values)


@pytest.mark.parametrize("count", [1, 2, 30, 31])
def test_the_filter_answers_what_the_read_counts(owned_library, spans, count):
    """The read and the filter count the same days, so a run
    the one answers for is a run the other answers for."""
    by_read = {
        run.player_game.game.name.removeprefix("Game ")
        for run in library_runs(owned_library).select_related("player_game__game")
        if days_to_finish(run) == count
    }

    assert (
        matched(owned_library, PlaythroughFilter.where(days_to_finish=count)) == by_read
    )


def test_a_count_below_one_answers_nothing(owned_library, spans):
    """The count never reads 0, so nothing answers for it, and a
    run completed before it started reads no count at all."""
    assert matched(owned_library, PlaythroughFilter.where(days_to_finish=0)) == set()
    assert matched(owned_library, PlaythroughFilter.where(days_to_finish=-1)) == set()


def test_a_run_with_one_bound_answers_no_comparison(owned_library, spans):
    """A started run nobody completed has no count."""
    answered = matched(owned_library, PlaythroughFilter.where(days_to_finish__gt=0))

    assert "unfinished" not in answered
    assert "backwards" not in answered


def test_more_than_and_fewer_than_read_the_same_span(owned_library, spans):
    """Two days or more leaves the same-day run out; fewer than
    thirty leaves the thirty-day run out."""
    assert matched(owned_library, PlaythroughFilter.where(days_to_finish__gt=1)) == {
        "next day",
        "thirty",
        "month",
    }
    assert matched(owned_library, PlaythroughFilter.where(days_to_finish__lt=30)) == {
        "same day",
        "next day",
    }


def test_between_reads_both_ends(owned_library, spans):
    """Two to thirty days, both counts included."""
    assert matched(
        owned_library, PlaythroughFilter.where(days_to_finish__between=(2, 30))
    ) == {"next day", "thirty"}


def test_the_count_reads_the_runs_a_person_finished(owned_library):
    """`playthrough_count` counts what `Played N times` prints.

    Every tracked game holds a run from the moment the library
    tracks it, so a plain count would read 1 for a game nobody
    played. The aggregate states a completion of its own.
    """
    from common.criteria import AggregateCriterion, Modifier
    from games.filters import GameFilter
    from games.reads.playthrough_runs import completed_run_count

    unfinished = Game.objects.create(library=owned_library, name="Game unfinished")
    finished = one_run(owned_library, "Game finished")
    state(
        finished,
        completion_recorded_at=timezone.now(),
        completed=TemporalValue.parse("2025-03-15"),
    )
    context = filter_query_context_for_library(owned_library)

    def counted(count: int) -> set[str]:
        return {
            game.name
            for game in Game.objects.filter(
                GameFilter(
                    playthrough_count=AggregateCriterion(
                        value=count, modifier=Modifier.EQUALS
                    )
                ).to_q(context)
            )
        }

    assert counted(0) == {"Game unfinished"}
    assert counted(1) == {"Game finished"}
    assert completed_run_count(owned_library, finished.player_game) == 1
    assert (
        completed_run_count(
            owned_library,
            Playthrough.objects.get(player_game__game=unfinished).player_game,
        )
        == 0
    )
