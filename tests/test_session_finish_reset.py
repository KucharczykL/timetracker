"""Finishing and resetting a session are POST routes that reload the page."""

from datetime import UTC, datetime

import pytest
from django.urls import reverse

from common.returns import action_url
from games.models import Game, Platform, Session

BROWSER_ZONE = "Asia/Tokyo"
STARTED_AT = datetime(2024, 6, 1, 12, tzinfo=UTC)


@pytest.fixture
def logged_in(client, django_user_model, db):
    user = django_user_model.objects.create_user(username="u", password="p")
    client.force_login(user)
    return client


@pytest.fixture
def open_session(db):
    game = Game.objects.create(
        name="Test Game", platform=Platform.objects.create(name="PC")
    )
    return Session.objects.create(game=game, timestamp_start=STARTED_AT)


def test_finish_sets_timestamp_end_and_redirects_to_origin(logged_in, open_session):
    origin = f"{reverse('games:list_sessions')}?page=2"

    response = logged_in.post(
        action_url("games:finish_session", open_session.pk, origin=origin)
    )

    open_session.refresh_from_db()
    assert open_session.timestamp_end is not None
    assert response["Location"] == origin


def test_finish_records_the_posted_browser_time_zone(logged_in, open_session):
    logged_in.post(
        reverse("games:finish_session", args=[open_session.pk]),
        {"browser_time_zone": BROWSER_ZONE},
    )

    open_session.refresh_from_db()
    assert open_session.timestamp_end_timezone == BROWSER_ZONE


def test_finish_ignores_an_unknown_time_zone(logged_in, open_session):
    response = logged_in.post(
        reverse("games:finish_session", args=[open_session.pk]),
        {"browser_time_zone": "Not/AZone"},
    )

    open_session.refresh_from_db()
    assert response.status_code == 302
    assert open_session.timestamp_end is not None
    assert not open_session.timestamp_end_timezone


def test_finish_rejects_get(logged_in, open_session):
    response = logged_in.get(reverse("games:finish_session", args=[open_session.pk]))

    open_session.refresh_from_db()
    assert response.status_code == 405
    assert open_session.timestamp_end is None


def test_reset_get_renders_a_confirmation_and_does_not_mutate(logged_in, open_session):
    response = logged_in.get(reverse("games:reset_session", args=[open_session.pk]))

    open_session.refresh_from_db()
    assert response.status_code == 200
    assert "Test Game" in response.content.decode()
    assert open_session.timestamp_start == STARTED_AT


def test_reset_post_moves_timestamp_start_to_now_and_redirects(logged_in, open_session):
    response = logged_in.post(reverse("games:reset_session", args=[open_session.pk]))

    open_session.refresh_from_db()
    assert open_session.timestamp_start > STARTED_AT
    assert response["Location"] == reverse("games:list_sessions")


def test_reset_records_the_posted_browser_time_zone(logged_in, open_session):
    logged_in.post(
        reverse("games:reset_session", args=[open_session.pk]),
        {"browser_time_zone": BROWSER_ZONE},
    )

    open_session.refresh_from_db()
    assert open_session.timestamp_start_timezone == BROWSER_ZONE


@pytest.mark.parametrize("url_name", ["games:finish_session", "games:reset_session"])
def test_both_routes_require_login(client, open_session, url_name):
    response = client.post(reverse(url_name, args=[open_session.pk]))

    open_session.refresh_from_db()
    assert response.status_code == 302
    assert "/login" in response["Location"]
    assert open_session.timestamp_end is None
    assert open_session.timestamp_start == STARTED_AT
