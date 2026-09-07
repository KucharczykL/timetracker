"""Dispatching the commands that state a run."""

import uuid
from datetime import date

import pytest
from django.db import connection, models, transaction
from django.test.utils import isolate_apps
from django.utils import timezone

from games.commands import playthrough as playthrough_commands
from games.commands.playergame import PlayerGameNotTracked, TrackGame
from games.commands.playthrough import (
    PLAYTHROUGH_NAME_MAX_LENGTH,
    ActStatement,
    BlockingReferrer,
    CompletePlaythrough,
    CorrectPlaythroughCompletion,
    CorrectPlaythroughStart,
    CreatePlaythrough,
    DescribePlaythrough,
    RemovePlaythrough,
    RestorePlaythrough,
    StartPlaythrough,
    endpoints_certainly_reversed,
)
from games.events.append import lock_stream
from games.events.dispatch import CommandOutcome, CommandRejected, dispatch
from games.events.idempotency import IdempotencyKeyMismatch
from games.events.playthrough import playthrough_created
from games.models import (
    Game,
    LibraryEvent,
    PlayerGame,
    Playthrough,
    PlaythroughKind,
    ProjectionModel,
    RemovableLibraryQuerySet,
)
from games.reads.playthrough_numbering import display_name, with_display_number
from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.untracked_games


@pytest.fixture
def game(owned_library):
    return Game.objects.create(library=owned_library, name="Outer Wilds")


def _track(owned_user, owned_library, game, key="track"):
    return dispatch(
        TrackGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key=key,
    )


@pytest.mark.django_db(transaction=True)
def test_creating_a_playthrough_records_it_and_projects_it(
    owned_user, owned_library, game
):
    _track(owned_user, owned_library, game)

    result = dispatch(
        CreatePlaythrough(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="second-run",
    )

    assert result.outcome is CommandOutcome.APPENDED
    events = LibraryEvent.objects.filter(
        event_type="library.playthrough.created"
    ).order_by("sequence")
    assert events.count() == 2
    tracked = PlayerGame.objects.get()
    assert events.last().payload == {
        "player_game": str(tracked.pk),
        "kind": "ordinary",
    }
    assert Playthrough.objects.filter(player_game=tracked).count() == 2


@pytest.mark.django_db(transaction=True)
def test_creating_a_playthrough_for_an_untracked_game_is_refused(
    owned_user, owned_library, game
):
    with pytest.raises(PlayerGameNotTracked):
        dispatch(
            CreatePlaythrough(game_id=game.pk),
            actor=owned_user,
            library=owned_library,
            idempotency_key="untracked",
        )

    assert Playthrough.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_creating_a_playthrough_for_a_removed_game_is_refused(
    owned_user, owned_library, game
):
    _track(owned_user, owned_library, game)
    tracked = PlayerGame.objects.get()
    PlayerGame.objects.filter(pk=tracked.pk).update(removed_at=tracked.tracked_at)

    with pytest.raises(CommandRejected) as refusal:
        dispatch(
            CreatePlaythrough(game_id=game.pk),
            actor=owned_user,
            library=owned_library,
            idempotency_key="removed",
        )

    assert refusal.value.sentence == (
        "That game was removed from your library. Restore it before adding "
        "a playthrough."
    )
    #: Only the default, from TrackGame.
    assert Playthrough.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_a_repeat_under_one_key_records_nothing_further(
    owned_user, owned_library, game
):
    _track(owned_user, owned_library, game)
    for _ in range(2):
        dispatch(
            CreatePlaythrough(game_id=game.pk),
            actor=owned_user,
            library=owned_library,
            idempotency_key="second-run",
        )

    assert Playthrough.objects.count() == 2


@pytest.mark.django_db(transaction=True)
def test_one_build_states_the_run_its_note_and_both_acts(
    owned_user, owned_library, game
):
    """#687: a whole run in one dispatch."""
    _track(owned_user, owned_library, game)

    result = dispatch(
        CreatePlaythrough(
            game_id=game.pk,
            started=ActStatement(TemporalValue.from_day(date(2026, 1, 2))),
            completed=ActStatement(TemporalValue.from_day(date(2026, 2, 3))),
            note="12h 30m",
        ),
        actor=owned_user,
        library=owned_library,
        idempotency_key="whole-run",
    )

    assert result.outcome is CommandOutcome.APPENDED
    run = Playthrough.objects.get(note="12h 30m")
    assert run.started == TemporalValue.from_day(date(2026, 1, 2))
    assert run.completed == TemporalValue.from_day(date(2026, 2, 3))
    assert run.start_recorded_at is not None
    assert run.completion_recorded_at is not None


@pytest.mark.django_db(transaction=True)
def test_an_act_with_no_day_is_still_an_act(owned_user, owned_library, game):
    """#687: the marker is the act."""
    _track(owned_user, owned_library, game)

    dispatch(
        CreatePlaythrough(
            game_id=game.pk,
            started=ActStatement(None),
            completed=ActStatement(None),
        ),
        actor=owned_user,
        library=owned_library,
        idempotency_key="dayless",
    )

    run = Playthrough.objects.latest("created_at")
    assert run.started is None
    assert run.start_recorded_at is not None
    assert run.completion_recorded_at is not None


@pytest.mark.django_db(transaction=True)
def test_a_creation_that_states_no_act_states_no_endpoint(
    owned_user, owned_library, game
):
    """#687: TrackGame's run keeps both ends unstated."""
    _track(owned_user, owned_library, game)

    dispatch(
        CreatePlaythrough(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="actless",
    )

    run = Playthrough.objects.latest("created_at")
    assert run.start_recorded_at is None
    assert run.completion_recorded_at is None


@pytest.mark.django_db(transaction=True)
def test_a_creation_whose_acts_are_reversed_records_nothing(
    owned_user, owned_library, game
):
    """#687: one build, so no half-stated run."""
    _track(owned_user, owned_library, game)
    before = LibraryEvent.objects.count()

    with pytest.raises(CommandRejected) as refusal:
        dispatch(
            CreatePlaythrough(
                game_id=game.pk,
                started=ActStatement(TemporalValue.from_day(date(2026, 2, 3))),
                completed=ActStatement(TemporalValue.from_day(date(2026, 1, 2))),
            ),
            actor=owned_user,
            library=owned_library,
            idempotency_key="reversed",
        )

    assert refusal.value.sentence == (
        "This run finished before it started. Check the days."
    )
    assert LibraryEvent.objects.count() == before


@pytest.mark.django_db(transaction=True)
def test_the_endpoint_notes_of_a_created_run_are_its_own(
    owned_user, owned_library, game
):
    """#687: each act carries its own note."""
    _track(owned_user, owned_library, game)

    dispatch(
        CreatePlaythrough(
            game_id=game.pk,
            started=ActStatement(None, "  from the box  "),
            completed=ActStatement(TemporalValue.from_day(date(2026, 2, 3)), "100%"),
        ),
        actor=owned_user,
        library=owned_library,
        idempotency_key="endpoint-notes",
    )

    run = Playthrough.objects.latest("created_at")
    #: Stripped in __post_init__, so restatements fingerprint alike.
    assert run.start_note == "from the box"
    assert run.completion_note == "100%"


@pytest.mark.django_db(transaction=True)
def test_tracking_a_game_states_its_first_playthrough(owned_user, owned_library, game):
    """The first act states both facts."""
    _track(owned_user, owned_library, game)

    events = list(LibraryEvent.objects.order_by("sequence"))
    assert [event.event_type for event in events] == [
        "library.playergame.created",
        "library.playthrough.created",
    ]
    #: One dispatch, one correlation_id.
    assert len({event.correlation_id for event in events}) == 1
    assert events[1].sequence == events[0].sequence + 1

    tracked = PlayerGame.objects.get()
    run = Playthrough.objects.get()
    assert events[1].payload == {
        "player_game": str(tracked.pk),
        "kind": "ordinary",
    }
    assert (run.player_game_id, run.kind, run.library_id) == (
        tracked.pk,
        PlaythroughKind.ORDINARY,
        owned_library.pk,
    )


@pytest.mark.django_db(transaction=True)
def test_a_repeated_track_under_one_key_states_one_playthrough(
    owned_user, owned_library, game
):
    """A repeat answers from the idempotency record."""
    _track(owned_user, owned_library, game)
    _track(owned_user, owned_library, game)

    assert Playthrough.objects.count() == 1
    assert LibraryEvent.objects.count() == 2


@pytest.mark.django_db(transaction=True)
def test_tracking_an_already_tracked_game_states_no_second_default(
    owned_user, owned_library, game
):
    """#684 supplies a missing default, not TrackGame."""
    _track(owned_user, owned_library, game, key="first")
    result = _track(owned_user, owned_library, game, key="second")

    assert result.outcome is CommandOutcome.UNCHANGED
    assert Playthrough.objects.count() == 1


@pytest.mark.parametrize(
    ("started", "completed", "reversed_pair"),
    [
        #: Certainly reversed, at every precision.
        ("2024-03-20", "2024-03-10", True),
        ("2024-05", "2024-03", True),
        ("202X", "2019", True),
        ("2030", "202X", True),
        ("2024-06/2024-12", "2024-01", True),
        #: Consistent, or imprecise enough to be.
        ("2024-03-10", "2024-03", False),
        ("2024-03-10", "2024-03-10", False),
        ("2024-03", "2024-03-10", False),
        ("2019", "202X", False),
        ("2024-03", "202X", False),
        #: No bound on one side: nothing to prove.
        (None, "2024-03", False),
        ("2024-05", None, False),
        (None, None, False),
        #: A dated endpoint with no bound: a range with an open or an
        #: unknown far end. Both spellings bound the same nothing.
        ("../2024-06", "2020", False),
        ("2024-05", "2024-01/..", False),
        ("/2024-06", "2020", False),
        ("2024-06", "2019/", False),
        #: The near end of such a range still bounds.
        ("2024-01/", "2023", True),
        #: A qualifier states no certainty to contradict.
        ("2024-05~", "2024-03", False),
        ("2024-05?", "2024-03", False),
        ("2024-05%", "2024-03", False),
        ("2024-05-10~", "2024-05-09", False),
        ("2024-05", "2024-03~", False),
        #: A range states its qualifier on the endpoints.
        ("1984~/1986~", "1980", False),
        #: Only the end the comparison reads. The far end says nothing
        #: about the bound in hand, so it cannot excuse the pair.
        ("1984~/1986", "1980", False),
        ("1984/1986~", "1980", True),
        ("2024-06", "2019/2020-01~", False),
        ("2024-06", "2019~/2020-01", True),
    ],
)
def test_the_order_rule_refuses_only_the_certainly_impossible(
    started, completed, reversed_pair
):
    """Only the certainly-impossible pairs.

    Every other row reads as consistent, because a missing bound and a
    qualifier alike state no certainty for a date to contradict.
    """
    assert (
        endpoints_certainly_reversed(
            started=None if started is None else TemporalValue(started),
            completed=None if completed is None else TemporalValue(completed),
        )
        is reversed_pair
    )


def _start(owned_user, owned_library, playthrough, *, when, note="", key="start"):
    return dispatch(
        StartPlaythrough(playthrough_id=playthrough.pk, when=when, note=note),
        actor=owned_user,
        library=owned_library,
        idempotency_key=key,
    )


def _complete(owned_user, owned_library, playthrough, *, when, note="", key="done"):
    return dispatch(
        CompletePlaythrough(playthrough_id=playthrough.pk, when=when, note=note),
        actor=owned_user,
        library=owned_library,
        idempotency_key=key,
    )


@pytest.mark.django_db(transaction=True)
def test_stating_a_start_records_the_date_as_the_effective_time(
    owned_user, owned_library, game
):
    _track(owned_user, owned_library, game)
    playthrough = Playthrough.objects.get()

    result = _start(
        owned_user, owned_library, playthrough, when=TemporalValue.from_month(2024, 3)
    )

    assert result.outcome is CommandOutcome.APPENDED
    event = LibraryEvent.objects.get(event_type="library.playthrough.started")
    assert event.aggregate_id == playthrough.pk
    assert event.effective_time == TemporalValue.from_month(2024, 3)
    assert event.payload == {"note": ""}


@pytest.mark.django_db(transaction=True)
def test_played_before_records_the_act_with_no_date(owned_user, owned_library, game):
    """The headline case: a run happened, and nobody knows when.

    Nothing here is distinguishable by value from a row that never
    started, so a build comparing values would record nothing at all.
    """
    _track(owned_user, owned_library, game)
    playthrough = Playthrough.objects.get()

    result = _start(owned_user, owned_library, playthrough, when=None)

    assert result.outcome is CommandOutcome.APPENDED
    event = LibraryEvent.objects.get(event_type="library.playthrough.started")
    assert event.effective_time is None


@pytest.mark.django_db(transaction=True)
def test_restating_one_start_exactly_changes_nothing(owned_user, owned_library, game):
    _track(owned_user, owned_library, game)
    playthrough = Playthrough.objects.get()
    when = TemporalValue.from_day(date(2024, 3, 10))
    _start(owned_user, owned_library, playthrough, when=when, note="blind")

    result = _start(
        owned_user, owned_library, playthrough, when=when, note="blind", key="again"
    )

    assert result.outcome is CommandOutcome.UNCHANGED
    assert (
        LibraryEvent.objects.filter(event_type="library.playthrough.started").count()
        == 1
    )


@pytest.mark.django_db(transaction=True)
def test_an_unknown_day_restates_a_dateless_start(owned_user, owned_library, game):
    """Two spellings of no day, and one fact between them.

    The column keeps `None`, so a caller holding `unknown()` -- the
    backfill, and the form's empty draft -- restates what it stated.
    """
    _track(owned_user, owned_library, game)
    playthrough = Playthrough.objects.get()
    _start(owned_user, owned_library, playthrough, when=None)

    result = _start(
        owned_user,
        owned_library,
        playthrough,
        when=TemporalValue.unknown(),
        key="again",
    )

    assert result.outcome is CommandOutcome.UNCHANGED
    assert (
        LibraryEvent.objects.filter(event_type="library.playthrough.started").count()
        == 1
    )


@pytest.mark.django_db(transaction=True)
def test_restating_a_start_with_another_date_is_refused(
    owned_user, owned_library, game
):
    _track(owned_user, owned_library, game)
    playthrough = Playthrough.objects.get()
    _start(owned_user, owned_library, playthrough, when=TemporalValue.from_year(2024))

    with pytest.raises(CommandRejected) as refusal:
        _start(
            owned_user,
            owned_library,
            playthrough,
            when=TemporalValue.from_year(2025),
            key="moved",
        )

    assert refusal.value.sentence == (
        "This run already has a start. Correct the one it has instead of "
        "adding another."
    )


@pytest.mark.django_db(transaction=True)
def test_an_unknown_day_fingerprints_as_a_dateless_start(
    owned_user, owned_library, game
):
    """One key, two spellings, and no mismatch between them."""
    _track(owned_user, owned_library, game)
    playthrough = Playthrough.objects.get()
    _start(owned_user, owned_library, playthrough, when=None)

    result = _start(
        owned_user, owned_library, playthrough, when=TemporalValue.unknown()
    )

    assert result.outcome is CommandOutcome.REPLAYED
    assert (
        LibraryEvent.objects.filter(event_type="library.playthrough.started").count()
        == 1
    )


@pytest.mark.django_db(transaction=True)
def test_restating_a_start_with_another_note_is_refused(
    owned_user, owned_library, game
):
    """The endpoint is the pair, so its note is not a free field."""
    _track(owned_user, owned_library, game)
    playthrough = Playthrough.objects.get()
    _start(owned_user, owned_library, playthrough, when=None, note="blind")

    with pytest.raises(CommandRejected):
        _start(owned_user, owned_library, playthrough, when=None, note="", key="wiped")


@pytest.mark.django_db(transaction=True)
def test_restating_one_completion_exactly_changes_nothing(
    owned_user, owned_library, game
):
    _track(owned_user, owned_library, game)
    playthrough = Playthrough.objects.get()
    when = TemporalValue.from_day(date(2024, 6, 1))
    _complete(owned_user, owned_library, playthrough, when=when, note="all endings")

    result = _complete(
        owned_user,
        owned_library,
        playthrough,
        when=when,
        note="all endings",
        key="again",
    )

    assert result.outcome is CommandOutcome.UNCHANGED
    assert (
        LibraryEvent.objects.filter(event_type="library.playthrough.completed").count()
        == 1
    )


@pytest.mark.django_db(transaction=True)
def test_restating_a_completion_with_another_date_is_refused(
    owned_user, owned_library, game
):
    _track(owned_user, owned_library, game)
    playthrough = Playthrough.objects.get()
    _complete(
        owned_user, owned_library, playthrough, when=TemporalValue.from_year(2024)
    )

    with pytest.raises(CommandRejected) as refusal:
        _complete(
            owned_user,
            owned_library,
            playthrough,
            when=TemporalValue.from_year(2025),
            key="moved",
        )

    assert refusal.value.sentence == (
        "This run already has a completion. Correct the one it has instead "
        "of adding another."
    )
    assert (
        LibraryEvent.objects.filter(event_type="library.playthrough.completed").count()
        == 1
    )


@pytest.mark.django_db(transaction=True)
def test_a_completion_before_the_start_is_refused(owned_user, owned_library, game):
    _track(owned_user, owned_library, game)
    playthrough = Playthrough.objects.get()
    _start(
        owned_user, owned_library, playthrough, when=TemporalValue.from_month(2024, 5)
    )

    with pytest.raises(CommandRejected) as refusal:
        _complete(
            owned_user,
            owned_library,
            playthrough,
            when=TemporalValue.from_month(2024, 3),
            key="reversed",
        )

    assert refusal.value.sentence == "This run started after that date. Check the day."
    assert not LibraryEvent.objects.filter(
        event_type="library.playthrough.completed"
    ).exists()


@pytest.mark.django_db(transaction=True)
def test_a_start_after_the_completion_is_refused_the_same_way(
    owned_user, owned_library, game
):
    """One rule, whichever endpoint is stated second."""
    _track(owned_user, owned_library, game)
    playthrough = Playthrough.objects.get()
    _complete(
        owned_user, owned_library, playthrough, when=TemporalValue.from_month(2024, 3)
    )

    with pytest.raises(CommandRejected):
        _start(
            owned_user,
            owned_library,
            playthrough,
            when=TemporalValue.from_month(2024, 5),
            key="late",
        )


@pytest.mark.django_db(transaction=True)
def test_stating_an_endpoint_of_another_library_is_refused(
    owned_user, owned_library, django_user_model
):
    """A refusal names no id, and leaks no row."""
    stranger = django_user_model.objects.create_user(username="stranger", password="p")
    elsewhere = Game.objects.create(library=stranger.library, name="Tunic")
    tracked = PlayerGame.objects.create(
        id=uuid.uuid7(),
        library=stranger.library,
        game=elsewhere,
        tracked_at=timezone.now(),
    )
    hidden = Playthrough.objects.create(
        id=uuid.uuid7(),
        library=stranger.library,
        player_game=tracked,
        kind=PlaythroughKind.ORDINARY,
        created_at=timezone.now(),
    )

    with pytest.raises(CommandRejected) as refusal:
        _start(owned_user, owned_library, hidden, when=None, key="foreign")

    assert refusal.value.sentence == "That playthrough is not available."


@pytest.mark.django_db(transaction=True)
def test_stating_an_endpoint_of_no_playthrough_is_refused_alike(
    owned_user, owned_library
):
    """A row of another library and no row answer in one sentence."""
    with pytest.raises(CommandRejected) as refusal:
        dispatch(
            StartPlaythrough(playthrough_id=uuid.uuid7(), when=None, note=""),
            actor=owned_user,
            library=owned_library,
            idempotency_key="nowhere",
        )

    assert refusal.value.sentence == "That playthrough is not available."


@pytest.mark.django_db(transaction=True)
def test_stating_an_endpoint_for_a_removed_game_is_refused(
    owned_user, owned_library, game
):
    _track(owned_user, owned_library, game)
    playthrough = Playthrough.objects.get()
    tracked = PlayerGame.objects.get()
    PlayerGame.objects.filter(pk=tracked.pk).update(removed_at=tracked.tracked_at)

    with pytest.raises(CommandRejected) as refusal:
        _start(owned_user, owned_library, playthrough, when=None, key="removed")

    assert refusal.value.sentence == (
        "That game was removed from your library. Restore it before recording this."
    )


@pytest.mark.django_db(transaction=True)
def test_stating_an_endpoint_for_a_removed_playthrough_is_refused(
    owned_user, owned_library, game
):
    """The shared resolver answers for both commands."""
    _track(owned_user, owned_library, game)
    playthrough = _second_run(owned_user, owned_library)
    _remove(owned_user, owned_library, playthrough, key="removal")

    with pytest.raises(CommandRejected) as refusal:
        _start(owned_user, owned_library, playthrough, when=None, key="gone")

    assert refusal.value.sentence == (
        "That playthrough was removed from your library. Restore it before "
        "recording this."
    )


def _describe(owned_user, owned_library, playthrough, *, name, note, key="describe"):
    return dispatch(
        DescribePlaythrough(playthrough_id=playthrough.pk, name=name, note=note),
        actor=owned_user,
        library=owned_library,
        idempotency_key=key,
    )


def _imported_run(owned_user, owned_library):
    """A bucket row, which no display number is counted across."""
    tracked = PlayerGame.objects.get()
    with transaction.atomic():
        stream = lock_stream(owned_library)
        appended = stream.append(
            [playthrough_created(tracked.pk, kind="imported_history")],
            actor=owned_user,
            correlation_id=uuid.uuid7(),
            idempotency_key="imported",
        )
    return Playthrough.objects.get(pk=appended.events[0].aggregate_id)


@pytest.mark.django_db(transaction=True)
def test_describing_a_run_records_one_event_per_stated_fact(
    owned_user, owned_library, game
):
    _track(owned_user, owned_library, game)
    run = Playthrough.objects.get()

    result = _describe(owned_user, owned_library, run, name="Ironman", note="no saves")

    assert result.outcome is CommandOutcome.APPENDED
    described = Playthrough.objects.get()
    assert (described.name, described.note) == ("Ironman", "no saves")
    recorded = LibraryEvent.objects.filter(aggregate_id=run.pk).order_by("sequence")
    assert [event.event_type for event in recorded] == [
        "library.playthrough.created",
        "library.playthrough.name_changed",
        "library.playthrough.note_changed",
    ]


@pytest.mark.django_db(transaction=True)
def test_a_fact_the_command_does_not_state_is_left_alone(
    owned_user, owned_library, game
):
    """None is not a value; it is the absence of a statement."""
    _track(owned_user, owned_library, game)
    run = Playthrough.objects.get()
    _describe(owned_user, owned_library, run, name="Ironman", note="no saves")

    _describe(owned_user, owned_library, run, name=None, note="one save", key="again")

    described = Playthrough.objects.get()
    assert (described.name, described.note) == ("Ironman", "one save")


@pytest.mark.django_db(transaction=True)
def test_a_cleared_name_reads_as_the_display_number(owned_user, owned_library, game):
    """Three spaces is a cleared name, not a name of spaces."""
    _track(owned_user, owned_library, game)
    run = Playthrough.objects.get()
    _describe(owned_user, owned_library, run, name="Ironman", note=None)

    _describe(owned_user, owned_library, run, name="   ", note=None, key="again")

    numbered = with_display_number(Playthrough.objects.all()).get()
    assert numbered.name == ""
    assert display_name(numbered) == "Playthrough 1"


@pytest.mark.django_db(transaction=True)
def test_the_note_is_stripped_like_the_name(owned_user, owned_library, game):
    """One rule for either fact, so neither stores its spaces."""
    _track(owned_user, owned_library, game)
    run = Playthrough.objects.get()

    _describe(owned_user, owned_library, run, name=None, note=" no saves ")

    assert Playthrough.objects.get().note == "no saves"


@pytest.mark.django_db(transaction=True)
def test_spaces_clear_the_note(owned_user, owned_library, game):
    _track(owned_user, owned_library, game)
    run = Playthrough.objects.get()
    _describe(owned_user, owned_library, run, name=None, note="no saves")

    _describe(owned_user, owned_library, run, name=None, note="   ", key="again")

    assert Playthrough.objects.get().note == ""


@pytest.mark.django_db(transaction=True)
def test_a_fact_stated_as_it_already_reads_records_no_event(
    owned_user, owned_library, game
):
    """A save that moved the note alone appends one event."""
    _track(owned_user, owned_library, game)
    run = Playthrough.objects.get()
    _describe(owned_user, owned_library, run, name="Ironman", note="no saves")

    _describe(
        owned_user, owned_library, run, name="Ironman", note="one save", key="again"
    )

    recorded = LibraryEvent.objects.filter(
        aggregate_id=run.pk, event_type="library.playthrough.name_changed"
    )
    assert recorded.count() == 1


@pytest.mark.django_db(transaction=True)
def test_a_name_that_differs_only_by_spaces_fingerprints_alike(
    owned_user, owned_library, game
):
    """The strip runs before the key is taken, or it is two keys."""
    _track(owned_user, owned_library, game)
    run = Playthrough.objects.get()
    _describe(owned_user, owned_library, run, name="Ironman ", note=None, key="one")

    again = _describe(
        owned_user, owned_library, run, name="Ironman", note=None, key="one"
    )

    assert again.outcome is CommandOutcome.REPLAYED


def test_a_command_that_states_no_fact_is_not_a_command():
    """A request expressing no intent claims no idempotency key."""
    with pytest.raises(ValueError):
        DescribePlaythrough(playthrough_id=uuid.uuid7(), name=None, note=None)


@pytest.mark.django_db(transaction=True)
def test_restating_both_facts_exactly_changes_nothing(owned_user, owned_library, game):
    _track(owned_user, owned_library, game)
    run = Playthrough.objects.get()
    _describe(owned_user, owned_library, run, name="Ironman", note="no saves")

    result = _describe(
        owned_user, owned_library, run, name="Ironman", note="no saves", key="again"
    )

    assert result.outcome is CommandOutcome.UNCHANGED
    assert (
        LibraryEvent.objects.filter(
            event_type="library.playthrough.name_changed"
        ).count()
        == 1
    )


@pytest.mark.django_db(transaction=True)
def test_a_name_longer_than_the_column_is_refused(owned_user, owned_library, game):
    """The bound is the column's width, read off the column."""
    _track(owned_user, owned_library, game)
    run = Playthrough.objects.get()

    with pytest.raises(CommandRejected) as refusal:
        _describe(owned_user, owned_library, run, name="x" * 256, note=None)

    assert refusal.value.sentence == (
        "That name is too long. Keep it to 255 characters or fewer."
    )
    assert not LibraryEvent.objects.filter(
        event_type="library.playthrough.name_changed"
    ).exists()


def test_the_refused_width_is_the_width_the_column_holds():
    """The sentence quotes a number, so the two cannot drift."""
    assert PLAYTHROUGH_NAME_MAX_LENGTH == Playthrough._meta.get_field("name").max_length


@pytest.mark.django_db(transaction=True)
def test_a_name_of_the_column_s_width_is_accepted(owned_user, owned_library, game):
    """The refusal is over the width, not at it."""
    _track(owned_user, owned_library, game)
    run = Playthrough.objects.get()

    result = _describe(
        owned_user,
        owned_library,
        run,
        name="x" * PLAYTHROUGH_NAME_MAX_LENGTH,
        note=None,
    )

    assert result.outcome is CommandOutcome.APPENDED
    assert Playthrough.objects.get().name == "x" * PLAYTHROUGH_NAME_MAX_LENGTH


@pytest.mark.django_db(transaction=True)
def test_clearing_the_name_of_an_unnumbered_run_is_refused(
    owned_user, owned_library, game
):
    """An imported-history run has no number to fall back on."""
    _track(owned_user, owned_library, game)
    imported = _imported_run(owned_user, owned_library)
    _describe(owned_user, owned_library, imported, name="Before 2020", note=None)

    with pytest.raises(CommandRejected) as refusal:
        _describe(owned_user, owned_library, imported, name="", note=None, key="clear")

    assert refusal.value.sentence == (
        "This run is not numbered, so it needs a name of its own."
    )


@pytest.mark.django_db(transaction=True)
def test_spaces_clear_the_name_of_an_unnumbered_run_and_are_refused_alike(
    owned_user, owned_library, game
):
    """The strip runs before the refusal reads the name."""
    _track(owned_user, owned_library, game)
    imported = _imported_run(owned_user, owned_library)
    _describe(owned_user, owned_library, imported, name="Before 2020", note=None)

    with pytest.raises(CommandRejected) as refusal:
        _describe(
            owned_user, owned_library, imported, name="   ", note=None, key="clear"
        )

    assert refusal.value.sentence == (
        "This run is not numbered, so it needs a name of its own."
    )


@pytest.mark.django_db(transaction=True)
def test_a_note_reaches_an_unnumbered_run_that_was_never_named(
    owned_user, owned_library, game
):
    """The refusal takes a name away; it does not repeat a blank."""
    _track(owned_user, owned_library, game)
    imported = _imported_run(owned_user, owned_library)

    result = _describe(owned_user, owned_library, imported, name="", note="from before")

    assert result.outcome is CommandOutcome.APPENDED
    assert Playthrough.objects.get(pk=imported.pk).note == "from before"


@pytest.mark.django_db(transaction=True)
def test_an_unnumbered_run_states_an_endpoint_like_any_other(
    owned_user, owned_library, game
):
    """The kind refuses one value of one fact, and nothing else."""
    _track(owned_user, owned_library, game)
    imported = _imported_run(owned_user, owned_library)
    _start(owned_user, owned_library, imported, when=TemporalValue.from_year(2019))

    result = _correct_start(
        owned_user, owned_library, imported, when=TemporalValue.from_year(2018)
    )

    assert result.outcome is CommandOutcome.APPENDED
    assert Playthrough.objects.get(pk=imported.pk).started == TemporalValue.from_year(
        2018
    )


@pytest.mark.django_db(transaction=True)
def test_describing_a_run_of_another_library_is_refused(
    owned_user, owned_library, django_user_model
):
    """A refusal names no id, and leaks no row."""
    stranger = django_user_model.objects.create_user(username="stranger", password="p")
    elsewhere = Game.objects.create(library=stranger.library, name="Tunic")
    tracked = PlayerGame.objects.create(
        id=uuid.uuid7(),
        library=stranger.library,
        game=elsewhere,
        tracked_at=timezone.now(),
    )
    hidden = Playthrough.objects.create(
        id=uuid.uuid7(),
        library=stranger.library,
        player_game=tracked,
        kind=PlaythroughKind.ORDINARY,
        created_at=timezone.now(),
    )

    with pytest.raises(CommandRejected) as refusal:
        _describe(owned_user, owned_library, hidden, name="Ironman", note=None)

    assert refusal.value.sentence == "That playthrough is not available."


@pytest.mark.django_db(transaction=True)
def test_describing_a_run_of_a_removed_game_is_refused(owned_user, owned_library, game):
    _track(owned_user, owned_library, game)
    run = Playthrough.objects.get()
    tracked = PlayerGame.objects.get()
    PlayerGame.objects.filter(pk=tracked.pk).update(removed_at=tracked.tracked_at)

    with pytest.raises(CommandRejected) as refusal:
        _describe(owned_user, owned_library, run, name="Ironman", note=None)

    assert refusal.value.sentence == (
        "That game was removed from your library. Restore it before recording this."
    )


@pytest.mark.django_db(transaction=True)
def test_describing_a_removed_run_is_refused(owned_user, owned_library, game):
    _track(owned_user, owned_library, game)
    run = _second_run(owned_user, owned_library)
    _remove(owned_user, owned_library, run, key="removal")

    with pytest.raises(CommandRejected) as refusal:
        _describe(owned_user, owned_library, run, name="Ironman", note=None)

    assert refusal.value.sentence == (
        "That playthrough was removed from your library. Restore it before "
        "recording this."
    )


def _correct_start(
    owned_user, owned_library, playthrough, *, when, note="", key="correct-start"
):
    return dispatch(
        CorrectPlaythroughStart(playthrough_id=playthrough.pk, when=when, note=note),
        actor=owned_user,
        library=owned_library,
        idempotency_key=key,
    )


def _correct_completion(
    owned_user, owned_library, playthrough, *, when, note="", key="correct-done"
):
    return dispatch(
        CorrectPlaythroughCompletion(
            playthrough_id=playthrough.pk, when=when, note=note
        ),
        actor=owned_user,
        library=owned_library,
        idempotency_key=key,
    )


@pytest.mark.django_db(transaction=True)
def test_correcting_an_endpoint_that_was_never_stated_is_refused(
    owned_user, owned_library, game
):
    """The values match a row that never started; the marker says so."""
    _track(owned_user, owned_library, game)
    run = Playthrough.objects.get()

    with pytest.raises(CommandRejected) as refusal:
        _correct_start(owned_user, owned_library, run, when=None, note="")

    assert refusal.value.sentence == (
        "This run has no start to correct. Record that it started first."
    )
    assert (
        LibraryEvent.objects.filter(
            event_type="library.playthrough.start_corrected"
        ).count()
        == 0
    )


@pytest.mark.django_db(transaction=True)
def test_correcting_a_completion_that_was_never_stated_is_refused(
    owned_user, owned_library, game
):
    _track(owned_user, owned_library, game)
    run = Playthrough.objects.get()

    with pytest.raises(CommandRejected) as refusal:
        _correct_completion(owned_user, owned_library, run, when=None, note="")

    assert refusal.value.sentence == (
        "This run has no completion to correct. Record that it finished first."
    )


@pytest.mark.django_db(transaction=True)
def test_a_correction_leaves_the_instant_the_act_was_recorded(
    owned_user, owned_library, game
):
    _track(owned_user, owned_library, game)
    run = Playthrough.objects.get()
    _start(owned_user, owned_library, run, when=TemporalValue.from_year(2023))
    stated_at = Playthrough.objects.get().start_recorded_at

    _correct_start(owned_user, owned_library, run, when=TemporalValue.from_year(2024))

    corrected = Playthrough.objects.get()
    assert corrected.start_recorded_at == stated_at
    assert corrected.started == TemporalValue.from_year(2024)


@pytest.mark.django_db(transaction=True)
def test_correcting_a_start_records_the_date_as_the_effective_time(
    owned_user, owned_library, game
):
    _track(owned_user, owned_library, game)
    run = Playthrough.objects.get()
    _start(owned_user, owned_library, run, when=TemporalValue.from_year(2023))

    result = _correct_start(
        owned_user, owned_library, run, when=TemporalValue.from_month(2024, 3)
    )

    assert result.outcome is CommandOutcome.APPENDED
    event = LibraryEvent.objects.get(event_type="library.playthrough.start_corrected")
    assert event.aggregate_id == run.pk
    assert event.effective_time == TemporalValue.from_month(2024, 3)
    assert event.payload == {"note": ""}


@pytest.mark.django_db(transaction=True)
def test_correcting_only_the_note_of_a_start_is_recorded(
    owned_user, owned_library, game
):
    """The endpoint is the pair, so its note is corrected alike."""
    when = TemporalValue.from_year(2023)
    _track(owned_user, owned_library, game)
    run = Playthrough.objects.get()
    _start(owned_user, owned_library, run, when=when, note="blind")

    _correct_start(owned_user, owned_library, run, when=when, note="second try")

    corrected = Playthrough.objects.get()
    assert (corrected.started, corrected.start_note) == (when, "second try")


@pytest.mark.django_db(transaction=True)
def test_correcting_a_start_to_an_unknown_day_keeps_the_act(
    owned_user, owned_library, game
):
    """The day was wrong, and the run still began."""
    _track(owned_user, owned_library, game)
    run = Playthrough.objects.get()
    _start(owned_user, owned_library, run, when=TemporalValue.from_year(2023))

    _correct_start(owned_user, owned_library, run, when=None)

    corrected = Playthrough.objects.get()
    assert corrected.started is None
    assert corrected.start_recorded_at is not None


@pytest.mark.django_db(transaction=True)
def test_correcting_a_start_to_what_it_states_changes_nothing(
    owned_user, owned_library, game
):
    when = TemporalValue.from_year(2023)
    _track(owned_user, owned_library, game)
    run = Playthrough.objects.get()
    _start(owned_user, owned_library, run, when=when, note="blind")

    result = _correct_start(owned_user, owned_library, run, when=when, note="blind")

    assert result.outcome is CommandOutcome.UNCHANGED
    #: Its own reason, so a log names the branch that decided.
    assert result.reason == "This correction states the start the run states."
    assert not LibraryEvent.objects.filter(
        event_type="library.playthrough.start_corrected"
    ).exists()


@pytest.mark.django_db(transaction=True)
def test_an_unknown_day_restates_a_dateless_start_correction(
    owned_user, owned_library, game
):
    """Two spellings of no day, and one fact between them."""
    _track(owned_user, owned_library, game)
    run = Playthrough.objects.get()
    _start(owned_user, owned_library, run, when=None)
    _correct_start(owned_user, owned_library, run, when=TemporalValue.from_year(2023))

    result = _correct_start(owned_user, owned_library, run, when=None, key="cleared")

    assert result.outcome is CommandOutcome.APPENDED
    assert Playthrough.objects.get().started is None


@pytest.mark.django_db(transaction=True)
def test_an_unknown_day_states_the_dateless_start_a_run_states(
    owned_user, owned_library, game
):
    """The other spelling of no day, and the same fact."""
    _track(owned_user, owned_library, game)
    run = Playthrough.objects.get()
    _start(owned_user, owned_library, run, when=None)
    _correct_start(owned_user, owned_library, run, when=TemporalValue.from_year(2023))
    _correct_start(owned_user, owned_library, run, when=None, key="cleared")

    again = _correct_start(
        owned_user,
        owned_library,
        run,
        when=TemporalValue.unknown(),
        key="cleared-again",
    )

    assert again.outcome is CommandOutcome.UNCHANGED


@pytest.mark.django_db(transaction=True)
def test_correcting_a_completion_records_the_date_and_the_note(
    owned_user, owned_library, game
):
    _track(owned_user, owned_library, game)
    run = Playthrough.objects.get()
    _complete(owned_user, owned_library, run, when=TemporalValue.from_year(2023))

    result = _correct_completion(
        owned_user,
        owned_library,
        run,
        when=TemporalValue.from_day(date(2024, 4, 2)),
        note="hard mode",
    )

    assert result.outcome is CommandOutcome.APPENDED
    corrected = Playthrough.objects.get()
    assert corrected.completed == TemporalValue.from_day(date(2024, 4, 2))
    assert corrected.completion_note == "hard mode"


@pytest.mark.django_db(transaction=True)
def test_correcting_only_the_note_of_a_completion_is_recorded(
    owned_user, owned_library, game
):
    """The far endpoint is the pair too, so its note is corrected alike."""
    when = TemporalValue.from_year(2023)
    _track(owned_user, owned_library, game)
    run = Playthrough.objects.get()
    _complete(owned_user, owned_library, run, when=when, note="rushed")

    _correct_completion(owned_user, owned_library, run, when=when, note="hard mode")

    corrected = Playthrough.objects.get()
    assert (corrected.completed, corrected.completion_note) == (when, "hard mode")


@pytest.mark.django_db(transaction=True)
def test_correcting_a_completion_to_what_it_states_changes_nothing(
    owned_user, owned_library, game
):
    when = TemporalValue.from_year(2023)
    _track(owned_user, owned_library, game)
    run = Playthrough.objects.get()
    _complete(owned_user, owned_library, run, when=when, note="done")

    result = _correct_completion(owned_user, owned_library, run, when=when, note="done")

    assert result.outcome is CommandOutcome.UNCHANGED
    assert result.reason == "This correction states the completion the run states."


@pytest.mark.django_db(transaction=True)
def test_a_note_of_spaces_states_the_endpoint_the_run_states(
    owned_user, owned_library, game
):
    """The endpoint note is stripped, or a blank appends an event."""
    when = TemporalValue.from_year(2023)
    _track(owned_user, owned_library, game)
    run = Playthrough.objects.get()
    _start(owned_user, owned_library, run, when=when, note="blind")

    result = _correct_start(owned_user, owned_library, run, when=when, note=" blind ")

    assert result.outcome is CommandOutcome.UNCHANGED


@pytest.mark.django_db(transaction=True)
def test_a_correction_between_the_two_endpoints_is_recorded(
    owned_user, owned_library, game
):
    """The order rule reads the stored far end, and passes here."""
    _track(owned_user, owned_library, game)
    run = Playthrough.objects.get()
    _start(owned_user, owned_library, run, when=TemporalValue.from_year(2022))
    _complete(owned_user, owned_library, run, when=TemporalValue.from_year(2024))

    result = _correct_start(
        owned_user, owned_library, run, when=TemporalValue.from_year(2023)
    )

    assert result.outcome is CommandOutcome.APPENDED
    assert Playthrough.objects.get().started == TemporalValue.from_year(2023)


@pytest.mark.django_db(transaction=True)
def test_clearing_a_start_beside_a_stated_completion_is_recorded(
    owned_user, owned_library, game
):
    """No day bounds nothing, so the far end refuses nothing."""
    _track(owned_user, owned_library, game)
    run = Playthrough.objects.get()
    _start(owned_user, owned_library, run, when=TemporalValue.from_year(2022))
    _complete(owned_user, owned_library, run, when=TemporalValue.from_year(2024))

    result = _correct_start(owned_user, owned_library, run, when=None)

    assert result.outcome is CommandOutcome.APPENDED
    corrected = Playthrough.objects.get()
    assert corrected.started is None
    assert corrected.completed == TemporalValue.from_year(2024)


@pytest.mark.django_db(transaction=True)
def test_a_start_never_stated_is_refused_before_the_order_rule(
    owned_user, owned_library, game
):
    """The marker refusal stands first, so it names the missing act."""
    _track(owned_user, owned_library, game)
    run = Playthrough.objects.get()
    _complete(owned_user, owned_library, run, when=TemporalValue.from_year(2023))

    with pytest.raises(CommandRejected) as refusal:
        _correct_start(
            owned_user, owned_library, run, when=TemporalValue.from_year(2025)
        )

    assert refusal.value.sentence == (
        "This run has no start to correct. Record that it started first."
    )


@pytest.mark.django_db(transaction=True)
def test_correcting_a_start_past_the_completion_is_refused(
    owned_user, owned_library, game
):
    _track(owned_user, owned_library, game)
    run = Playthrough.objects.get()
    _start(owned_user, owned_library, run, when=TemporalValue.from_year(2023))
    _complete(owned_user, owned_library, run, when=TemporalValue.from_year(2024))

    with pytest.raises(CommandRejected) as refusal:
        _correct_start(
            owned_user, owned_library, run, when=TemporalValue.from_year(2025)
        )

    assert refusal.value.sentence == (
        "This run finished before that date. Check the day."
    )


@pytest.mark.django_db(transaction=True)
def test_correcting_a_completion_before_the_start_is_refused(
    owned_user, owned_library, game
):
    _track(owned_user, owned_library, game)
    run = Playthrough.objects.get()
    _start(owned_user, owned_library, run, when=TemporalValue.from_year(2024))
    _complete(owned_user, owned_library, run, when=TemporalValue.from_year(2025))

    with pytest.raises(CommandRejected) as refusal:
        _correct_completion(
            owned_user, owned_library, run, when=TemporalValue.from_year(2023)
        )

    assert refusal.value.sentence == (
        "This run started after that date. Check the day."
    )


@pytest.mark.django_db(transaction=True)
def test_correcting_an_endpoint_of_another_library_is_refused(
    owned_user, owned_library, django_user_model
):
    """A refusal names no id, and leaks no row."""
    stranger = django_user_model.objects.create_user(username="stranger", password="p")
    elsewhere = Game.objects.create(library=stranger.library, name="Tunic")
    tracked = PlayerGame.objects.create(
        id=uuid.uuid7(),
        library=stranger.library,
        game=elsewhere,
        tracked_at=timezone.now(),
    )
    hidden = Playthrough.objects.create(
        id=uuid.uuid7(),
        library=stranger.library,
        player_game=tracked,
        kind=PlaythroughKind.ORDINARY,
        created_at=timezone.now(),
    )

    with pytest.raises(CommandRejected) as refusal:
        _correct_start(owned_user, owned_library, hidden, when=None)

    assert refusal.value.sentence == "That playthrough is not available."


@pytest.mark.django_db(transaction=True)
def test_correcting_an_endpoint_of_a_removed_game_is_refused(
    owned_user, owned_library, game
):
    _track(owned_user, owned_library, game)
    run = Playthrough.objects.get()
    _start(owned_user, owned_library, run, when=TemporalValue.from_year(2023))
    tracked = PlayerGame.objects.get()
    PlayerGame.objects.filter(pk=tracked.pk).update(removed_at=tracked.tracked_at)

    with pytest.raises(CommandRejected) as refusal:
        _correct_start(owned_user, owned_library, run, when=None)

    assert refusal.value.sentence == (
        "That game was removed from your library. Restore it before recording this."
    )


@pytest.mark.django_db(transaction=True)
def test_correcting_an_endpoint_of_a_removed_run_is_refused(
    owned_user, owned_library, game
):
    _track(owned_user, owned_library, game)
    run = _second_run(owned_user, owned_library)
    _start(owned_user, owned_library, run, when=TemporalValue.from_year(2023))
    _remove(owned_user, owned_library, run, key="removal")

    with pytest.raises(CommandRejected) as refusal:
        _correct_start(owned_user, owned_library, run, when=None)

    assert refusal.value.sentence == (
        "That playthrough was removed from your library. Restore it before "
        "recording this."
    )


@pytest.mark.django_db(transaction=True)
def test_a_repeated_description_under_one_key_records_nothing_further(
    owned_user, owned_library, game
):
    _track(owned_user, owned_library, game)
    run = Playthrough.objects.get()
    _describe(owned_user, owned_library, run, name="Ironman", note="no saves")

    result = _describe(owned_user, owned_library, run, name="Ironman", note="no saves")

    assert result.outcome is CommandOutcome.REPLAYED
    assert (
        LibraryEvent.objects.filter(
            event_type="library.playthrough.name_changed"
        ).count()
        == 1
    )


@pytest.mark.django_db(transaction=True)
def test_a_repeated_correction_under_one_key_records_nothing_further(
    owned_user, owned_library, game
):
    _track(owned_user, owned_library, game)
    run = Playthrough.objects.get()
    _start(owned_user, owned_library, run, when=TemporalValue.from_year(2023))
    when = TemporalValue.from_year(2024)
    _correct_start(owned_user, owned_library, run, when=when)

    result = _correct_start(owned_user, owned_library, run, when=when)

    assert result.outcome is CommandOutcome.REPLAYED
    assert (
        LibraryEvent.objects.filter(
            event_type="library.playthrough.start_corrected"
        ).count()
        == 1
    )


@pytest.mark.django_db(transaction=True)
def test_a_repeated_completion_correction_under_one_key_records_nothing_further(
    owned_user, owned_library, game
):
    _track(owned_user, owned_library, game)
    run = Playthrough.objects.get()
    _complete(owned_user, owned_library, run, when=TemporalValue.from_year(2023))
    when = TemporalValue.from_year(2024)
    _correct_completion(owned_user, owned_library, run, when=when)

    result = _correct_completion(owned_user, owned_library, run, when=when)

    assert result.outcome is CommandOutcome.REPLAYED
    assert (
        LibraryEvent.objects.filter(
            event_type="library.playthrough.completion_corrected"
        ).count()
        == 1
    )


@pytest.mark.django_db(transaction=True)
def test_an_unknown_day_fingerprints_as_a_dateless_correction(
    owned_user, owned_library, game
):
    """One key, two spellings, and no mismatch between them."""
    _track(owned_user, owned_library, game)
    run = Playthrough.objects.get()
    _start(owned_user, owned_library, run, when=TemporalValue.from_year(2023))
    _correct_start(owned_user, owned_library, run, when=None)

    result = _correct_start(
        owned_user, owned_library, run, when=TemporalValue.unknown()
    )

    assert result.outcome is CommandOutcome.REPLAYED
    assert (
        LibraryEvent.objects.filter(
            event_type="library.playthrough.start_corrected"
        ).count()
        == 1
    )


@pytest.mark.django_db(transaction=True)
def test_a_cleared_name_fingerprints_apart_from_no_name(
    owned_user, owned_library, game
):
    """Two answers, so two fingerprints: one clears, one states nothing."""
    _track(owned_user, owned_library, game)
    run = Playthrough.objects.get()
    _describe(owned_user, owned_library, run, name=None, note="no saves")

    with pytest.raises(IdempotencyKeyMismatch):
        _describe(owned_user, owned_library, run, name="", note="no saves")


@pytest.mark.django_db(transaction=True)
def test_a_cleared_note_fingerprints_apart_from_no_note(
    owned_user, owned_library, game
):
    """The note reads the same two ways as the name."""
    _track(owned_user, owned_library, game)
    run = Playthrough.objects.get()
    _describe(owned_user, owned_library, run, name="Ironman", note=None)

    with pytest.raises(IdempotencyKeyMismatch):
        _describe(owned_user, owned_library, run, name="Ironman", note="")


def _second_run(owned_user, owned_library, key="second-run"):
    """A run the last-run rule does not protect."""
    game = Game.objects.get()
    #: CommandResult carries no events; diff the rows.
    before = set(Playthrough.objects.values_list("pk", flat=True))
    dispatch(
        CreatePlaythrough(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key=key,
    )
    return Playthrough.objects.exclude(pk__in=before).get()


def _remove(owned_user, owned_library, playthrough, key="remove"):
    return dispatch(
        RemovePlaythrough(playthrough_id=playthrough.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key=key,
    )


def _restore(owned_user, owned_library, playthrough, key="restore"):
    return dispatch(
        RestorePlaythrough(playthrough_id=playthrough.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key=key,
    )


@pytest.mark.django_db(transaction=True)
def test_removing_a_run_stamps_the_column(owned_user, owned_library, game):
    _track(owned_user, owned_library, game)
    run = _second_run(owned_user, owned_library)

    result = _remove(owned_user, owned_library, run)

    assert result.outcome is CommandOutcome.APPENDED
    run.refresh_from_db()
    assert run.removed_at is not None


@pytest.mark.django_db(transaction=True)
def test_removing_a_run_a_second_time_changes_nothing(owned_user, owned_library, game):
    """A no-op is a success recording no event, per #906."""
    _track(owned_user, owned_library, game)
    run = _second_run(owned_user, owned_library)
    _remove(owned_user, owned_library, run)

    result = _remove(owned_user, owned_library, run, key="remove-again")

    assert result.outcome is CommandOutcome.UNCHANGED
    assert (
        LibraryEvent.objects.filter(event_type="library.playthrough.removed").count()
        == 1
    )


@pytest.mark.django_db(transaction=True)
def test_one_idempotency_key_records_one_removal(owned_user, owned_library, game):
    """The key names the request, so a repeat replays the record."""
    _track(owned_user, owned_library, game)
    run = _second_run(owned_user, owned_library)
    _remove(owned_user, owned_library, run, key="once")

    result = _remove(owned_user, owned_library, run, key="once")

    assert result.outcome is CommandOutcome.REPLAYED
    assert (
        LibraryEvent.objects.filter(event_type="library.playthrough.removed").count()
        == 1
    )


@pytest.mark.django_db(transaction=True)
def test_restoring_a_run_clears_the_column(owned_user, owned_library, game):
    _track(owned_user, owned_library, game)
    run = _second_run(owned_user, owned_library)
    _remove(owned_user, owned_library, run)

    result = _restore(owned_user, owned_library, run)

    assert result.outcome is CommandOutcome.APPENDED
    run.refresh_from_db()
    assert run.removed_at is None


@pytest.mark.django_db(transaction=True)
def test_restoring_a_live_run_changes_nothing(owned_user, owned_library, game):
    _track(owned_user, owned_library, game)
    run = Playthrough.objects.get()

    result = _restore(owned_user, owned_library, run)

    assert result.outcome is CommandOutcome.UNCHANGED
    assert not LibraryEvent.objects.filter(
        event_type="library.playthrough.restored"
    ).exists()


@pytest.mark.django_db(transaction=True)
def test_removing_a_run_of_another_library_is_refused(
    owned_user, owned_library, django_user_model
):
    """A refusal is not a place to learn an id."""
    stranger = django_user_model.objects.create_user(username="stranger", password="p")
    elsewhere = Game.objects.create(library=stranger.library, name="Tunic")
    tracked = PlayerGame.objects.create(
        id=uuid.uuid7(),
        library=stranger.library,
        game=elsewhere,
        tracked_at=timezone.now(),
    )
    hidden = Playthrough.objects.create(
        id=uuid.uuid7(),
        library=stranger.library,
        player_game=tracked,
        kind=PlaythroughKind.ORDINARY,
        created_at=timezone.now(),
    )

    with pytest.raises(CommandRejected) as refusal:
        _remove(owned_user, owned_library, hidden, key="foreign")

    assert refusal.value.sentence == "That playthrough is not available."


@pytest.mark.django_db(transaction=True)
def test_removing_a_run_of_a_removed_game_is_refused(owned_user, owned_library, game):
    _track(owned_user, owned_library, game)
    run = _second_run(owned_user, owned_library)
    tracked = PlayerGame.objects.get()
    PlayerGame.objects.filter(pk=tracked.pk).update(removed_at=tracked.tracked_at)

    with pytest.raises(CommandRejected) as refusal:
        _remove(owned_user, owned_library, run, key="parent-gone")

    assert refusal.value.sentence == (
        "That game was removed from your library. Restore it before changing "
        "its playthroughs."
    )


@pytest.mark.django_db(transaction=True)
def test_restoring_a_run_of_a_removed_game_is_refused(owned_user, owned_library, game):
    """The way out: restore the game first."""
    _track(owned_user, owned_library, game)
    run = _second_run(owned_user, owned_library)
    _remove(owned_user, owned_library, run)
    tracked = PlayerGame.objects.get()
    PlayerGame.objects.filter(pk=tracked.pk).update(removed_at=tracked.tracked_at)

    with pytest.raises(CommandRejected) as refusal:
        _restore(owned_user, owned_library, run, key="parent-gone")

    assert refusal.value.sentence == (
        "That game was removed from your library. Restore it before changing "
        "its playthroughs."
    )


@pytest.mark.django_db(transaction=True)
def test_removing_a_removed_run_of_a_removed_game_changes_nothing(
    owned_user, owned_library, game
):
    """#906: the no-op is read before the game's mark.

    A retry after the game went is a success, not advice to
    restore a game the caller never touched.
    """
    _track(owned_user, owned_library, game)
    run = _second_run(owned_user, owned_library)
    _remove(owned_user, owned_library, run)
    tracked = PlayerGame.objects.get()
    PlayerGame.objects.filter(pk=tracked.pk).update(removed_at=tracked.tracked_at)

    result = _remove(owned_user, owned_library, run, key="retry")

    assert result.outcome is CommandOutcome.UNCHANGED
    assert (
        LibraryEvent.objects.filter(event_type="library.playthrough.removed").count()
        == 1
    )


@pytest.mark.django_db(transaction=True)
def test_restoring_a_live_run_of_a_removed_game_changes_nothing(
    owned_user, owned_library, game
):
    """The same order in the other command."""
    _track(owned_user, owned_library, game)
    run = _second_run(owned_user, owned_library)
    tracked = PlayerGame.objects.get()
    PlayerGame.objects.filter(pk=tracked.pk).update(removed_at=tracked.tracked_at)

    result = _restore(owned_user, owned_library, run, key="already-here")

    assert result.outcome is CommandOutcome.UNCHANGED
    assert not LibraryEvent.objects.filter(
        event_type="library.playthrough.restored"
    ).exists()


@pytest.mark.django_db(transaction=True)
def test_one_idempotency_key_records_one_restoration(owned_user, owned_library, game):
    """The key names the request, as it does for a removal."""
    _track(owned_user, owned_library, game)
    run = _second_run(owned_user, owned_library)
    _remove(owned_user, owned_library, run)
    _restore(owned_user, owned_library, run, key="once")

    result = _restore(owned_user, owned_library, run, key="once")

    assert result.outcome is CommandOutcome.REPLAYED
    assert (
        LibraryEvent.objects.filter(event_type="library.playthrough.restored").count()
        == 1
    )


@pytest.mark.django_db(transaction=True)
def test_restoring_a_run_a_second_time_changes_nothing(owned_user, owned_library, game):
    """A mis-click states nothing twice."""
    _track(owned_user, owned_library, game)
    run = _second_run(owned_user, owned_library)
    _remove(owned_user, owned_library, run)
    _restore(owned_user, owned_library, run)

    result = _restore(owned_user, owned_library, run, key="restore-again")

    assert result.outcome is CommandOutcome.UNCHANGED
    assert (
        LibraryEvent.objects.filter(event_type="library.playthrough.restored").count()
        == 1
    )


@pytest.mark.django_db(transaction=True)
def test_removing_the_only_ordinary_run_is_refused(owned_user, owned_library, game):
    """Every tracked game keeps a Playthrough 1."""
    _track(owned_user, owned_library, game)
    run = Playthrough.objects.get()

    with pytest.raises(CommandRejected) as refusal:
        _remove(owned_user, owned_library, run, key="last")

    assert refusal.value.sentence == (
        "This is the only playthrough of that game, and a tracked game keeps "
        "one. Remove the game itself instead."
    )


@pytest.mark.django_db(transaction=True)
def test_removing_a_run_beside_a_live_sibling_is_allowed(
    owned_user, owned_library, game
):
    _track(owned_user, owned_library, game)
    run = _second_run(owned_user, owned_library)

    result = _remove(owned_user, owned_library, run)

    assert result.outcome is CommandOutcome.APPENDED


@pytest.mark.django_db(transaction=True)
def test_a_removed_sibling_does_not_keep_the_last_run_removable(
    owned_user, owned_library, game
):
    """The rule counts live rows only."""
    _track(owned_user, owned_library, game)
    second = _second_run(owned_user, owned_library)
    _remove(owned_user, owned_library, second, key="first-removal")
    first = Playthrough.objects.get(removed_at__isnull=True)

    with pytest.raises(CommandRejected) as refusal:
        _remove(owned_user, owned_library, first, key="second-removal")

    assert refusal.value.sentence == (
        "This is the only playthrough of that game, and a tracked game keeps "
        "one. Remove the game itself instead."
    )


@pytest.mark.django_db(transaction=True)
def test_a_bucket_does_not_keep_an_ordinary_run_removable(
    owned_user, owned_library, game
):
    """No display number is counted across a bucket."""
    _track(owned_user, owned_library, game)
    _imported_run(owned_user, owned_library)
    ordinary = Playthrough.objects.get(kind=PlaythroughKind.ORDINARY)

    with pytest.raises(CommandRejected) as refusal:
        _remove(owned_user, owned_library, ordinary, key="last-ordinary")

    assert refusal.value.sentence == (
        "This is the only playthrough of that game, and a tracked game keeps "
        "one. Remove the game itself instead."
    )


@pytest.mark.django_db(transaction=True)
def test_a_bucket_is_removable_from_a_game_with_no_ordinary_run(
    owned_user, owned_library, game
):
    """A bucket takes no ordinary run away."""
    _track(owned_user, owned_library, game)
    bucket = _imported_run(owned_user, owned_library)
    Playthrough.objects.filter(kind=PlaythroughKind.ORDINARY).update(
        removed_at=timezone.now()
    )

    result = _remove(owned_user, owned_library, bucket, key="bucket")

    assert result.outcome is CommandOutcome.APPENDED


@pytest.mark.django_db(transaction=True)
def test_a_removed_game_is_the_refusal_a_last_run_hears(
    owned_user, owned_library, game
):
    """Two rules apply; the earlier one states the way out."""
    _track(owned_user, owned_library, game)
    run = Playthrough.objects.get()
    tracked = PlayerGame.objects.get()
    PlayerGame.objects.filter(pk=tracked.pk).update(removed_at=tracked.tracked_at)

    with pytest.raises(CommandRejected) as refusal:
        _remove(owned_user, owned_library, run, key="both")

    assert refusal.value.sentence == (
        "That game was removed from your library. Restore it before changing "
        "its playthroughs."
    )


@pytest.mark.django_db(transaction=True)
def test_a_foreign_run_at_the_same_game_does_not_keep_the_last_run_removable(
    owned_user, owned_library, game, django_user_model
):
    """The sibling count is scoped on the library.

    A run naming another library's PlayerGame is the drift
    `audit_library_ownership` reports. Counting it would let this
    library take its own last run off a game it still tracks.
    """
    _track(owned_user, owned_library, game)
    run = Playthrough.objects.get()
    stranger = django_user_model.objects.create_user(username="stranger", password="p")
    Playthrough.objects.create(
        id=uuid.uuid7(),
        library=stranger.library,
        player_game=run.player_game,
        kind=PlaythroughKind.ORDINARY,
        created_at=timezone.now(),
    )

    with pytest.raises(CommandRejected) as refusal:
        _remove(owned_user, owned_library, run, key="drift")

    assert refusal.value.sentence == (
        "This is the only playthrough of that game, and a tracked game keeps "
        "one. Remove the game itself instead."
    )


@pytest.fixture
def referring_models():
    """Two throwaway projections naming a run, as #701's will."""
    with isolate_apps("games"):

        class Assignment(ProjectionModel):
            id = models.UUIDField(primary_key=True, default=uuid.uuid7)
            playthrough = models.ForeignKey(Playthrough, on_delete=models.RESTRICT)
            removed_at = models.DateTimeField(null=True, default=None)

            objects = RemovableLibraryQuerySet.as_manager()

            class Meta:
                app_label = "games"
                db_table = "test_playthrough_assignment"

        class Bookmark(ProjectionModel):
            id = models.UUIDField(primary_key=True, default=uuid.uuid7)
            playthrough = models.ForeignKey(Playthrough, on_delete=models.RESTRICT)
            removed_at = models.DateTimeField(null=True, default=None)

            objects = RemovableLibraryQuerySet.as_manager()

            class Meta:
                app_label = "games"
                db_table = "test_playthrough_bookmark"

        built = (Assignment, Bookmark)
        with connection.schema_editor() as schema_editor:
            for model in built:
                schema_editor.create_model(model)
        try:
            yield built
        finally:
            with connection.schema_editor() as schema_editor:
                for model in reversed(built):
                    schema_editor.delete_model(model)


def _register(monkeypatch, *referrers):
    monkeypatch.setattr(playthrough_commands, "BLOCKING_REFERRERS", referrers)


ASSIGNED_SENTENCE = (
    "Sessions are assigned to this playthrough. Move them before removing it."
)


@pytest.mark.django_db(transaction=True)
def test_a_registered_referrer_keeps_a_run_in_place(
    owned_user, owned_library, game, monkeypatch, referring_models
):
    """Inert on delivery: #700 and #701 supply the first entry."""
    assignment_model, _ = referring_models
    _track(owned_user, owned_library, game)
    run = _second_run(owned_user, owned_library)
    assignment_model.objects.create(playthrough=run, library=owned_library)
    _register(
        monkeypatch,
        BlockingReferrer.on(
            assignment_model, "playthrough", sentence=ASSIGNED_SENTENCE
        ),
    )

    with pytest.raises(CommandRejected) as refusal:
        _remove(owned_user, owned_library, run, key="blocked")

    assert refusal.value.sentence == ASSIGNED_SENTENCE


@pytest.mark.django_db(transaction=True)
def test_a_removed_referring_row_keeps_nothing_in_place(
    owned_user, owned_library, game, monkeypatch, referring_models
):
    """A removed referrer blocks nothing."""
    assignment_model, _ = referring_models
    _track(owned_user, owned_library, game)
    run = _second_run(owned_user, owned_library)
    assignment_model.objects.create(
        playthrough=run, library=owned_library, removed_at=timezone.now()
    )
    _register(
        monkeypatch,
        BlockingReferrer.on(assignment_model, "playthrough", sentence="unused"),
    )

    result = _remove(owned_user, owned_library, run, key="not-blocked")

    assert result.outcome is CommandOutcome.APPENDED


@pytest.mark.django_db(transaction=True)
def test_a_later_entry_answers_where_the_first_names_nothing(
    owned_user, owned_library, game, monkeypatch, referring_models
):
    """The walk does not stop at the first entry."""
    assignment_model, bookmark_model = referring_models
    _track(owned_user, owned_library, game)
    run = _second_run(owned_user, owned_library)
    bookmark_model.objects.create(playthrough=run, library=owned_library)
    _register(
        monkeypatch,
        BlockingReferrer.on(
            assignment_model, "playthrough", sentence=ASSIGNED_SENTENCE
        ),
        BlockingReferrer.on(
            bookmark_model, "playthrough", sentence="Bookmarks name this playthrough."
        ),
    )

    with pytest.raises(CommandRejected) as refusal:
        _remove(owned_user, owned_library, run, key="second-entry")

    assert refusal.value.sentence == "Bookmarks name this playthrough."


@pytest.mark.django_db(transaction=True)
def test_the_first_naming_entry_is_the_one_a_person_hears(
    owned_user, owned_library, game, monkeypatch, referring_models
):
    """Two rows name the run; the registry states the order."""
    assignment_model, bookmark_model = referring_models
    _track(owned_user, owned_library, game)
    run = _second_run(owned_user, owned_library)
    assignment_model.objects.create(playthrough=run, library=owned_library)
    bookmark_model.objects.create(playthrough=run, library=owned_library)
    _register(
        monkeypatch,
        BlockingReferrer.on(
            assignment_model, "playthrough", sentence=ASSIGNED_SENTENCE
        ),
        BlockingReferrer.on(
            bookmark_model, "playthrough", sentence="Bookmarks name this playthrough."
        ),
    )

    with pytest.raises(CommandRejected) as refusal:
        _remove(owned_user, owned_library, run, key="both-name-it")

    assert refusal.value.sentence == ASSIGNED_SENTENCE


@pytest.mark.django_db(transaction=True)
def test_a_foreign_referring_row_keeps_nothing_in_place(
    owned_user, owned_library, game, monkeypatch, referring_models, django_user_model
):
    """The lookup is scoped, as the sibling count is.

    A row of another library naming this run is the drift
    `audit_library_ownership` reports, and "move your sessions"
    is advice about rows this person cannot reach.
    """
    assignment_model, _ = referring_models
    _track(owned_user, owned_library, game)
    run = _second_run(owned_user, owned_library)
    stranger = django_user_model.objects.create_user(username="stranger", password="p")
    assignment_model.objects.create(playthrough=run, library=stranger.library)
    _register(
        monkeypatch,
        BlockingReferrer.on(
            assignment_model, "playthrough", sentence=ASSIGNED_SENTENCE
        ),
    )

    result = _remove(owned_user, owned_library, run, key="foreign-referrer")

    assert result.outcome is CommandOutcome.APPENDED


def test_a_referrer_whose_reads_keep_removed_rows_is_refused():
    """A row nobody can remove would block forever."""
    with isolate_apps("games"):

        class Unmarked(ProjectionModel):
            id = models.UUIDField(primary_key=True, default=uuid.uuid7)
            playthrough = models.ForeignKey(Playthrough, on_delete=models.RESTRICT)

            class Meta:
                app_label = "games"

        with pytest.raises(TypeError, match="states no alive"):
            BlockingReferrer.on(Unmarked, "playthrough", sentence="unused")


def test_a_referrer_on_a_field_that_is_not_a_key_is_refused():
    """The lookup would raise a FieldError inside build()."""
    with isolate_apps("games"):

        class Mislabeled(ProjectionModel):
            id = models.UUIDField(primary_key=True, default=uuid.uuid7)
            playthrough = models.CharField(max_length=8)
            removed_at = models.DateTimeField(null=True, default=None)

            objects = RemovableLibraryQuerySet.as_manager()

            class Meta:
                app_label = "games"

        with pytest.raises(TypeError, match="is not a foreign key"):
            BlockingReferrer.on(Mislabeled, "playthrough", sentence="unused")


def test_a_referrer_naming_another_model_is_refused():
    """A key to something else answers about the wrong row."""
    with isolate_apps("games"):

        class Misdirected(ProjectionModel):
            id = models.UUIDField(primary_key=True, default=uuid.uuid7)
            playthrough = models.ForeignKey(PlayerGame, on_delete=models.RESTRICT)
            removed_at = models.DateTimeField(null=True, default=None)

            objects = RemovableLibraryQuerySet.as_manager()

            class Meta:
                app_label = "games"

        with pytest.raises(TypeError, match="not a playthrough"):
            BlockingReferrer.on(Misdirected, "playthrough", sentence="unused")


def test_the_delivered_registry_refuses_nothing():
    """Nothing names a run until #700 and #701."""
    assert playthrough_commands.BLOCKING_REFERRERS == ()
