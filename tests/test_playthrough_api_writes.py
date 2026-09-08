"""#687: the API states runs, not rows."""

from datetime import date

import pytest
from playthrough_conversion import convert_and_take_runs

from games.models import Game, PlayEvent, Playthrough
from timetracker.temporal import TemporalValue


@pytest.fixture
def user(owned_user):
    return owned_user


@pytest.fixture
def game(owned_library):
    return Game.objects.create(library=owned_library, name="Outer Wilds")


@pytest.mark.django_db(transaction=True)
def test_post_states_a_run_and_writes_no_row(client, user, game):
    client.force_login(user)

    response = client.post(
        "/api/playthrough/",
        {
            "game_id": str(game.pk),
            "started": "2026-01-02",
            "completed": None,
            "note": "",
        },
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
            "completed": "2026-01-02",
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
    [run] = convert_and_take_runs(user.library, game)
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
    [run] = convert_and_take_runs(user.library, game)
    client.force_login(user)

    response = client.patch(
        f"/api/playthrough/{run.pk}",
        {"started": "2026-01-02", "completed": None, "note": "read"},
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
    [run] = convert_and_take_runs(user.library, game)
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
def test_a_patch_states_a_month(client, user, game):
    """The body states every value stated."""
    PlayEvent.objects.create(game=game, started=None, ended=None, note="start")
    [run] = convert_and_take_runs(user.library, game)
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
    """A note-only PATCH keeps the month."""
    PlayEvent.objects.create(game=game, started=None, ended=None, note="start")
    [run] = convert_and_take_runs(user.library, game)
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
    """A decade is 202X; 2020s names nothing."""
    PlayEvent.objects.create(game=game, started=None, ended=None, note="start")
    [run] = convert_and_take_runs(user.library, game)
    client.force_login(user)

    response = client.patch(
        f"/api/playthrough/{run.pk}",
        {"started": "2020s"},
        content_type="application/json",
    )

    assert response.status_code == 422


@pytest.mark.django_db(transaction=True)
def test_delete_states_the_removal_and_leaves_the_row(client, user, game):
    PlayEvent.objects.create(game=game, started=None, ended=None, note="first")
    second = PlayEvent.objects.create(
        game=game, started=None, ended=None, note="second"
    )
    _first, run = convert_and_take_runs(user.library, game)
    client.force_login(user)

    response = client.delete(f"/api/playthrough/{run.pk}")

    assert response.status_code == 204
    run.refresh_from_db()
    assert run.removed_at is not None
    second.refresh_from_db()
    assert second.removed_at is None


@pytest.mark.django_db(transaction=True)
def test_a_second_delete_answers_204(client, user, game):
    """#906: a repeat refuses nothing."""
    PlayEvent.objects.create(game=game, started=None, ended=None, note="first")
    PlayEvent.objects.create(game=game, started=None, ended=None, note="second")
    _first, run = convert_and_take_runs(user.library, game)
    client.force_login(user)

    assert client.delete(f"/api/playthrough/{run.pk}").status_code == 204
    assert client.delete(f"/api/playthrough/{run.pk}").status_code == 204


@pytest.mark.django_db(transaction=True)
def test_an_unconverted_row_id_answers_404(client, user, game):
    """A row id names no run."""
    row = PlayEvent.objects.create(game=game, started=None, ended=None, note="")
    client.force_login(user)

    assert client.delete(f"/api/playthrough/{row.pk}").status_code == 404
    assert client.get(f"/api/playthrough/{row.pk}").status_code == 404
