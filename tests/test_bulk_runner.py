"""The runner: one route, two POSTs, told apart by the token."""

import html as html_module
import json
import uuid
from datetime import date, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from session_rows import duration_only_row, tracked_run

from games.bulk_reclassification import (
    IN_THE_BUCKET,
    NOT_AVAILABLE,
    REVIEW_THRESHOLD_HOURS,
)
from games.models import (
    Game,
    HistoricalPlaytime,
    PlayerSession,
    Playthrough,
    PlaythroughKind,
)
from games.views.bulk import PROGRESS_FIELD, STATEMENT_FIELD, TOKEN_FIELD
from games.views.session_reclassification import review_filter
from timetracker.uuidv7 import parse_uuidv7

pytestmark = [pytest.mark.untracked_games, pytest.mark.django_db(transaction=True)]

A_DAY = date(2026, 3, 5)
LONG_ENOUGH = timedelta(hours=REVIEW_THRESHOLD_HOURS + 1)
RECLASSIFY = reverse("games:run_bulk_action", args=["session.reclassify"])


@pytest.fixture(autouse=True)
def prague_calendar(owned_user, set_user_setting):
    set_user_setting(owned_user, "DISPLAY_TIME_ZONE", "Europe/Prague")


@pytest.fixture
def client_in(client, owned_user):
    client.force_login(owned_user)
    return client


@pytest.fixture
def game(owned_library):
    return Game.objects.create(library=owned_library, name="Outer Wilds")


def a_written_session(library, game, day=A_DAY, duration=LONG_ENOUGH):
    return duration_only_row(tracked_run(library, game), day, duration)


def some(*sessions) -> str:
    return json.dumps(
        {"mode": "some", "keys": sorted(str(session.pk) for session in sessions)}
    )


def all_matching(filter_json: str, count: int, *excluded) -> str:
    return json.dumps(
        {
            "mode": "all",
            "filter": filter_json,
            "count": count,
            "except": sorted(str(row.pk) for row in excluded),
        }
    )


def confirm(client, statement, url=RECLASSIFY):
    """The first POST: no token, so it confirms."""
    return client.post(url, {STATEMENT_FIELD: statement})


def posted(response) -> dict[str, str]:
    """The hidden fields the confirmation would submit."""
    html = response.content.decode()
    fields: dict[str, str] = {}
    for name in (TOKEN_FIELD, PROGRESS_FIELD):
        marker = f'name="{name}" value="'
        if marker in html:
            start = html.index(marker) + len(marker)
            fields[name] = html_module.unescape(html[start : html.index('"', start)])
    return fields


# ── The confirmation ─────────────────────────────────────────────────────────


def test_a_statement_without_a_token_confirms(client_in, owned_library, game):
    session = a_written_session(owned_library, game)

    response = confirm(client_in, some(session))

    assert response.status_code == 200
    fields = posted(response)
    #: The token is the batch's correlation id, so it must be a v7.
    assert parse_uuidv7(uuid.UUID(fields[TOKEN_FIELD]))
    assert json.loads(fields[PROGRESS_FIELD])["rows"] == [str(session.pk)]
    assert HistoricalPlaytime.objects.count() == 0


def test_an_all_statement_resolves_through_the_scope(client_in, owned_library, game):
    wanted = a_written_session(owned_library, game)
    short = a_written_session(
        owned_library, game, day=date(2026, 3, 6), duration=timedelta(hours=1)
    )

    response = confirm(client_in, all_matching(review_filter(), 1))

    rows = json.loads(posted(response)[PROGRESS_FIELD])["rows"]
    assert rows == [str(wanted.pk)]
    assert str(short.pk) not in rows


def test_an_all_statement_drops_what_it_excludes(client_in, owned_library, game):
    kept = a_written_session(owned_library, game)
    dropped = a_written_session(owned_library, game, day=date(2026, 3, 6))

    response = confirm(client_in, all_matching(review_filter(), 2, dropped))

    assert json.loads(posted(response)[PROGRESS_FIELD])["rows"] == [str(kept.pk)]


def test_a_filter_that_cannot_be_parsed_refuses(client_in, owned_library, game):
    a_written_session(owned_library, game)

    response = confirm(client_in, all_matching("{not json", 1))

    assert response.status_code == 400
    assert TOKEN_FIELD not in posted(response)
    assert HistoricalPlaytime.objects.count() == 0


def test_a_count_that_moved_is_said_and_not_refused(client_in, owned_library, game):
    a_written_session(owned_library, game)

    #: The person saw nine; one is here now.
    response = confirm(client_in, all_matching(review_filter(), 9))

    assert response.status_code == 200
    assert TOKEN_FIELD in posted(response)
    assert b"1" in response.content


def test_another_librarys_key_never_resolves(
    client_in, owned_library, django_user_model
):
    stranger = django_user_model.objects.create_user(username="stranger", password="p")
    game = Game.objects.create(library=stranger.library, name="Celeste")
    theirs = duration_only_row(tracked_run(stranger.library, game), A_DAY, LONG_ENOUGH)

    response = confirm(client_in, some(theirs))

    assert json.loads(posted(response)[PROGRESS_FIELD])["rows"] == []


def test_a_refused_row_is_named_with_its_reason(client_in, owned_library, game):
    player_game = tracked_run(owned_library, game).player_game
    bucket = Playthrough.objects.create(
        pk=uuid.uuid7(),
        library=owned_library,
        player_game=player_game,
        kind=PlaythroughKind.IMPORTED_HISTORY,
        created_at=timezone.now(),
    )
    in_the_bucket = duration_only_row(bucket, A_DAY, LONG_ENOUGH)

    response = confirm(client_in, some(in_the_bucket))

    assert IN_THE_BUCKET.encode() in response.content


def test_a_missing_key_is_named_lost(client_in, owned_library):
    response = confirm(client_in, some_key(uuid.uuid7()))

    assert NOT_AVAILABLE.encode() in response.content


def some_key(key) -> str:
    return json.dumps({"mode": "some", "keys": [str(key)]})


def test_a_confirmation_lists_the_rows_to_a_cap(client_in, owned_library, game):
    from games.views.bulk import CONFIRMATION_SAMPLE

    sessions = [
        a_written_session(owned_library, game, day=A_DAY + timedelta(days=offset))
        for offset in range(CONFIRMATION_SAMPLE + 3)
    ]

    response = confirm(client_in, some(*sessions))

    html = response.content.decode()
    assert html.count("data-bulk-sample-row") == CONFIRMATION_SAMPLE
    #: Every key still rides the field, capped or not.
    assert len(json.loads(posted(response)[PROGRESS_FIELD])["rows"]) == len(sessions)


def test_a_statement_naming_nothing_offers_no_submit(client_in, owned_library):
    """Nothing to do admits no press.

    The page's own chrome submits (the navbar signs out), so this asks
    about the act's button rather than about every button.
    """
    from games.bulk_actions import BULK_ACTIONS

    response = confirm(client_in, json.dumps({"mode": "some", "keys": []}))

    assert response.status_code == 200
    assert BULK_ACTIONS["session.reclassify"].confirm_label.encode() not in (
        response.content
    )


def test_an_unknown_act_is_absent(client_in):
    response = client_in.post(
        reverse("games:run_bulk_action", args=["session.invented"]),
        {STATEMENT_FIELD: json.dumps({"mode": "some", "keys": []})},
    )

    assert response.status_code == 404


def test_the_runner_answers_no_get(client_in, owned_library, game):
    assert client_in.get(RECLASSIFY).status_code == 405


def test_the_runner_needs_a_login(client, owned_library, game):
    session = a_written_session(owned_library, game)

    response = client.post(RECLASSIFY, {STATEMENT_FIELD: some(session)})

    assert response.status_code == 302
    assert PlayerSession.objects.get(pk=session.pk).removed_at is None
