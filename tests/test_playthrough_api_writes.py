"""#687: the API states runs, not rows."""

from datetime import date

import pytest

from games.backfill.playthrough import convert_library
from games.models import Game, PlayEvent, Playthrough
from games.reads.playthrough_runs import live_ordinary_runs, tracked_game
from timetracker.temporal import TemporalValue


@pytest.fixture
def user(owned_user):
    return owned_user


@pytest.fixture
def game(owned_library):
    return Game.objects.create(library=owned_library, name="Outer Wilds")


def converted_runs(user, game) -> list[Playthrough]:
    """The runs the conversion left for this game, oldest first."""
    player_game = tracked_game(user.library, game)
    assert player_game is not None
    return list(live_ordinary_runs(user.library, player_game))


def run_with_note(user, game, note: str) -> Playthrough:
    """The run the conversion made of the row with this note.

    Tracking states a run of its own, so a converted
    library holds one more run than it held rows.
    """
    return next(run for run in converted_runs(user, game) if run.note == note)


@pytest.mark.django_db(transaction=True)
def test_post_states_a_run_and_writes_no_row(client, user, game):
    client.force_login(user)

    response = client.post(
        "/api/playthrough/",
        {"game_id": str(game.pk), "started": "2026-01-02", "ended": None, "note": ""},
        content_type="application/json",
    )

    assert response.status_code == 204
    assert PlayEvent.objects.count() == 0
    assert Playthrough.objects.filter(player_game__game=game).count() == 1


@pytest.mark.django_db(transaction=True)
def test_a_reversed_pair_answers_409(client, user, game):
    client.force_login(user)

    response = client.post(
        "/api/playthrough/",
        {
            "game_id": str(game.pk),
            "started": "2026-02-03",
            "ended": "2026-01-02",
            "note": "",
        },
        content_type="application/json",
    )

    assert response.status_code == 409


@pytest.mark.django_db(transaction=True)
def test_a_key_the_patch_leaves_out_keeps_the_value_the_run_states(client, user, game):
    PlayEvent.objects.create(
        game=game, started=date(2026, 1, 2), ended=None, note="12h"
    )
    convert_library(user.library)
    run = run_with_note(user, game, "12h")
    client.force_login(user)

    response = client.patch(
        f"/api/playthrough/{run.pk}",
        {"note": "12h 30m"},
        content_type="application/json",
    )

    assert response.status_code == 204
    run.refresh_from_db()
    assert run.note == "12h 30m"
    assert run.started == TemporalValue.from_day(date(2026, 1, 2))


@pytest.mark.django_db(transaction=True)
def test_patch_states_the_difference_onto_the_run(client, user, game):
    row = PlayEvent.objects.create(game=game, started=None, ended=None, note="row")
    convert_library(user.library)
    run = run_with_note(user, game, "row")
    client.force_login(user)

    response = client.patch(
        f"/api/playthrough/{run.pk}",
        {"started": "2026-01-02", "ended": None, "note": "read"},
        content_type="application/json",
    )

    assert response.status_code == 204
    run.refresh_from_db()
    assert run.note == "read"
    row.refresh_from_db()
    assert row.note == "row"


@pytest.mark.django_db(transaction=True)
def test_a_second_patch_does_not_revert_the_first(client, user, game):
    """The merge reads the run, never the frozen row.

    Nothing writes the legacy row any more, so filling the
    absent keys off it would put the day back that the
    first PATCH moved.
    """
    PlayEvent.objects.create(
        game=game, started=date(2026, 1, 2), ended=None, note="before"
    )
    convert_library(user.library)
    run = run_with_note(user, game, "before")
    client.force_login(user)

    client.patch(
        f"/api/playthrough/{run.pk}",
        {"started": "2026-03-04"},
        content_type="application/json",
    )
    response = client.patch(
        f"/api/playthrough/{run.pk}",
        {"note": "second"},
        content_type="application/json",
    )

    assert response.status_code == 204
    run.refresh_from_db()
    assert run.note == "second"
    assert run.started == TemporalValue.from_day(date(2026, 3, 4))


@pytest.mark.django_db(transaction=True)
def test_a_run_stating_more_than_a_day_answers_409(client, user, game):
    """#1015 owns the screen that states a month.

    This form holds a day, so it refuses rather than
    flattening what the run says into one.
    """
    PlayEvent.objects.create(game=game, started=None, ended=None, note="start")
    convert_library(user.library)
    run = run_with_note(user, game, "start")
    Playthrough.objects.filter(pk=run.pk).update(
        started=TemporalValue.from_month(2026, 3)
    )
    client.force_login(user)

    response = client.patch(
        f"/api/playthrough/{run.pk}",
        {"note": "second"},
        content_type="application/json",
    )

    assert response.status_code == 409
    run.refresh_from_db()
    assert run.note == "start"


@pytest.mark.django_db(transaction=True)
def test_delete_states_the_removal_and_leaves_the_row(client, user, game):
    PlayEvent.objects.create(game=game, started=None, ended=None, note="first")
    second = PlayEvent.objects.create(
        game=game, started=None, ended=None, note="second"
    )
    convert_library(user.library)
    run = run_with_note(user, game, "second")
    client.force_login(user)

    response = client.delete(f"/api/playthrough/{run.pk}")

    assert response.status_code == 204
    run.refresh_from_db()
    assert run.removed_at is not None
    second.refresh_from_db()
    assert second.removed_at is None


@pytest.mark.django_db(transaction=True)
def test_a_second_delete_answers_204(client, user, game):
    """#906: a repeat states nothing and refuses nothing."""
    PlayEvent.objects.create(game=game, started=None, ended=None, note="first")
    PlayEvent.objects.create(game=game, started=None, ended=None, note="second")
    convert_library(user.library)
    run = run_with_note(user, game, "second")
    client.force_login(user)

    assert client.delete(f"/api/playthrough/{run.pk}").status_code == 204
    assert client.delete(f"/api/playthrough/{run.pk}").status_code == 204


@pytest.mark.django_db(transaction=True)
def test_an_unconverted_row_id_answers_404(client, user, game):
    """The path names a run, so a row id names nothing."""
    row = PlayEvent.objects.create(game=game, started=None, ended=None, note="")
    client.force_login(user)

    assert client.delete(f"/api/playthrough/{row.pk}").status_code == 404
    assert client.get(f"/api/playthrough/{row.pk}").status_code == 404


def test_no_module_reads_the_bridge():
    """The API was its one reader; the module goes next."""
    import pathlib

    readers = sorted(
        path.as_posix()
        for path in pathlib.Path("games").rglob("*.py")
        if "playthrough_provenance" in path.read_text()
        and path.name != "playthrough_provenance.py"
    )
    assert readers == []
