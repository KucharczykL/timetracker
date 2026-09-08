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
    player_game = tracked_game(user.library, game)
    assert player_game is not None
    return live_ordinary_runs(user.library, player_game).get()


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
