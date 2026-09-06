"""Dispatching the commands that state a run."""

import uuid
from datetime import date

import pytest
from django.utils import timezone

from games.commands.playergame import PlayerGameNotTracked, TrackGame
from games.commands.playthrough import (
    CompletePlaythrough,
    CreatePlaythrough,
    StartPlaythrough,
    endpoints_certainly_reversed,
)
from games.events.dispatch import CommandOutcome, CommandRejected, dispatch
from games.models import (
    Game,
    LibraryEvent,
    PlayerGame,
    Playthrough,
    PlaythroughKind,
)
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
    assert str(hidden.pk) not in refusal.value.sentence


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
    """Inert until #1011 stamps the column, and written here.

    The resolver both commands share is written here, so its answers are
    tested here.
    """
    _track(owned_user, owned_library, game)
    playthrough = Playthrough.objects.get()
    Playthrough.objects.filter(pk=playthrough.pk).update(
        removed_at=playthrough.created_at
    )

    with pytest.raises(CommandRejected) as refusal:
        _start(owned_user, owned_library, playthrough, when=None, key="gone")

    assert refusal.value.sentence == (
        "That playthrough was removed from your library. Restore it before "
        "recording this."
    )
