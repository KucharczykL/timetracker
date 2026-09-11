"""#687: the API states runs, not rows."""

from datetime import date

import pytest
from stated_runs import another_run, state_run

from games.commands.playthrough import ActStatement
from games.models import Game, PlayEvent, Playthrough
from games.removal import remove
from timetracker.temporal import TemporalValue


@pytest.fixture
def user(owned_user):
    return owned_user


@pytest.fixture
def game(owned_library):
    return Game.objects.create(library=owned_library, name="Outer Wilds")


def born_run(game) -> Playthrough:
    """The run a tracked game was born with."""
    return Playthrough.objects.get(player_game__game=game)


def day(value: str) -> ActStatement:
    """One act, stated on a day."""
    return ActStatement(TemporalValue.from_day(date.fromisoformat(value)))


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
    run = state_run(user, game, started=day("2026-01-02"), note="12h")
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
    run = state_run(user, game, note="unread")
    client.force_login(user)

    response = client.patch(
        f"/api/playthrough/{run.pk}",
        {"started": "2026-01-02", "completed": None, "note": "read"},
        content_type="application/json",
    )

    assert response.status_code == 204
    run.refresh_from_db()
    assert run.note == "read"
    assert run.started == TemporalValue.from_day(date(2026, 1, 2))


@pytest.mark.django_db(transaction=True)
def test_a_second_patch_does_not_revert_the_first(client, user, game):
    """The merge reads the run, never the frozen row.

    Nothing writes the legacy row any more, so filling the
    absent keys off it would put the day back that the
    first PATCH moved.
    """
    run = state_run(user, game, started=day("2026-01-02"), note="before")
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
    run = born_run(game)
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
    """A note-only PATCH keeps the month.

    The act is stated through the command, then coarsened
    in place: no command states a month.
    """
    run = state_run(user, game, started=day("2026-01-02"))
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
    run = born_run(game)
    client.force_login(user)

    response = client.patch(
        f"/api/playthrough/{run.pk}",
        {"started": "2020s"},
        content_type="application/json",
    )

    assert response.status_code == 422


@pytest.mark.django_db(transaction=True)
def test_delete_states_the_removal_and_leaves_the_row(client, user, game):
    run = another_run(user, game, note="second")
    client.force_login(user)

    response = client.delete(f"/api/playthrough/{run.pk}")

    assert response.status_code == 204
    run.refresh_from_db()
    assert run.removed_at is not None
    assert Playthrough.objects.filter(pk=run.pk).exists()


@pytest.mark.django_db(transaction=True)
def test_a_second_delete_answers_204(client, user, game):
    """#906: a repeat refuses nothing."""
    run = another_run(user, game, note="second")
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


@pytest.mark.django_db(transaction=True)
def test_a_note_only_patch_records_no_act(client, user, game):
    """#679's run states neither act, and keeps it.

    An act is recorded because a person recorded it, so a
    request that names no endpoint records none.
    """
    run = born_run(game)
    assert run.start_recorded_at is None
    client.force_login(user)

    response = client.patch(
        f"/api/playthrough/{run.pk}",
        {"note": "just a note"},
        content_type="application/json",
    )

    assert response.status_code == 204
    run.refresh_from_db()
    assert run.note == "just a note"
    assert run.start_recorded_at is None
    assert run.completion_recorded_at is None


@pytest.mark.django_db(transaction=True)
def test_a_patch_that_states_a_null_records_the_act(client, user, game):
    """A named key is the act; its day is unknown."""
    run = born_run(game)
    client.force_login(user)

    response = client.patch(
        f"/api/playthrough/{run.pk}",
        {"started": None},
        content_type="application/json",
    )

    assert response.status_code == 204
    run.refresh_from_db()
    assert run.start_recorded_at is not None
    assert run.started is None
    assert run.completion_recorded_at is None


@pytest.mark.django_db(transaction=True)
def test_the_body_patches_back_unchanged(client, user, game):
    """What a read states, a write takes back."""
    run = state_run(
        user,
        game,
        started=day("2026-01-02"),
        completed=day("2026-03-04"),
        note="12h",
    )
    client.force_login(user)
    body = client.get(f"/api/playthrough/{run.pk}").json()

    response = client.patch(
        f"/api/playthrough/{run.pk}",
        {
            "started": body["started"],
            "completed": body["completed"],
            "note": body["note"],
        },
        content_type="application/json",
    )

    assert response.status_code == 204
    assert client.get(f"/api/playthrough/{run.pk}").json() == body


@pytest.mark.parametrize(
    "spelling", ["2026", "2026-03", "202X", "2026-03-04~", "2024-01/.."]
)
@pytest.mark.django_db(transaction=True)
def test_every_spelling_the_grammar_knows_round_trips(client, user, game, spelling):
    run = born_run(game)
    client.force_login(user)

    response = client.patch(
        f"/api/playthrough/{run.pk}",
        {"started": spelling},
        content_type="application/json",
    )

    assert response.status_code == 204
    assert client.get(f"/api/playthrough/{run.pk}").json()["started"] == spelling


@pytest.mark.django_db(transaction=True)
def test_a_key_the_body_does_not_know_answers_422(client, user, game):
    """#1015 renamed `ended`; the old name is refused."""
    run = born_run(game)
    client.force_login(user)

    response = client.patch(
        f"/api/playthrough/{run.pk}",
        {"ended": "2026-01-02"},
        content_type="application/json",
    )

    assert response.status_code == 422
    run.refresh_from_db()
    assert run.completion_recorded_at is None


@pytest.mark.django_db(transaction=True)
def test_a_post_key_the_body_does_not_know_answers_422(client, user, game):
    client.force_login(user)

    response = client.post(
        "/api/playthrough/",
        {"game_id": str(game.pk), "ended": "2026-01-02"},
        content_type="application/json",
    )

    assert response.status_code == 422
    assert not Playthrough.objects.filter(
        player_game__game=game, completion_recorded_at__isnull=False
    ).exists()


@pytest.mark.django_db(transaction=True)
def test_deleting_the_only_run_of_a_tracked_game_answers_409(client, user, game):
    """A tracked game keeps one run."""
    run = born_run(game)
    client.force_login(user)

    response = client.delete(f"/api/playthrough/{run.pk}")

    assert response.status_code == 409
    run.refresh_from_db()
    assert run.removed_at is None


@pytest.mark.django_db(transaction=True)
def test_a_patch_of_a_removed_run_answers_409(client, user, game):
    run = another_run(user, game, note="second")
    client.force_login(user)
    assert client.delete(f"/api/playthrough/{run.pk}").status_code == 204

    response = client.patch(
        f"/api/playthrough/{run.pk}",
        {"note": "after"},
        content_type="application/json",
    )

    assert response.status_code == 409
    run.refresh_from_db()
    assert run.note == "second"


@pytest.mark.django_db(transaction=True)
def test_a_run_under_a_removed_game_is_neither_read_nor_written(client, user, game):
    """No route writes a run no route reads."""
    run = born_run(game)
    remove(game)
    client.force_login(user)

    assert client.get(f"/api/playthrough/{run.pk}").status_code == 404
    assert client.get("/api/playthrough/").json() == []
    assert (
        client.patch(
            f"/api/playthrough/{run.pk}",
            {"note": "after"},
            content_type="application/json",
        ).status_code
        == 404
    )
    assert client.delete(f"/api/playthrough/{run.pk}").status_code == 404
