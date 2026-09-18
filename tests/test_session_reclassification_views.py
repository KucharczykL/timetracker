"""The reclassification acts through the routes."""

import json
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from django.contrib.messages import get_messages
from django.urls import reverse
from django.utils import timezone
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
    PlaythroughKind,
)
from games.views.session_reclassification import (
    ALREADY_RECORDED,
    IN_THE_BUCKET,
    NOT_AVAILABLE,
    NOT_WRITTEN,
    UNDER_THRESHOLD,
)
from games.writes.answers import CONFLICT_STATUS, DEFECT_STATUS, CommandFailed
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
    #: Run checked; day and hours filled.
    checked = [line for line in html.split("<input") if str(run.pk) in line]
    assert any("checked" in line for line in checked)
    assert 'name="duration_hours"' in html
    assert 'value="9"' in html
    assert 'value="2026"' in html


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
    assert record.reclassified_from_id == session.pk
    assert session.removed_at is not None


def test_the_toast_offers_the_undo(logged_in, session, run):
    response = logged_in.post(
        _url(session), posted_record([run.pk], hours="9", when_year="2026")
    )

    (level, message) = _messages_of(response)[0]
    assert level == "success"
    assert message == "Session recorded as historical playtime."


def test_a_reclassified_session_posted_again_is_refused_in_its_own_words(
    logged_in, session, run
):
    """A stale tab; the sentence names the undo."""
    posted = posted_record([run.pk], hours="9", when_year="2026")
    logged_in.post(_url(session), posted)

    response = logged_in.post(_url(session), posted | {"submission": str(uuid.uuid7())})

    assert response.status_code == CONFLICT_STATUS
    assert any(
        "already recorded" in message for _level, message in _messages_of(response)
    )
    assert HistoricalPlaytime.objects.count() == 1
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

    tooltip = "Was an estimate, not one sitting"
    assert tooltip in str(SessionActions(written, "token", None))
    assert tooltip not in str(SessionActions(measured, "token", None))


# --- The review and the bulk conversion ---------------------------------------


def _bulk_url() -> str:
    return reverse("games:reclassify_reviewed_sessions")


def _long_row(run, day=A_DAY, hours=9) -> PlayerSession:
    return duration_only_row(run, day, timedelta(hours=hours))


def test_the_library_offers_the_review(logged_in, session):
    """The entry points live here."""
    response = logged_in.get(reverse("games:library"))

    html = response.content.decode()
    assert "See these sessions" in html
    assert "Move all 1 to historical playtime" in html
    assert "Playtime" in html


def test_the_library_says_so_when_nothing_waits(logged_in, run):
    timed_row(run, START, START + timedelta(hours=20))

    response = logged_in.get(reverse("games:library"))

    assert "Nothing to review" in response.content.decode()


def test_the_session_list_carries_no_review_row(logged_in, session):
    """One act, one home."""
    response = logged_in.get(reverse("games:list_sessions"))

    assert "See these sessions" not in response.content.decode()


def test_the_review_filter_parses_and_stays_quick_editable(logged_in):
    """The link lands on an editable bar."""
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

    assert ("error", NOT_AVAILABLE) in _messages_of(response)
    row.refresh_from_db()
    assert row.removed_at is None


def test_a_written_down_row_under_the_threshold_is_refused_in_its_own_words(
    logged_in, run
):
    short = _long_row(run, hours=7)

    response = logged_in.post(
        _bulk_url(), {"session": [str(short.pk)], "submission": "one"}
    )

    assert ("error", UNDER_THRESHOLD) in _messages_of(response)
    assert ("error", NOT_WRITTEN) not in _messages_of(response)
    short.refresh_from_db()
    assert short.removed_at is None


def test_a_key_that_is_no_session_counts_against_the_posted_total(logged_in, run):
    row = _long_row(run)

    response = logged_in.post(
        _bulk_url(), {"session": [str(row.pk), "not-a-key"], "submission": "one"}
    )

    said = _messages_of(response)
    assert ("error", NOT_AVAILABLE) in said
    assert any("1 of 2" in message for _level, message in said)


def test_a_row_removed_since_the_page_opened_counts_as_lost(logged_in, owned_user, run):
    kept = _long_row(run, date(2026, 3, 1))
    gone = _long_row(run, date(2026, 3, 2))
    PlayerSession.objects.filter(pk=gone.pk).update(removed_at=START)

    response = logged_in.post(
        _bulk_url(),
        {"session": [str(kept.pk), str(gone.pk)], "submission": "one"},
    )

    said = _messages_of(response)
    assert any("1 of 2" in message for _level, message in said)
    assert ("error", NOT_AVAILABLE) in said


def test_a_defect_stops_the_request_and_offers_no_second_press(
    logged_in, run, monkeypatch
):
    """Rows before it stay recorded and counted."""
    from games.views import session_reclassification as views

    rows = [_long_row(run, date(2026, 3, day)) for day in (1, 2, 3)]
    real = views.state_reclassification

    def failing(user, row, *args, **kwargs):
        if row.pk == rows[1].pk:
            raise CommandFailed("Nothing was saved.", DEFECT_STATUS)
        return real(user, row, *args, **kwargs)

    monkeypatch.setattr(views, "state_reclassification", failing)

    response = logged_in.post(
        _bulk_url(),
        {"session": [str(row.pk) for row in rows] + ["not-a-key"], "submission": "one"},
    )

    assert response.status_code == DEFECT_STATUS
    html = response.content.decode()
    assert "1 of 4" in html
    assert ">Record as historical playtime<" not in html
    #: Sentences before the defect still reach the page.
    assert NOT_AVAILABLE in html
    for row in rows:
        row.refresh_from_db()
    assert rows[0].removed_at is not None
    assert rows[1].removed_at is None
    assert rows[2].removed_at is None


def test_the_undo_route_says_when_nothing_changed(logged_in, session, run):
    logged_in.post(_url(session), posted_record([run.pk], hours="9", when_year="2026"))
    url = reverse("games:undo_reclassify_session", args=[session.pk])
    logged_in.post(url)
    #: A rendered page spends the earlier messages.
    logged_in.get(reverse("games:list_sessions"))

    response = logged_in.post(url)

    assert response.status_code == 302
    said = _messages_of(response)
    assert ("info", "That session was already back.") in said
    assert not any("restored" in message for _level, message in said)


def test_the_library_promises_no_undo_for_the_bulk_act(logged_in, session):
    html = logged_in.get(reverse("games:library")).content.decode()

    assert "every change offers an Undo" not in html
    assert "all of them at once does not." in html


def test_one_refused_row_does_not_stop_the_rest(logged_in, owned_user, run, game):
    """Both counts named; the rest converted."""
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
    #: The refused row counts: two were sent.
    said = _messages_of(response)
    assert any("1 of 2" in message for _level, message in said)
    assert ("info", ALREADY_RECORDED) in said


def test_a_command_refusal_does_not_stop_the_rest(logged_in, run, monkeypatch):
    """A refusal is a sentence; the loop continues."""
    from games.views import session_reclassification as views

    rows = [_long_row(run, date(2026, 3, day)) for day in (1, 2, 3)]
    real = views.state_reclassification

    def refusing(user, row, *args, **kwargs):
        if row.pk == rows[1].pk:
            raise CommandFailed("That one was refused.", CONFLICT_STATUS)
        return real(user, row, *args, **kwargs)

    monkeypatch.setattr(views, "state_reclassification", refusing)

    response = logged_in.post(
        _bulk_url(),
        {"session": [str(row.pk) for row in rows], "submission": "one"},
    )

    assert response.status_code == 302
    said = _messages_of(response)
    assert any("2 of 3" in message for _level, message in said)
    assert ("error", "That one was refused.") in said
    assert HistoricalPlaytime.objects.count() == 2


def test_a_second_submit_says_the_rows_were_already_recorded(logged_in, run):
    row = _long_row(run)
    posted = {"session": [str(row.pk)], "submission": "one"}
    logged_in.post(_bulk_url(), posted)
    logged_in.get(reverse("games:list_sessions"))

    response = logged_in.post(_bulk_url(), posted)

    said = _messages_of(response)
    assert ("info", ALREADY_RECORDED) in said
    assert not any(level == "error" for level, _message in said)
    assert any("0 of 1" in message for _level, message in said)


def test_a_key_posted_twice_counts_once(logged_in, run):
    row = _long_row(run)

    response = logged_in.post(
        _bulk_url(), {"session": [str(row.pk), str(row.pk)], "submission": "one"}
    )

    assert any("1 of 1" in message for _level, message in _messages_of(response))


def test_a_bucket_session_is_not_reviewed_and_is_refused_in_its_own_words(
    logged_in, run
):
    bucket = Playthrough.objects.create(
        id=uuid.uuid7(),
        library=run.library,
        player_game=run.player_game,
        kind=PlaythroughKind.IMPORTED_HISTORY,
        created_at=timezone.now(),
    )
    in_the_bucket = _long_row(bucket)

    assert (
        "Nothing to review" in logged_in.get(reverse("games:library")).content.decode()
    )
    response = logged_in.post(
        _bulk_url(), {"session": [str(in_the_bucket.pk)], "submission": "one"}
    )

    assert ("error", IN_THE_BUCKET) in _messages_of(response)
    in_the_bucket.refresh_from_db()
    assert in_the_bucket.removed_at is None


def test_every_key_left_alone_is_logged_with_its_library(logged_in, run, caplog):
    import logging

    short = _long_row(run, hours=7)
    #: The games logger does not propagate.
    logging.getLogger("games").addHandler(caplog.handler)
    with caplog.at_level("INFO", logger="games"):
        logged_in.post(_bulk_url(), {"session": [str(short.pk)], "submission": "one"})
    logging.getLogger("games").removeHandler(caplog.handler)

    (line,) = [
        record for record in caplog.records if "was not recorded" in record.message
    ]
    assert str(short.pk) in line.message
    assert str(run.library_id) in line.message
    assert UNDER_THRESHOLD in line.message


def test_the_bulk_toast_offers_no_undo(logged_in, run):
    row = _long_row(run)

    response = logged_in.post(
        _bulk_url(), {"session": [str(row.pk)], "submission": "one"}
    )

    stored = list(get_messages(response.wsgi_request))
    assert stored
    assert all(not message.extra_tags for message in stored)


def test_a_second_submit_converts_nothing_new(logged_in, run):
    row = _long_row(run)
    posted = {"session": [str(row.pk)], "submission": "one"}

    logged_in.post(_bulk_url(), posted)
    logged_in.post(_bulk_url(), posted)

    assert HistoricalPlaytime.objects.count() == 1
