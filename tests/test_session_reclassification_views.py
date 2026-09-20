"""The reclassification acts through the routes."""

import json
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from django.contrib.messages import get_messages
from django.urls import NoReverseMatch, reverse
from historical_playtime_posts import posted_record
from session_rows import duration_only_row, timed_row, tracked_run

from common.returns import action_url
from games.bulk_actions import BULK_ACTIONS
from games.commands.session_reclassification import (
    STILL_RUNNING,
)
from games.models import (
    Game,
    HistoricalPlaytime,
    LibraryEvent,
    PlayerSession,
    Playthrough,
)
from games.views.bulk import STATEMENT_FIELD
from games.views.session_reclassification import (
    review_filter,
    review_url,
)
from games.writes.answers import CONFLICT_STATUS

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


def _long_row(run, day=A_DAY, hours=9) -> PlayerSession:
    return duration_only_row(run, day, timedelta(hours=hours))


def test_the_library_offers_the_review(logged_in, session):
    """The panel explains and points; the act is not pressed here."""
    response = logged_in.get(reverse("games:library"))

    html = response.content.decode()
    assert "See these sessions" in html
    assert "1 of your play sessions" in html
    assert "Playtime" in html


def test_the_panel_presses_nothing(logged_in, session):
    """The act is offered from the line the session list renders.

    One place presses it, so the review is a link to those rows
    rather than a second way to run the same batch.
    """
    html = logged_in.get(reverse("games:library")).content.decode()

    assert "Move all" not in html
    assert (
        action_url(
            "games:run_bulk_action",
            "session.reclassify",
            origin=reverse("games:library"),
        )
        not in html
    )
    assert f'name="{STATEMENT_FIELD}"' not in html


def test_the_panels_count_is_the_scope_the_act_resolves(logged_in, owned_library, run):
    """What a person is told, and what the line acts on, are one read."""
    for day in (1, 2, 3):
        _long_row(run, date(2026, 3, day))
    _long_row(run, date(2026, 4, 1), hours=1)

    html = logged_in.get(reverse("games:library")).content.decode()

    assert "3 of your play sessions" in html
    scope = BULK_ACTIONS["session.reclassify"].scope(owned_library, review_filter())
    assert scope.count() == 3


def test_the_link_lands_on_the_rows_the_act_offers(logged_in, owned_library, run):
    """The review's filter is the one the line's act narrows by."""
    for day in (1, 2, 3):
        _long_row(run, date(2026, 3, day))

    listed = logged_in.get(review_url())

    html = listed.content.decode()
    assert html.count("data-selection-key=") == 3
    assert "/bulk/session.reclassify/" in html


def test_the_review_has_no_route_of_its_own(logged_in):
    """One runner, so the act's own route is gone."""
    with pytest.raises(NoReverseMatch):
        reverse("games:reclassify_reviewed_sessions")


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
        parsed,
        {facet.field for facet in QUICK_FACETS["sessions"]},
        filter_cls=PlayerSessionFilter,
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


def test_the_library_promises_nothing_it_does_not_do(logged_in, session):
    """The panel runs no act, so it makes no promise about one.

    The Undo is the runner's, and the line that presses it says so.
    What must stay gone is the older sentence, which told a person the
    batch could not be taken back.
    """
    html = logged_in.get(reverse("games:library")).content.decode()

    assert "all of them at once does not" not in html
    assert "Undo" not in html
