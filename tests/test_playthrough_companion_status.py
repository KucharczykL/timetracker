"""#683: the status a lifecycle act offers."""

from datetime import date

import pytest
from django.urls import reverse
from django.utils import timezone

from games.events.rebuild import RebuildMode, rebuild_projections
from games.models import Game, LibraryEvent, PlayerGame, PlayerGameStatus, Playthrough
from games.reads.companion_status import played_is_offered
from games.writes.playergame import new_correlation_id, record_facts, track_game

#: TrackGame states the run itself.
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
    """The Add form, before a game."""
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
    """A checked box would walk it back."""
    state(owned_user, tracked, status)

    assert played_is_offered(owned_library, tracked) is False


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
    """Never rendered, so a posted one drops."""
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
    """Both boxes ticked, neither act stated."""
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


def test_a_note_edit_on_a_finished_run_states_no_status(
    owned_user, logged_in, owned_library, tracked
):
    """The boxes ride a prefilled form, so a note edit reposts both days.

    Restating an endpoint the run already holds records no
    new act, and only a new act implies a status. Otherwise
    fixing a typo would drag Abandoned back to Completed.
    """
    run = Playthrough.objects.get(player_game__game=tracked)
    logged_in.post(
        reverse("games:edit_playthrough", args=[run.pk]),
        {
            "game": str(tracked.pk),
            "started": "2026-01-02",
            "ended": "2026-02-03",
            "note": "",
        },
    )
    state(owned_user, tracked, PlayerGameStatus.ABANDONED)

    logged_in.post(
        reverse("games:edit_playthrough", args=[run.pk]),
        {
            "game": str(tracked.pk),
            "started": "2026-01-02",
            "ended": "2026-02-03",
            "note": "gave up in the tower",
            "also_mark_played": "on",
            "also_mark_completed": "on",
        },
    )

    run.refresh_from_db()
    assert run.note == "gave up in the tower"
    assert status_of(owned_library) == PlayerGameStatus.ABANDONED


def test_adding_a_run_with_no_end_day_finishes_nothing(logged_in, owned_library, game):
    """A run added with no end day is one nobody finished.

    Not one finished on a day nobody wrote down, so the
    ticked box states no completion either.
    """
    logged_in.post(
        reverse("games:add_playthrough"),
        {
            "game": str(game.pk),
            "started": "2026-01-02",
            "ended": "",
            "note": "",
            "also_mark_played": "on",
            "also_mark_completed": "on",
        },
    )

    run = Playthrough.objects.get(player_game__game=game)
    assert run.completion_recorded_at is None
    assert status_of(owned_library) == PlayerGameStatus.PLAYED


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


def test_a_stale_start_press_leaves_the_stated_day(logged_in, owned_library, tracked):
    """A page rendered before the start was stated presses on it anyway.

    The route means "this began today", so a run that already
    states a start is refused. Correcting it instead would
    overwrite a recorded day and answer the person success.
    """
    run = Playthrough.objects.get(player_game__game=tracked)
    logged_in.post(
        reverse("games:edit_playthrough", args=[run.pk]),
        {"game": str(tracked.pk), "started": "2024-01-05", "ended": "", "note": ""},
    )

    logged_in.post(reverse("games:start_playthrough", args=[run.pk]))

    run.refresh_from_db()
    assert run.started_lower == date(2024, 1, 5)


def test_a_stale_completion_press_leaves_the_stated_day(logged_in, tracked):
    run = Playthrough.objects.get(player_game__game=tracked)
    logged_in.post(
        reverse("games:edit_playthrough", args=[run.pk]),
        {
            "game": str(tracked.pk),
            "started": "2024-01-05",
            "ended": "2024-02-06",
            "note": "",
        },
    )

    logged_in.post(reverse("games:complete_playthrough", args=[run.pk]))

    run.refresh_from_db()
    assert run.completed_upper == date(2024, 2, 6)


def test_a_refused_press_tells_the_person_why(logged_in, tracked):
    """The refusal reaches the page the redirect lands on."""
    run = Playthrough.objects.get(player_game__game=tracked)
    logged_in.post(
        reverse("games:edit_playthrough", args=[run.pk]),
        {"game": str(tracked.pk), "started": "2024-01-05", "ended": "", "note": ""},
    )

    response = logged_in.post(
        reverse("games:start_playthrough", args=[run.pk]), follow=True
    )

    assert "This run already has a start." in response.content.decode()


def test_neither_act_answers_a_get(logged_in, tracked):
    run = Playthrough.objects.get(player_game__game=tracked)

    for name in ("games:start_playthrough", "games:complete_playthrough"):
        assert logged_in.get(reverse(name, args=[run.pk])).status_code == 405


def test_an_act_keeps_the_run_note(logged_in, owned_user, owned_library, tracked):
    """The restatement carries the note along."""
    run = Playthrough.objects.get(player_game__game=tracked)
    logged_in.post(
        reverse("games:edit_playthrough", args=[run.pk]),
        {"game": str(tracked.pk), "started": "", "ended": "", "note": "12h"},
    )

    logged_in.post(reverse("games:start_playthrough", args=[run.pk]))

    run.refresh_from_db()
    assert run.note == "12h"


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
