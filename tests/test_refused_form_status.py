"""A re-rendered form answers the refusal's status."""

import pytest
from django.urls import reverse
from django.utils import timezone
from tracked_games import create_tracked_game

from games.models import PlayerGame, PlayerSession, Playthrough
from games.writes.answers import CONFLICT_STATUS, DEFECT_STATUS, CommandFailed

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def logged_in(client, owned_user):
    client.force_login(owned_user)
    return client


@pytest.fixture
def tracked_game(owned_library):
    return create_tracked_game(owned_library, "Outer Wilds")


def _session_payload(game, **overrides):
    started = timezone.now().replace(microsecond=0)
    tracked = PlayerGame.objects.filter(game=game).first()
    run = None if tracked is None else tracked.playthroughs.first()
    return {
        "game": str(game.id),
        "playthrough": "" if run is None else str(run.pk),
        "started_at": started.strftime("%Y-%m-%d %H:%M"),
        "started_at_zone": "",
        "ended_at": "",
        "ended_at_zone": "",
        "duration": "",
        "note": "",
        **overrides,
    }


def _refuse(status):
    def refuse(*args, **kwargs):
        raise CommandFailed("Nothing was recorded; try again.", status)

    return refuse


@pytest.mark.parametrize("status", [CONFLICT_STATUS, DEFECT_STATUS])
def test_a_refused_new_session_renders_the_form_at_the_refusals_status(
    logged_in, tracked_game, monkeypatch, status
):
    monkeypatch.setattr("games.views.session.record_session", _refuse(status))

    response = logged_in.post(
        reverse("games:add_session"), _session_payload(tracked_game)
    )

    #: A redirect would read as a save.
    assert response.status_code == status
    assert "show-toast" in response.headers["HX-Trigger"]
    assert not PlayerSession.objects.exists()


@pytest.mark.parametrize("status", [CONFLICT_STATUS, DEFECT_STATUS])
def test_a_refused_session_edit_renders_the_form_at_the_refusals_status(
    logged_in, tracked_game, monkeypatch, status
):
    logged_in.post(reverse("games:add_session"), _session_payload(tracked_game))
    session = PlayerSession.objects.get()
    monkeypatch.setattr("games.views.session.restate_session", _refuse(status))

    response = logged_in.post(
        reverse("games:edit_session", args=[session.id]),
        _session_payload(tracked_game, note="Changed"),
    )

    assert response.status_code == status
    assert "show-toast" in response.headers["HX-Trigger"]
    session.refresh_from_db()
    assert session.note == ""


@pytest.mark.parametrize("status", [CONFLICT_STATUS, DEFECT_STATUS])
def test_a_refused_new_run_renders_the_form_at_the_refusals_status(
    logged_in, tracked_game, monkeypatch, status
):
    monkeypatch.setattr("games.views.playthrough_writes.record_run", _refuse(status))

    response = logged_in.post(
        reverse("games:add_playthrough"),
        {
            "game": str(tracked_game.pk),
            "started": "2024-01-05",
            "ended": "",
            "note": "",
        },
    )

    assert response.status_code == status
    assert "show-toast" in response.headers["HX-Trigger"]
    assert Playthrough.objects.count() == 1


@pytest.mark.parametrize("status", [CONFLICT_STATUS, DEFECT_STATUS])
def test_a_refused_run_edit_renders_the_form_at_the_refusals_status(
    logged_in, tracked_game, monkeypatch, status
):
    run = Playthrough.objects.get(player_game__game=tracked_game)
    monkeypatch.setattr("games.views.playthrough_writes.restate_run", _refuse(status))

    response = logged_in.post(
        reverse("games:edit_playthrough", args=[run.pk]),
        {
            "game": str(tracked_game.pk),
            "started": "2024-01-05",
            "ended": "",
            "note": "",
        },
    )

    assert response.status_code == status
    assert "show-toast" in response.headers["HX-Trigger"]
    run.refresh_from_db()
    assert run.started_lower is None
