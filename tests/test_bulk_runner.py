"""The runner: one route, two POSTs, told apart by the token."""

import html as html_module
import json
import logging
import uuid
from datetime import date, timedelta

import pytest
from django.contrib.messages import get_messages
from django.contrib.messages.storage.base import Message
from django.urls import reverse
from django.utils import timezone
from session_rows import duration_only_row, tracked_run

from common.duration_presentation import (
    DEFAULT_DURATION_FORMAT_PROFILE,
    DurationPresentation,
)
from games import bulk_reclassification
from games.bulk_actions import _TABLE, BULK_ACTIONS, BulkAction, RowOutcome
from games.bulk_reclassification import (
    IN_THE_BUCKET,
    NOT_AVAILABLE,
    REVIEW_THRESHOLD_HOURS,
    UNDER_THRESHOLD,
)
from games.commands.session_reclassification import statement_from_session
from games.models import (
    Game,
    HistoricalPlaytime,
    LibraryEvent,
    PlayerSession,
    Playthrough,
    PlaythroughKind,
)
from games.reads.events import batch_aggregate_ids
from games.views.bulk import (
    ENDED_BY_A_DEFECT,
    NOT_THIS_BATCH,
    PROGRESS_FIELD,
    STATEMENT_FIELD,
    STOP_FIELD,
    STOPPED_BY_HAND,
    TOKEN_FIELD,
    UNKNOWN_ACT,
)
from games.views.session_reclassification import review_filter
from games.writes.historical_playtime import restate_historical_playtime
from games.writes.playersession import reclassify_session, undo_reclassification
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


def test_a_confirmation_shows_the_columns_the_act_states(
    client_in, owned_library, game
):
    """Through the route, so the presentations reach the cells."""
    session = a_written_session(owned_library, game)

    html = confirm(client_in, some(session)).content.decode()

    for heading in ("Game", "Day", "Duration"):
        assert heading in html
    assert str(session.effective_day) in html


def test_a_confirmation_names_the_act_and_what_it_counts(
    client_in, owned_library, game
):
    """The noun is the act's own, so a second act needs no second page."""
    action = BULK_ACTIONS["session.reclassify"]
    one = a_written_session(owned_library, game)
    two = a_written_session(owned_library, game, day=date(2026, 3, 6))

    alone = confirm(client_in, some(one)).content.decode()
    both = confirm(client_in, some(one, two)).content.decode()

    assert f"{action.label}: 1 {action.subject}?" in alone
    assert f"{action.label}: 2 {action.subject}s?" in both


def test_a_confirmation_prints_a_duration_the_way_a_person_reads_it(
    client_in, owned_library, game
):
    """`9:00:00` is a column, not a sentence.

    Every other page states elapsed time through the person's own
    duration setting, and the confirmation is where this act's rows are
    read before it runs.
    """
    session = a_written_session(owned_library, game)
    presentation = DurationPresentation(DEFAULT_DURATION_FORMAT_PROFILE, "en-us")

    html = confirm(client_in, some(session)).content.decode()

    assert presentation.format(session.effective_duration) in html
    assert str(session.effective_duration) not in html


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


# ── The act ──────────────────────────────────────────────────────────────────


def act(client, response, url=RECLASSIFY, **extra):
    """The second POST: the token, so it acts."""
    fields = posted(response)
    return client.post(url, {**fields, **extra})


def tally_of(response) -> dict:
    return json.loads(posted(response)[PROGRESS_FIELD])


def test_a_batch_converts_every_row_and_returns(client_in, owned_library, game):
    sessions = [
        a_written_session(owned_library, game, day=A_DAY + timedelta(days=offset))
        for offset in range(3)
    ]

    done = act(client_in, confirm(client_in, some(*sessions)))

    assert done.status_code == 302
    assert HistoricalPlaytime.objects.count() == 3
    for session in sessions:
        assert PlayerSession.objects.get(pk=session.pk).removed_at is not None


def test_every_chunk_of_a_batch_shares_one_correlation_id(
    client_in, owned_library, game, monkeypatch
):
    """The token is the batch's identity.

    A fresh correlation id per request would make a two-chunk batch two
    batches, and its Undo would find half of it.
    """
    monkeypatch.setattr("games.views.bulk.CHUNK_BUDGET", timedelta(0))
    sessions = [
        a_written_session(owned_library, game, day=A_DAY + timedelta(days=offset))
        for offset in range(3)
    ]
    confirmation = confirm(client_in, some(*sessions))
    token = posted(confirmation)[TOKEN_FIELD]

    response = act(client_in, confirmation)
    #: Each request spends its budget after one row.
    assert response.status_code == 200
    assert tally_of(response)["done"] == 1
    while response.status_code == 200:
        response = act(client_in, response)

    assert response.status_code == 302
    assert HistoricalPlaytime.objects.count() == 3
    correlations = set(
        LibraryEvent.objects.filter(
            event_type="library.playersession.reclassified"
        ).values_list("correlation_id", flat=True)
    )
    assert correlations == {uuid.UUID(token)}


def test_the_same_token_twice_converts_nothing_twice(client_in, owned_library, game):
    session = a_written_session(owned_library, game)
    confirmation = confirm(client_in, some(session))

    first = act(client_in, confirmation)
    second = act(client_in, confirmation)

    assert first.status_code == second.status_code == 302
    assert HistoricalPlaytime.objects.count() == 1


def test_a_row_gone_since_the_confirmation_is_counted_lost(
    client_in, owned_library, game, monkeypatch
):
    monkeypatch.setattr("games.views.bulk.CHUNK_BUDGET", timedelta(0))
    staying = a_written_session(owned_library, game)
    leaving = a_written_session(owned_library, game, day=date(2026, 3, 6))
    confirmation = confirm(client_in, some(staying, leaving))

    response = act(client_in, confirmation)
    #: Gone between the confirmation and its own chunk.
    PlayerSession.objects.filter(pk=leaving.pk).update(removed_at=timezone.now())
    while response.status_code == 200:
        response = act(client_in, response)

    assert response.status_code == 302
    assert HistoricalPlaytime.objects.count() == 1


def test_a_refused_row_leaves_the_rest_done(client_in, owned_library, game):
    wanted = a_written_session(owned_library, game)
    short = a_written_session(
        owned_library, game, day=date(2026, 3, 6), duration=timedelta(hours=1)
    )
    #: The short row is posted straight to the act, past the review.
    confirmation = confirm(client_in, some(wanted))
    fields = posted(confirmation)
    fields[PROGRESS_FIELD] = json.dumps({"rows": [str(wanted.pk), str(short.pk)]})

    response = client_in.post(RECLASSIFY, fields)

    assert response.status_code == 302
    assert HistoricalPlaytime.objects.count() == 1


def test_a_refused_row_is_counted_and_its_reason_reaches_the_person(
    client_in, owned_library, game
):
    """The toast says how many were left, and a second says why.

    A count with no reason sends a person back to the list to work out
    which rows those were, and a reason with no count hides that one
    sentence stood over several rows.
    """
    wanted = a_written_session(owned_library, game)
    short = a_written_session(
        owned_library, game, day=date(2026, 3, 6), duration=timedelta(hours=1)
    )
    brief = a_written_session(
        owned_library, game, day=date(2026, 3, 7), duration=timedelta(hours=2)
    )

    asked = confirm(client_in, some(wanted, short, brief))
    assert "2 of them will be left as they are:" in asked.content.decode()

    done = act(client_in, asked)

    assert done.status_code == 302
    assert [str(message) for message in toasts(done)] == [
        "1 of 1 done, 2 left as they are.",
        UNDER_THRESHOLD,
    ]


def test_a_row_lost_in_one_chunk_is_still_counted_by_the_next(
    client_in, owned_library, game, monkeypatch
):
    """The tally rides the form, so a count must survive the round trip.

    A row counted lost in the chunk that met it is answered for by a
    later chunk, and a counter the progress field dropped would make
    the batch's own answer disagree with what it did.
    """
    monkeypatch.setattr("games.views.bulk.CHUNK_BUDGET", timedelta(0))
    sessions = [
        a_written_session(owned_library, game, day=A_DAY + timedelta(days=offset))
        for offset in range(3)
    ]
    confirmation = confirm(client_in, some(*sessions))

    response = act(client_in, confirmation)
    #: Gone between the first chunk and the one that would reach it.
    PlayerSession.objects.filter(pk=sessions[1].pk).update(removed_at=timezone.now())
    middle = act(client_in, response)
    assert tally_of(middle)["lost"] == 1
    last = act(client_in, middle)

    assert last.status_code == 302
    assert [str(message) for message in toasts(last)] == [
        "2 of 3 done, 1 no longer there.",
        NOT_AVAILABLE,
    ]


def test_every_row_left_alone_is_logged_with_its_library(
    client_in, owned_library, game, caplog, capture_games_logger
):
    """The page prints sentences; the log prints keys.

    A person reading a toast wants to know how many were left and why.
    Whoever reads the log afterwards wants to know which ones.
    """
    short = a_written_session(owned_library, game, duration=timedelta(hours=1))
    fine = a_written_session(owned_library, game, day=date(2026, 3, 6))

    with capture_games_logger() as captured:
        #: The fixture pins WARNING; a row left alone is ordinary.
        captured.set_level(logging.INFO, logger="games")
        act(client_in, confirm(client_in, some(short, fine)))

    assert HistoricalPlaytime.objects.count() == 1
    said = " ".join(record.message for record in caplog.records)
    assert str(short.pk) in said
    assert str(owned_library.pk) in said


def test_a_defect_ends_the_batch_and_leaves_the_done_rows_done(
    client_in, owned_library, game, monkeypatch
):
    """The act stops; what committed stays committed.

    The declaration is frozen, so this breaks the write the act calls
    rather than the act itself -- which is also the honest shape of a
    defect: ours, underneath the command.
    """
    from games.writes.answers import DEFECT_STATUS, CommandFailed

    sessions = [
        a_written_session(owned_library, game, day=A_DAY + timedelta(days=offset))
        for offset in range(3)
    ]
    real = bulk_reclassification.reclassify_session
    calls = {"n": 0}

    def breaks_after_one(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] > 1:
            raise CommandFailed("A problem on our side.", DEFECT_STATUS)
        return real(*args, **kwargs)

    monkeypatch.setattr(bulk_reclassification, "reclassify_session", breaks_after_one)

    response = act(client_in, confirm(client_in, some(*sessions)))

    assert response.status_code == DEFECT_STATUS
    assert HistoricalPlaytime.objects.count() == 1
    #: A defect admits no second press.
    assert (
        BULK_ACTIONS["session.reclassify"].confirm_label.encode()
        not in response.content
    )


def test_a_row_the_library_does_not_hold_ends_the_batch(
    client_in, owned_library, game, monkeypatch
):
    """The leg re-resolved these rows, so nothing inside can miss."""
    from django.http import Http404

    from games.writes.answers import DEFECT_STATUS

    sessions = [
        a_written_session(owned_library, game, day=A_DAY + timedelta(days=offset))
        for offset in range(3)
    ]
    real = bulk_reclassification.reclassify_session
    calls = {"n": 0}

    def absent_after_one(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] > 1:
            raise Http404("No such session.")
        return real(*args, **kwargs)

    monkeypatch.setattr(bulk_reclassification, "reclassify_session", absent_after_one)

    response = act(client_in, confirm(client_in, some(*sessions)))

    assert response.status_code == DEFECT_STATUS
    assert HistoricalPlaytime.objects.count() == 1
    assert (
        BULK_ACTIONS["session.reclassify"].confirm_label.encode()
        not in response.content
    )


def test_a_defect_still_offers_the_batch_its_undo(
    client_in, owned_library, game, monkeypatch
):
    """The rows it did reach stay done, so the way back must be offered.

    A batch that finishes offers its Undo on the answer it redirects
    to, and a batch a defect stopped never reaches one.
    """
    from games.writes.answers import DEFECT_STATUS, CommandFailed

    sessions = [
        a_written_session(owned_library, game, day=A_DAY + timedelta(days=offset))
        for offset in range(2)
    ]
    real = bulk_reclassification.reclassify_session
    calls = {"n": 0}

    def breaks_after_one(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] > 1:
            raise CommandFailed("A problem on our side.", DEFECT_STATUS)
        return real(*args, **kwargs)

    monkeypatch.setattr(bulk_reclassification, "reclassify_session", breaks_after_one)
    confirmation = confirm(client_in, some(*sessions))
    token = posted(confirmation)[TOKEN_FIELD]

    stopped = act(client_in, confirmation)

    assert stopped.status_code == DEFECT_STATUS
    assert [toast["action"]["url"] for toast in page_toasts(stopped)] == [
        undo_url(token)
    ]

    undone = client_in.post(undo_url(token), {})

    assert undone.status_code == 302
    assert PlayerSession.objects.alive().count() == 2
    assert HistoricalPlaytime.objects.alive().count() == 0


def test_an_undo_a_defect_stopped_offers_no_undo_of_its_own(
    client_in, owned_library, game, monkeypatch
):
    """The answer's rule, read by the defect page too."""
    from games.writes.answers import DEFECT_STATUS, CommandFailed

    session = a_written_session(owned_library, game)
    confirmation = confirm(client_in, some(session))
    token = posted(confirmation)[TOKEN_FIELD]
    landed(client_in, act(client_in, confirmation))

    def breaks(*args, **kwargs):
        raise CommandFailed("A problem on our side.", DEFECT_STATUS)

    monkeypatch.setattr(bulk_reclassification, "undo_reclassification", breaks)

    stopped = client_in.post(undo_url(token), {})

    assert stopped.status_code == DEFECT_STATUS
    assert [toast.get("action") for toast in page_toasts(stopped)] == [None]


def test_a_progress_page_carries_the_tally_and_the_rest(
    client_in, owned_library, game, monkeypatch
):
    monkeypatch.setattr("games.views.bulk.CHUNK_BUDGET", timedelta(0))
    sessions = [
        a_written_session(owned_library, game, day=A_DAY + timedelta(days=offset))
        for offset in range(3)
    ]

    response = act(client_in, confirm(client_in, some(*sessions)))

    carried = tally_of(response)
    assert carried["done"] == 1
    assert len(carried["rows"]) == 2


def test_a_waypoint_says_what_has_been_left_alone_so_far(
    client_in, owned_library, game, monkeypatch
):
    """A batch of thousands is read at its waypoints, not at its answer.

    The reasons ride the tally from the confirmation onwards, so the
    page a person watches can say them rather than holding them back
    until the batch ends.
    """
    monkeypatch.setattr("games.views.bulk.CHUNK_BUDGET", timedelta(0))
    sessions = [
        a_written_session(owned_library, game, day=A_DAY + timedelta(days=offset))
        for offset in range(2)
    ]
    short = a_written_session(
        owned_library, game, day=date(2026, 4, 1), duration=timedelta(hours=1)
    )

    progressing = act(client_in, confirm(client_in, some(*sessions, short)))

    assert progressing.status_code == 200
    page = progressing.content.decode()
    assert "1 left as it is so far:" in page
    assert html_module.escape(UNDER_THRESHOLD) in page


def test_stopping_ends_the_batch_where_it_stands(
    client_in, owned_library, game, monkeypatch
):
    monkeypatch.setattr("games.views.bulk.CHUNK_BUDGET", timedelta(0))
    sessions = [
        a_written_session(owned_library, game, day=A_DAY + timedelta(days=offset))
        for offset in range(3)
    ]
    progressing = act(client_in, confirm(client_in, some(*sessions)))

    stopped = act(client_in, progressing, **{STOP_FIELD: "1"})

    assert stopped.status_code == 302
    assert HistoricalPlaytime.objects.count() == 1


def test_stopping_names_the_rows_it_left(
    client_in, owned_library, game, monkeypatch, caplog, capture_games_logger
):
    """A Stop leaves rows behind, and the log is where they are named.

    The toast says how far the batch got; nothing else ever says which
    rows it did not reach, and a person who presses Stop by accident
    has only the log to read them back from.
    """
    monkeypatch.setattr("games.views.bulk.CHUNK_BUDGET", timedelta(0))
    sessions = [
        a_written_session(owned_library, game, day=A_DAY + timedelta(days=offset))
        for offset in range(3)
    ]
    confirmation = confirm(client_in, some(*sessions))
    token = posted(confirmation)[TOKEN_FIELD]
    progressing = act(client_in, confirmation)

    with capture_games_logger() as captured:
        captured.set_level(logging.INFO, logger="games")
        act(client_in, progressing, **{STOP_FIELD: "1"})

    said = " ".join(record.message for record in caplog.records)
    left = [key for key in tally_of(progressing)["rows"]]
    assert len(left) == 2
    for key in left:
        assert key in said
    assert STOPPED_BY_HAND in said
    assert token in said


def test_a_defect_names_the_rows_it_left(
    client_in, owned_library, game, monkeypatch, caplog, capture_games_logger
):
    """The row that met the defect, and the rows behind it.

    No dispatch answered for any of them, so the tally counts none of
    them, and the log is the only record that they were part of the
    batch at all.
    """
    from games.writes.answers import DEFECT_STATUS, CommandFailed

    sessions = [
        a_written_session(owned_library, game, day=A_DAY + timedelta(days=offset))
        for offset in range(3)
    ]
    real = bulk_reclassification.reclassify_session
    calls = {"n": 0}

    def breaks_after_one(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] > 1:
            raise CommandFailed("A problem on our side.", DEFECT_STATUS)
        return real(*args, **kwargs)

    monkeypatch.setattr(bulk_reclassification, "reclassify_session", breaks_after_one)
    confirmation = confirm(client_in, some(*sessions))
    ordered = tally_of(confirmation)["rows"]

    with capture_games_logger() as captured:
        captured.set_level(logging.INFO, logger="games")
        stopped = act(client_in, confirmation)

    assert stopped.status_code == DEFECT_STATUS
    said = " ".join(record.message for record in caplog.records)
    #: The row the defect was met on, and the one it never reached.
    assert ordered[1] in said
    assert ordered[2] in said
    assert ENDED_BY_A_DEFECT in said


# ── The batch's Undo ─────────────────────────────────────────────────────────


def undo_url(token: str) -> str:
    return reverse("games:undo_bulk_action", args=[token])


def toasts(response) -> list[Message]:
    return list(get_messages(response.wsgi_request))


def landed(client, response) -> None:
    """Follow the answer, so a page reads its toasts and the queue empties.

    The test client follows nothing on its own, and an unread toast is
    still queued when the next request loads the storage.
    """
    assert response.status_code == 302
    client.get(response["Location"])


def page_toasts(response) -> list[dict]:
    """The toasts a rendered page carries, as it hands them to the element."""
    html = response.content.decode()
    marker = '<script id="django-messages" type="application/json">'
    start = html.index(marker) + len(marker)
    return json.loads(
        html_module.unescape(html[start : html.index("</script>", start)])
    )


def actions_of(response) -> list[str]:
    """The URL each toast's action posts to, for the toasts that carry one."""
    return [
        json.loads(message.extra_tags)["action"]["url"]
        for message in toasts(response)
        if message.extra_tags
    ]


def test_the_answer_of_a_batch_offers_the_batch_its_undo(
    client_in, owned_library, game
):
    session = a_written_session(owned_library, game)
    confirmation = confirm(client_in, some(session))
    token = posted(confirmation)[TOKEN_FIELD]

    done = act(client_in, confirmation)

    assert actions_of(done) == [undo_url(token)]


def test_a_batch_that_did_nothing_offers_no_undo(client_in, owned_library, game):
    """Nothing to take back, so no press that says there is."""
    session = a_written_session(owned_library, game, duration=timedelta(hours=1))

    done = act(client_in, confirm(client_in, some(session)))

    assert actions_of(done) == []


def test_undoing_a_batch_restores_every_session_and_removes_every_record(
    client_in, owned_library, game
):
    sessions = [
        a_written_session(owned_library, game, day=A_DAY + timedelta(days=offset))
        for offset in range(3)
    ]
    confirmation = confirm(client_in, some(*sessions))
    token = posted(confirmation)[TOKEN_FIELD]
    act(client_in, confirmation)

    undone = client_in.post(undo_url(token), {})

    assert undone.status_code == 302
    assert PlayerSession.objects.alive().count() == 3
    assert HistoricalPlaytime.objects.alive().count() == 0


def test_a_batch_undo_reads_only_the_aggregate_its_inverse_takes(
    client_in, owned_library, game
):
    """The batch wrote two aggregates; its inverse reads one.

    Each row appends a created record beside the reclassified session,
    under one correlation. An Undo that handed every aggregate of the
    batch to a command that reads sessions would refuse a record's key
    for every row of its own batch.
    """
    sessions = [
        a_written_session(owned_library, game, day=A_DAY + timedelta(days=offset))
        for offset in range(2)
    ]
    confirmation = confirm(client_in, some(*sessions))
    token = posted(confirmation)[TOKEN_FIELD]
    landed(client_in, act(client_in, confirmation))
    batch = uuid.UUID(token)
    #: The batch really is mixed, or this proves nothing.
    assert batch_aggregate_ids(owned_library, batch, "historicalplaytime")
    assert len(batch_aggregate_ids(owned_library, batch, "playersession")) == 2

    undone = client_in.post(undo_url(token), {})

    assert [str(message) for message in toasts(undone)] == ["2 of 2 done."]
    assert PlayerSession.objects.alive().count() == 2


def test_a_record_restated_since_is_named_and_the_rest_are_undone(
    client_in, owned_user, owned_library, game
):
    sessions = [
        a_written_session(owned_library, game, day=A_DAY + timedelta(days=offset))
        for offset in range(2)
    ]
    confirmation = confirm(client_in, some(*sessions))
    token = posted(confirmation)[TOKEN_FIELD]
    landed(client_in, act(client_in, confirmation))
    moved = HistoricalPlaytime.objects.get(reclassified_from=sessions[0])
    restate_historical_playtime(
        owned_user,
        moved,
        statement_from_session(sessions[0])._replace(note="Counted again."),
        correlation_id=uuid.uuid7(),
    )

    undone = client_in.post(undo_url(token), {})

    assert undone.status_code == 302
    assert PlayerSession.objects.get(pk=sessions[0].pk).removed_at is not None
    assert PlayerSession.objects.get(pk=sessions[1].pk).removed_at is None
    #: One refused row of an Undo, counted and said in its own number.
    first = next(str(message) for message in toasts(undone))
    assert first == "1 of 2 done, 1 left as it is."


def test_a_batch_undo_chunks_under_its_own_token(
    client_in, owned_library, game, monkeypatch
):
    """A batch of its own: its own token, and its own correlation id.

    Sharing the act's correlation would make the Undo part of the batch
    it undoes, and a second Undo would read its own appends as rows.
    """
    sessions = [
        a_written_session(owned_library, game, day=A_DAY + timedelta(days=offset))
        for offset in range(3)
    ]
    confirmation = confirm(client_in, some(*sessions))
    token = posted(confirmation)[TOKEN_FIELD]
    act(client_in, confirmation)
    monkeypatch.setattr("games.views.bulk.CHUNK_BUDGET", timedelta(0))

    response = client_in.post(undo_url(token), {})
    assert response.status_code == 200
    undo_token = posted(response)[TOKEN_FIELD]
    assert undo_token != token
    while response.status_code == 200:
        response = act(client_in, response, url=undo_url(token))

    assert response.status_code == 302
    assert PlayerSession.objects.alive().count() == 3
    restored = LibraryEvent.objects.filter(
        library=owned_library, event_type="library.playersession.restored"
    )
    assert {event.correlation_id for event in restored} == {uuid.UUID(undo_token)}


def test_a_row_undone_by_hand_is_counted_apart_from_one_the_undo_moved(
    client_in, owned_user, owned_library, game
):
    """A count of what was done must not claim work nobody did.

    The single-row Undo took one of these back already, so the batch's
    Undo meets a command that answers Unchanged, which is neither a
    row it moved nor a row it was refused.
    """
    sessions = [
        a_written_session(owned_library, game, day=A_DAY + timedelta(days=offset))
        for offset in range(2)
    ]
    confirmation = confirm(client_in, some(*sessions))
    token = posted(confirmation)[TOKEN_FIELD]
    landed(client_in, act(client_in, confirmation))
    undo_reclassification(
        owned_user,
        PlayerSession.objects.get(pk=sessions[0].pk),
        correlation_id=uuid.uuid7(),
    )

    undone = client_in.post(undo_url(token), {})

    assert undone.status_code == 302
    assert [str(message) for message in toasts(undone)] == [
        "1 of 2 done, 1 already done."
    ]
    assert PlayerSession.objects.alive().count() == 2


def test_an_undo_offers_no_further_undo(client_in, owned_library, game):
    session = a_written_session(owned_library, game)
    confirmation = confirm(client_in, some(session))
    token = posted(confirmation)[TOKEN_FIELD]
    landed(client_in, act(client_in, confirmation))

    undone = client_in.post(undo_url(token), {})

    assert actions_of(undone) == []


def test_an_undo_leaves_alone_a_key_its_batch_never_wrote(
    client_in, owned_library, game
):
    """A forged progress is counted and lost, as on the way forward.

    The tally rides the form, so a person can name any key in it. The
    Undo acts on the rows its own batch wrote, and a key that is not one
    of them reaches no dispatch to answer a defect.
    """
    session = a_written_session(owned_library, game)
    confirmation = confirm(client_in, some(session))
    token = posted(confirmation)[TOKEN_FIELD]
    landed(client_in, act(client_in, confirmation))

    undone = client_in.post(
        undo_url(token),
        {
            TOKEN_FIELD: str(uuid.uuid7()),
            PROGRESS_FIELD: json.dumps(
                {
                    "rows": [str(uuid.uuid7())],
                    "done": 0,
                    "unchanged": 0,
                    "lost": 0,
                    "refused": 0,
                    "reasons": [],
                    "total": 1,
                }
            ),
        },
    )

    assert undone.status_code == 302
    said = [str(message) for message in toasts(undone)]
    assert NOT_THIS_BATCH in said
    assert any("1 no longer there" in sentence for sentence in said)
    #: The batch's own row was never touched by the forgery.
    assert PlayerSession.objects.get(pk=session.pk).removed_at is not None


def test_a_correlation_that_names_no_batch_is_not_found(client_in, owned_library):
    response = client_in.post(undo_url(str(uuid.uuid7())), {})

    assert response.status_code == 404


def test_another_librarys_batch_is_not_found(
    client_in, client, owned_library, django_user_model, game
):
    """The read is scoped, or a guessed token undoes another library's act."""
    stranger = django_user_model.objects.create_user("stranger", password="secret123")
    session = a_written_session(owned_library, game)
    confirmation = confirm(client_in, some(session))
    token = posted(confirmation)[TOKEN_FIELD]
    act(client_in, confirmation)
    client.force_login(stranger)

    response = client.post(undo_url(token), {})

    assert response.status_code == 404
    assert PlayerSession.objects.get(pk=session.pk).removed_at is not None


def test_an_act_the_table_no_longer_holds_refuses(client_in, owned_library, game):
    """A batch whose act was retired states a sentence, not a traceback."""
    session = a_written_session(owned_library, game)
    confirmation = confirm(client_in, some(session))
    token = posted(confirmation)[TOKEN_FIELD]
    act(client_in, confirmation)
    LibraryEvent.objects.filter(correlation_id=uuid.UUID(token)).update(
        source_metadata={"bulk": {"action": "session.retired"}}
    )

    response = client_in.post(undo_url(token), {})

    assert response.status_code == 400
    assert UNKNOWN_ACT.encode() in response.content
    assert PlayerSession.objects.get(pk=session.pk).removed_at is not None


def test_an_ordinary_act_is_no_batch(client_in, owned_user, owned_library, game):
    """One row's own button writes no batch, so its correlation undoes none."""
    session = a_written_session(owned_library, game)
    alone = uuid.uuid7()
    reclassify_session(
        owned_user,
        session,
        statement_from_session(session),
        idempotency_key=f"one-{session.pk}",
        correlation_id=alone,
    )

    response = client_in.post(undo_url(str(alone)), {})

    assert response.status_code == 404


def test_the_batch_undo_needs_a_login(client, owned_library, game):
    response = client.post(undo_url(str(uuid.uuid7())), {})

    assert response.status_code == 302


# ── The choice a leg carries ─────────────────────────────────────────────────


@pytest.fixture
def recorded_choices(reclassify_declaration):
    """An act whose run remembers what it was handed."""
    seen: list[str] = []

    def run(actor, row, choice, idempotency_key, correlation_id):
        seen.append(choice)
        return RowOutcome.MOVED

    def inverse(actor, row_id, choice, idempotency_key, correlation_id):
        seen.append(choice)
        return RowOutcome.MOVED

    BulkAction(
        name="session.recorder",
        label=reclassify_declaration.label,
        title=reclassify_declaration.title,
        confirm_label=reclassify_declaration.confirm_label,
        subject=reclassify_declaration.subject,
        cardinality=reclassify_declaration.cardinality,
        color=reclassify_declaration.color,
        inverse_aggregate=reclassify_declaration.inverse_aggregate,
        fallback=reclassify_declaration.fallback,
        scope=reclassify_declaration.scope,
        resolve=reclassify_declaration.resolve,
        run=run,
        inverse=inverse,
        preview=reclassify_declaration.preview,
    )
    yield seen
    _TABLE.pop("session.recorder")


@pytest.fixture
def reclassify_declaration():
    return BULK_ACTIONS["session.reclassify"]


def test_the_runner_hands_an_act_the_legs_choice(
    client_in, owned_library, game, recorded_choices
):
    url = reverse("games:run_bulk_action", args=["session.recorder"])
    session = a_written_session(owned_library, game)

    fields = posted(confirm(client_in, some(session), url=url))
    client_in.post(url, fields)

    assert recorded_choices == [""]
