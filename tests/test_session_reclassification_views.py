"""The reclassification acts through the routes."""

from datetime import UTC, date, datetime, timedelta

import pytest
from django.contrib.messages import get_messages
from django.urls import reverse
from historical_playtime_posts import posted_record
from session_rows import duration_only_row, timed_row, tracked_run

from common.returns import action_url
from games.commands.session_reclassification import STILL_RUNNING
from games.models import (
    Game,
    HistoricalPlaytime,
    LibraryEvent,
    PlayerSession,
    Playthrough,
)

pytestmark = pytest.mark.django_db(transaction=True)

A_DAY = date(2026, 3, 5)
START = datetime(2026, 3, 5, 12, tzinfo=UTC)


@pytest.fixture
def logged_in(client, owned_user):
    client.force_login(owned_user)
    return client


@pytest.fixture
def game(owned_library) -> Game:
    return Game.objects.create(library=owned_library, name="Outer Wilds")


@pytest.fixture
def run(owned_library, game) -> Playthrough:
    return tracked_run(owned_library, game)


@pytest.fixture
def session(run) -> PlayerSession:
    return duration_only_row(run, A_DAY, timedelta(hours=9))


def _url(session, origin=None) -> str:
    return action_url("games:reclassify_session", session.pk, origin=origin)


def _messages_of(response) -> list[tuple[str, str]]:
    return [(m.level_tag, m.message) for m in get_messages(response.wsgi_request)]


def test_get_renders_the_prefilled_form(logged_in, session, run):
    response = logged_in.get(_url(session))

    assert response.status_code == 200
    html = response.content.decode()
    assert str(run.pk) in html
    #: Nine hours, as the session states them.
    assert 'value="9"' in html


def test_post_converts_and_returns_to_the_origin(logged_in, session, run):
    origin = reverse("games:list_sessions")

    response = logged_in.post(
        _url(session, origin=origin),
        posted_record([run.pk], hours="9", minutes="0", when_year="2026"),
    )

    assert response.status_code == 302
    assert response.headers["Location"] == origin
    record = HistoricalPlaytime.objects.get()
    session.refresh_from_db()
    assert session.reclassified_into_id == record.pk
    assert session.removed_at is not None


def test_the_toast_offers_the_undo(logged_in, session, run):
    response = logged_in.post(
        _url(session), posted_record([run.pk], hours="9", when_year="2026")
    )

    (level, message) = _messages_of(response)[0]
    assert level == "success"
    assert message == "Session recorded as historical playtime."
    stored = next(iter(get_messages(response.wsgi_request)))
    assert reverse("games:undo_reclassify_session", args=[session.pk]) in (
        stored.extra_tags
    )


def test_the_undo_route_reverses_the_pair(logged_in, session, run):
    logged_in.post(_url(session), posted_record([run.pk], hours="9", when_year="2026"))
    record = HistoricalPlaytime.objects.get()

    response = logged_in.post(
        reverse("games:undo_reclassify_session", args=[session.pk])
    )

    assert response.status_code == 302
    session.refresh_from_db()
    record.refresh_from_db()
    assert session.removed_at is None
    assert record.removed_at is not None


def test_a_refusal_re_renders_the_form_with_its_sentence(logged_in, run):
    running = timed_row(run, START, None)

    response = logged_in.post(
        _url(running), posted_record([run.pk], hours="9", when_year="2026")
    )

    assert response.status_code == 409
    assert (("error", STILL_RUNNING)) in _messages_of(response)
    assert not HistoricalPlaytime.objects.exists()


def test_a_repeated_submit_records_one_record(logged_in, session, run):
    posted = posted_record([run.pk], hours="9", when_year="2026")

    logged_in.post(_url(session), posted)
    logged_in.post(_url(session), posted)

    assert HistoricalPlaytime.objects.count() == 1
    assert (
        LibraryEvent.objects.filter(
            event_type="library.playersession.reclassified"
        ).count()
        == 1
    )


def test_a_session_of_another_library_is_not_found(client, django_user_model, session):
    other = django_user_model.objects.create_user(username="stranger")
    client.force_login(other)

    assert client.get(_url(session)).status_code == 404


def test_the_row_action_appears_on_a_duration_only_row_alone(run):
    from common.components.domain import SessionActions

    written = duration_only_row(run, A_DAY, timedelta(hours=9))
    measured = timed_row(run, START, START + timedelta(hours=1))

    assert "Was an estimate" in str(SessionActions(written, "token", None))
    assert "Was an estimate" not in str(SessionActions(measured, "token", None))
