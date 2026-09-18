"""The reclassification acts through the routes."""

import json
from datetime import UTC, date, datetime, timedelta

import pytest
from django.contrib.messages import get_messages
from django.urls import reverse
from historical_playtime_posts import posted_record
from session_rows import duration_only_row, timed_row, tracked_run

from common.returns import action_url
from games.commands.session_reclassification import (
    STILL_RUNNING,
    statement_from_session,
)
from games.models import (
    Game,
    HistoricalPlaytime,
    LibraryEvent,
    PlayerSession,
    Playthrough,
)
from games.views.session_reclassification import NOT_WRITTEN
from games.writes.playergame import new_correlation_id
from games.writes.playersession import reclassify_session as state_reclassification

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


# --- The review and the bulk conversion ---------------------------------------


def _bulk_url() -> str:
    return reverse("games:reclassify_reviewed_sessions")


def _long_row(run, day=A_DAY, hours=9) -> PlayerSession:
    return duration_only_row(run, day, timedelta(hours=hours))


def test_the_session_list_offers_the_review(logged_in, session):
    response = logged_in.get(reverse("games:list_sessions"))

    assert "Review estimates" in response.content.decode()


def test_the_review_filter_parses_and_stays_quick_editable(logged_in):
    """The link lands on a bar a person can go on editing."""
    from common.components import QUICK_FACETS, is_quick_editable, parse_filter_dict
    from games.filters import PlayerSessionFilter
    from games.views.session_reclassification import review_filter, review_url

    parsed = parse_filter_dict(review_filter(), PlayerSessionFilter)

    assert set(parsed) == {"timing_mode", "duration_hours"}
    assert is_quick_editable(
        parsed, {facet.field for facet in QUICK_FACETS["sessions"]}
    )
    rendered = logged_in.get(review_url()).content.decode()
    assert "Advanced filter active" not in rendered
    assert 'value="GREATER_THAN_OR_EQUAL" selected' in rendered


def test_the_review_filter_answers_the_rows_it_names(owned_library, run):
    from common.filter_execution import execute_filter
    from games.filters import PlayerSessionFilter, filter_query_context_for_library
    from games.reads.player_sessions import library_sessions
    from games.views.session_reclassification import review_filter

    long_enough = _long_row(run, hours=8)
    _long_row(run, date(2026, 4, 1), hours=7)
    timed_row(run, START, START + timedelta(hours=20))

    matched = set(
        execute_filter(
            PlayerSessionFilter.from_json(json.loads(review_filter())),
            library_sessions(owned_library),
            filter_query_context_for_library(owned_library),
        )
    )

    assert matched == {long_enough}


def test_the_confirmation_lists_every_matching_row(logged_in, run):
    rows = [_long_row(run, date(2026, 3, day)) for day in (1, 2, 3)]

    response = logged_in.get(_bulk_url())

    html = response.content.decode()
    assert response.status_code == 200
    for row in rows:
        assert f'value="{row.pk}"' in html


def test_the_post_converts_exactly_the_posted_keys(logged_in, run):
    first = _long_row(run, date(2026, 3, 1))
    second = _long_row(run, date(2026, 3, 2))

    logged_in.post(_bulk_url(), {"session": [str(first.pk)], "submission": "one"})

    first.refresh_from_db()
    second.refresh_from_db()
    assert first.removed_at is not None
    assert second.removed_at is None
    assert HistoricalPlaytime.objects.count() == 1


def test_a_posted_row_that_is_not_written_down_is_refused(logged_in, run):
    measured = timed_row(run, START, START + timedelta(hours=20))

    response = logged_in.post(
        _bulk_url(), {"session": [str(measured.pk)], "submission": "one"}
    )

    assert ("error", NOT_WRITTEN) in _messages_of(response)
    assert not HistoricalPlaytime.objects.exists()


def test_a_row_of_another_library_is_refused(
    client, django_user_model, owned_library, run
):
    row = _long_row(run)
    other = django_user_model.objects.create_user(username="stranger")
    client.force_login(other)

    response = client.post(_bulk_url(), {"session": [str(row.pk)], "submission": "one"})

    assert ("error", NOT_WRITTEN) in _messages_of(response)
    row.refresh_from_db()
    assert row.removed_at is None


def test_one_refused_row_does_not_stop_the_rest(logged_in, owned_user, run, game):
    """The answer names both counts, and the rest are converted."""
    refused = _long_row(run, date(2026, 3, 1))
    fine = _long_row(run, date(2026, 3, 2))
    #: Already a record; its conversion is refused.
    state_reclassification(
        owned_user,
        refused,
        statement_from_session(refused),
        idempotency_key="earlier",
        correlation_id=new_correlation_id(),
    )

    response = logged_in.post(
        _bulk_url(),
        {"session": [str(refused.pk), str(fine.pk)], "submission": "one"},
    )

    fine.refresh_from_db()
    assert fine.removed_at is not None
    assert any("1 of 1" in message for _level, message in _messages_of(response))


def test_a_second_submit_converts_nothing_new(logged_in, run):
    row = _long_row(run)
    posted = {"session": [str(row.pk)], "submission": "one"}

    logged_in.post(_bulk_url(), posted)
    logged_in.post(_bulk_url(), posted)

    assert HistoricalPlaytime.objects.count() == 1
