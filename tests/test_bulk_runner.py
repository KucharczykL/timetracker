"""The runner: one route, two POSTs, told apart by the token."""

import html as html_module
import json
import logging
import uuid
from dataclasses import replace
from datetime import date, timedelta
from typing import NamedTuple

import pytest
from bulk_posts import newest_batch, said
from django.contrib.messages import get_messages
from django.contrib.messages.storage.base import Message
from django.urls import reverse
from django.utils import timezone
from session_rows import duration_only_row, tracked_run

from common.components.primitives import Input
from common.duration_presentation import (
    DEFAULT_DURATION_FORMAT_PROFILE,
    DurationPresentation,
)
from games import bulk_reclassification
from games.bulk_actions import _TABLE, BULK_ACTIONS, BulkAction
from games.bulk_jobs import ENDED_BY_A_DEFECT, STOPPED_BY_HAND, Tally, batch_toast
from games.bulk_parts import BulkChoice, Control, RefusedAct, RowOutcome
from games.bulk_reclassification import (
    IN_THE_BUCKET,
    NOT_AVAILABLE,
    REVIEW_THRESHOLD_HOURS,
    SHORT_ONE,
)
from games.commands.session_reclassification import statement_from_session
from games.events.dispatch import CommandRejected
from games.models import (
    BulkBatch,
    Game,
    HistoricalPlaytime,
    LibraryEvent,
    PlayerSession,
    Playthrough,
    PlaythroughKind,
)
from games.reads.events import batch_aggregate_ids
from games.views.bulk import (
    CHOICE_FIELD,
    NOTHING_TO_UNDO,
    PROGRESS_FIELD,
    STATEMENT_FIELD,
    TOKEN_FIELD,
    UNDO_OF_AN_UNDO,
    UNKNOWN_ACT,
)
from games.views.session_reclassification import review_filter
from games.writes.historical_playtime import restate_historical_playtime
from games.writes.playersession import (
    reclassify_session,
    remove_session,
    undo_reclassification,
)
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


def a_bucket(library, game) -> Playthrough:
    """The game's imported-history bucket."""
    return Playthrough.objects.create(
        pk=uuid.uuid7(),
        library=library,
        player_game=tracked_run(library, game).player_game,
        kind=PlaythroughKind.IMPORTED_HISTORY,
        created_at=timezone.now(),
    )


def a_bucket_session(bucket, day=A_DAY):
    """A written-down row the act refuses."""
    return duration_only_row(bucket, day, LONG_ENOUGH)


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
    for name in (TOKEN_FIELD, PROGRESS_FIELD, CHOICE_FIELD):
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
    note = html_module.escape(SHORT_ONE.format(hours=REVIEW_THRESHOLD_HOURS))
    assert note not in response.content.decode()


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
    in_the_bucket = a_bucket_session(a_bucket(owned_library, game))

    response = confirm(client_in, some(in_the_bucket))

    assert IN_THE_BUCKET.encode() in response.content


def test_a_short_row_is_noted_and_converted_all_the_same(
    client_in, owned_library, game
):
    """A short row is noted, then converted."""
    short = a_written_session(owned_library, game, duration=timedelta(hours=1))

    asked = confirm(client_in, some(short))
    page = asked.content.decode()
    assert html_module.escape(SHORT_ONE.format(hours=REVIEW_THRESHOLD_HOURS)) in page
    assert "will be left as" not in page

    done = act(client_in, asked)

    assert done.status_code == 302
    assert said_by(newest_batch(owned_library)) == ["1 of 1 done."]
    assert HistoricalPlaytime.objects.count() == 1


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


def test_a_confirmation_heads_the_act_with_what_it_counts(
    client_in, owned_library, game
):
    """The heading counts; no question repeats it."""
    action = BULK_ACTIONS["session.reclassify"]
    one = a_written_session(owned_library, game)
    two = a_written_session(owned_library, game, day=date(2026, 3, 6))

    alone = confirm(client_in, some(one)).content.decode()
    both = confirm(client_in, some(one, two)).content.decode()

    assert action.title.one in alone
    assert "Record 2 sessions as historical playtime" in both
    assert f"{action.label}:" not in alone + both


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


def batch_of(library, token) -> BulkBatch:
    return BulkBatch.objects.get(library=library, token=token)


def said_by(batch: BulkBatch) -> list[str]:
    """The tally sentence, then each reason."""
    batch.refresh_from_db()
    return [Tally.of(batch).sentence(ended=batch.is_terminal), *batch.reasons]


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
    monkeypatch.setattr("games.bulk_jobs.CHUNK_BUDGET", timedelta(0))
    sessions = [
        a_written_session(owned_library, game, day=A_DAY + timedelta(days=offset))
        for offset in range(3)
    ]
    confirmation = confirm(client_in, some(*sessions))
    token = posted(confirmation)[TOKEN_FIELD]

    response = act(client_in, confirmation)

    assert response.status_code == 302
    #: One row a chunk.
    assert batch_of(owned_library, token).chunk == 2
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
    client_in, owned_library, game
):
    staying = a_written_session(owned_library, game)
    leaving = a_written_session(owned_library, game, day=date(2026, 3, 6))
    confirmation = confirm(client_in, some(staying, leaving))
    #: Gone between the confirmation and the press.
    PlayerSession.objects.filter(pk=leaving.pk).update(removed_at=timezone.now())

    response = act(client_in, confirmation)

    assert response.status_code == 302
    assert HistoricalPlaytime.objects.count() == 1
    assert newest_batch(owned_library).lost == 1


def test_a_refused_row_leaves_the_rest_done(client_in, owned_library, game):
    wanted = a_written_session(owned_library, game)
    in_the_bucket = a_bucket_session(a_bucket(owned_library, game))
    #: Posted straight to the act.
    confirmation = confirm(client_in, some(wanted))
    fields = posted(confirmation)
    fields[PROGRESS_FIELD] = json.dumps(
        {"rows": [str(wanted.pk), str(in_the_bucket.pk)]}
    )

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
    bucket = a_bucket(owned_library, game)
    imported = a_bucket_session(bucket, day=date(2026, 3, 6))
    also_imported = a_bucket_session(bucket, day=date(2026, 3, 7))

    asked = confirm(client_in, some(wanted, imported, also_imported))
    assert "2 of them will be left as they are:" in asked.content.decode()

    done = act(client_in, asked)

    assert done.status_code == 302
    assert said_by(newest_batch(owned_library)) == [
        "1 of 1 done, 2 left as they are.",
        IN_THE_BUCKET,
    ]


def test_a_row_lost_in_one_chunk_is_still_counted_by_the_next(
    client_in, owned_library, game, monkeypatch, held_batches
):
    """The tally survives between chunks."""
    monkeypatch.setattr("games.bulk_jobs.CHUNK_BUDGET", timedelta(0))
    sessions = [
        a_written_session(owned_library, game, day=A_DAY + timedelta(days=offset))
        for offset in range(3)
    ]
    act(client_in, confirm(client_in, some(*sessions)))
    batch = newest_batch(owned_library)
    held_batches.run_one()
    #: Gone between the first chunk and the one that would reach it.
    ordered = [uuid.UUID(key) for key in batch.rows]
    PlayerSession.objects.filter(pk=ordered[1]).update(removed_at=timezone.now())

    held_batches.run_all()

    assert said_by(batch) == ["2 of 3 done, 1 no longer there.", NOT_AVAILABLE]


def test_every_row_left_alone_is_logged_with_its_library(
    client_in, owned_library, game, caplog, capture_games_logger
):
    """The page prints sentences; the log prints keys.

    A person reading a toast wants to know how many were left and why.
    Whoever reads the log afterwards wants to know which ones.
    """
    in_the_bucket = a_bucket_session(a_bucket(owned_library, game))
    fine = a_written_session(owned_library, game, day=date(2026, 3, 6))

    with capture_games_logger() as captured:
        #: The fixture pins WARNING; a row left alone is ordinary.
        captured.set_level(logging.INFO, logger="games")
        act(client_in, confirm(client_in, some(in_the_bucket, fine)))

    assert HistoricalPlaytime.objects.count() == 1
    said = " ".join(record.message for record in caplog.records)
    assert str(in_the_bucket.pk) in said
    assert str(owned_library.pk) in said


def test_a_defect_ends_the_batch_and_leaves_the_done_rows_done(
    client_in, owned_library, game, monkeypatch, failing_batches
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

    assert response.status_code == 302
    assert HistoricalPlaytime.objects.count() == 1
    batch = newest_batch(owned_library)
    assert batch.state == BulkBatch.State.FAILED
    assert (batch.done, batch.position) == (1, 1)


def test_a_refusal_before_the_resolve_heads_in_the_plural(client_in, owned_library):
    """`_act_refused` holds a sentence and no rows.

    An act turned down before it resolved anything states nothing about how
    many rows it would have touched, so the heading counts none.
    """
    response = client_in.post(
        reverse("games:run_bulk_action", args=["session.remove"]),
        {STATEMENT_FIELD: "not a statement"},
    )

    page = response.content.decode()
    assert response.status_code == 400
    assert "Remove these sessions" in page
    assert "{count}" not in page


def test_a_row_the_library_does_not_hold_ends_the_batch(
    client_in, owned_library, game, monkeypatch, failing_batches
):
    """The chunk re-resolved these rows, so nothing inside can miss."""
    from django.http import Http404

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

    act(client_in, confirm(client_in, some(*sessions)))

    assert HistoricalPlaytime.objects.count() == 1
    assert newest_batch(owned_library).state == BulkBatch.State.FAILED


def test_a_defect_still_offers_the_batch_its_undo(
    client_in, owned_library, game, monkeypatch, failing_batches
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

    act(client_in, confirmation)

    toast = batch_toast(batch_of(owned_library, token))
    assert toast["type"] == "error"
    assert toast.get("action") == {"label": "Undo", "url": undo_url(token)}

    undone = client_in.post(undo_url(token), {})

    assert undone.status_code == 302
    assert PlayerSession.objects.alive().count() == 2
    assert HistoricalPlaytime.objects.alive().count() == 0


def test_an_undo_a_defect_stopped_offers_no_undo_of_its_own(
    client_in, owned_library, game, monkeypatch, failing_batches
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

    client_in.post(undo_url(token), {})

    undoing = BulkBatch.objects.get(undoes=uuid.UUID(token))
    assert undoing.state == BulkBatch.State.FAILED
    assert "action" not in batch_toast(undoing)


def stop_url(token) -> str:
    return reverse("games:stop_bulk_batch", args=[token])


def test_stopping_ends_the_batch_between_chunks(
    client_in, owned_library, game, monkeypatch, held_batches
):
    monkeypatch.setattr("games.bulk_jobs.CHUNK_BUDGET", timedelta(0))
    sessions = [
        a_written_session(owned_library, game, day=A_DAY + timedelta(days=offset))
        for offset in range(3)
    ]
    confirmation = confirm(client_in, some(*sessions))
    token = posted(confirmation)[TOKEN_FIELD]
    act(client_in, confirmation)
    held_batches.run_one()

    stopped = client_in.post(stop_url(token))
    held_batches.run_all()

    assert stopped.status_code == 302
    assert HistoricalPlaytime.objects.count() == 1
    batch = batch_of(owned_library, token)
    assert batch.state == BulkBatch.State.STOPPED
    assert said_by(batch) == ["1 of 3 done, 2 not reached."]


def test_another_librarys_batch_cannot_be_stopped(
    client, owned_library, game, django_user_model
):
    batch = BulkBatch.objects.create(
        token=uuid.uuid7(),
        library=owned_library,
        action="session.reclassify",
        origin="/",
        rows=[],
    )
    stranger = django_user_model.objects.create_user("stranger", password="pw")
    client.force_login(stranger)

    assert client.post(stop_url(batch.token)).status_code == 404
    batch.refresh_from_db()
    assert batch.stop_requested_at is None


def test_stopping_names_the_rows_it_left(
    client_in,
    owned_library,
    game,
    monkeypatch,
    caplog,
    capture_games_logger,
    held_batches,
):
    """A Stop leaves rows behind, and the log is where they are named.

    The toast says how far the batch got; nothing else ever says which
    rows it did not reach, and a person who presses Stop by accident
    has only the log to read them back from.
    """
    monkeypatch.setattr("games.bulk_jobs.CHUNK_BUDGET", timedelta(0))
    sessions = [
        a_written_session(owned_library, game, day=A_DAY + timedelta(days=offset))
        for offset in range(3)
    ]
    confirmation = confirm(client_in, some(*sessions))
    token = posted(confirmation)[TOKEN_FIELD]
    act(client_in, confirmation)
    held_batches.run_one()
    client_in.post(stop_url(token))

    with capture_games_logger() as captured:
        captured.set_level(logging.INFO, logger="games")
        held_batches.run_all()

    said = " ".join(record.message for record in caplog.records)
    left = batch_of(owned_library, token).rows[1:]
    assert len(left) == 2
    for key in left:
        assert key in said
    assert STOPPED_BY_HAND in said
    assert token in said


def test_a_defect_names_the_rows_it_left(
    client_in,
    owned_library,
    game,
    monkeypatch,
    caplog,
    capture_games_logger,
    failing_batches,
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
        act(client_in, confirmation)

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


def undoing(token) -> BulkBatch:
    """The Undo batch of this one."""
    return BulkBatch.objects.get(undoes=uuid.UUID(token))


def action_of(batch: BulkBatch) -> str | None:
    action = batch_toast(batch).get("action")
    return action["url"] if action else None


def test_the_answer_of_a_batch_offers_the_batch_its_undo(
    client_in, owned_library, game
):
    session = a_written_session(owned_library, game)
    confirmation = confirm(client_in, some(session))
    token = posted(confirmation)[TOKEN_FIELD]

    act(client_in, confirmation)

    assert action_of(batch_of(owned_library, token)) == undo_url(token)


def test_a_batch_that_did_nothing_offers_no_undo(client_in, owned_library, game):
    """Nothing to take back, so no press that says there is."""
    in_the_bucket = a_bucket_session(a_bucket(owned_library, game))

    act(client_in, confirm(client_in, some(in_the_bucket)))

    assert action_of(newest_batch(owned_library)) is None


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

    client_in.post(undo_url(token), {})

    assert said_by(undoing(token)) == ["2 of 2 done."]
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
        replace(statement_from_session(sessions[0]), note="Counted again."),
        correlation_id=uuid.uuid7(),
    )

    undone = client_in.post(undo_url(token), {})

    assert undone.status_code == 302
    assert PlayerSession.objects.get(pk=sessions[0].pk).removed_at is not None
    assert PlayerSession.objects.get(pk=sessions[1].pk).removed_at is None
    #: One refused row of an Undo, counted and said in its own number.
    assert said_by(undoing(token))[0] == "1 of 2 done, 1 left as it is."


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
    monkeypatch.setattr("games.bulk_jobs.CHUNK_BUDGET", timedelta(0))

    response = client_in.post(undo_url(token), {})

    assert response.status_code == 302
    undo_token = undoing(token).token
    assert undo_token != uuid.UUID(token)
    assert undoing(token).chunk == 2
    assert PlayerSession.objects.alive().count() == 3
    restored = LibraryEvent.objects.filter(
        library=owned_library, event_type="library.playersession.restored"
    )
    assert {event.correlation_id for event in restored} == {undo_token}


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
    assert said_by(undoing(token)) == ["1 of 2 done, 1 already done."]
    assert PlayerSession.objects.alive().count() == 2


def test_an_undo_offers_no_further_undo(client_in, owned_library, game):
    session = a_written_session(owned_library, game)
    confirmation = confirm(client_in, some(session))
    token = posted(confirmation)[TOKEN_FIELD]
    landed(client_in, act(client_in, confirmation))

    client_in.post(undo_url(token), {})

    assert action_of(undoing(token)) is None


def test_an_undo_reads_its_rows_on_the_server(client_in, owned_library, game):
    """Posted keys reach no Undo."""
    session = a_written_session(owned_library, game)
    confirmation = confirm(client_in, some(session))
    token = posted(confirmation)[TOKEN_FIELD]
    act(client_in, confirmation)
    forged = str(uuid.uuid7())

    client_in.post(
        undo_url(token),
        {TOKEN_FIELD: forged, PROGRESS_FIELD: json.dumps({"rows": [forged]})},
    )

    assert undoing(token).rows == [str(session.pk)]
    assert PlayerSession.objects.get(pk=session.pk).removed_at is None


def test_an_undo_waits_for_its_batch_to_end(
    client_in, owned_library, game, held_batches
):
    session = a_written_session(owned_library, game)
    confirmation = confirm(client_in, some(session))
    token = posted(confirmation)[TOKEN_FIELD]
    act(client_in, confirmation)

    refused = client_in.post(undo_url(token), {})

    assert refused.status_code == 400
    assert not BulkBatch.objects.filter(undoes=uuid.UUID(token)).exists()


def test_an_undo_pressed_twice_while_it_runs_starts_once(
    client_in, owned_library, game, chunk_queue
):
    session = a_written_session(owned_library, game)
    confirmation = confirm(client_in, some(session))
    token = posted(confirmation)[TOKEN_FIELD]
    act(client_in, confirmation)
    chunk_queue.held = True

    client_in.post(undo_url(token), {})
    client_in.post(undo_url(token), {})

    assert BulkBatch.objects.filter(undoes=uuid.UUID(token)).count() == 1
    #: The press is the end's acknowledgement.
    assert batch_of(owned_library, token).announced_at is not None


def test_an_undo_with_nothing_left_starts_nothing(client_in, owned_library, game):
    in_the_bucket = a_bucket_session(a_bucket(owned_library, game))
    confirmation = confirm(client_in, some(in_the_bucket))
    token = posted(confirmation)[TOKEN_FIELD]
    act(client_in, confirmation)

    undone = client_in.post(undo_url(token), {})

    assert undone.status_code == 302
    assert NOTHING_TO_UNDO in said(undone)
    assert not BulkBatch.objects.filter(undoes=uuid.UUID(token)).exists()


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
    BulkBatch.objects.filter(token=uuid.UUID(token)).update(action="session.retired")

    response = client_in.post(undo_url(token), {})

    assert response.status_code == 400
    assert UNKNOWN_ACT.encode() in response.content
    assert PlayerSession.objects.get(pk=session.pk).removed_at is not None


def test_a_batch_without_a_row_reads_its_act_from_events(
    client_in, owned_library, game
):
    """Batches run before the batch rows."""
    session = a_written_session(owned_library, game)
    confirmation = confirm(client_in, some(session))
    token = posted(confirmation)[TOKEN_FIELD]
    act(client_in, confirmation)
    BulkBatch.objects.filter(token=uuid.UUID(token)).delete()
    LibraryEvent.objects.filter(correlation_id=uuid.UUID(token)).update(
        source_metadata={"bulk": {"action": "session.retired"}}
    )

    response = client_in.post(undo_url(token), {})

    assert response.status_code == 400
    assert UNKNOWN_ACT.encode() in response.content


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


# ── The choice a chunk carries ───────────────────────────────────────────────


class Asked(NamedTuple):
    """What the act was handed, settled, and will refuse.

    Appending to `refusing` makes the next offer turn the
    whole act down, which a frozen declaration cannot be
    patched into.
    """

    seen: list[str | None]
    settled: list[str]
    refusing: list[str]


PICKED = "picked"
PICK_ONE = "Pick a playthrough first."
NO_GAME = "Those sessions are at more than one game."


@pytest.fixture
def reclassify_declaration():
    return BULK_ACTIONS["session.reclassify"]


def _removed(actor, row, idempotency_key, correlation_id, name) -> RowOutcome:
    """A real append, so the batch its Undo reads exists."""
    return RowOutcome.of(
        remove_session(
            actor,
            row,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            source_metadata={"bulk": {"action": name}},
        )
    )


def _declare(name, reclassify_declaration, run, inverse, choice=None):
    return BulkAction(
        name=name,
        label=reclassify_declaration.label,
        title=reclassify_declaration.title,
        confirm_label=reclassify_declaration.confirm_label,
        subject=reclassify_declaration.subject,
        color=reclassify_declaration.color,
        undo_rows=reclassify_declaration.undo_rows,
        fallback=reclassify_declaration.fallback,
        scope=reclassify_declaration.scope,
        resolve=reclassify_declaration.resolve,
        run=run,
        inverse=inverse,
        preview=reclassify_declaration.preview,
        choice=choice,
    )


@pytest.fixture
def recorder(reclassify_declaration):
    """An act with no choice, whose run remembers what it was handed."""
    seen: list[str | None] = []

    def run(actor, row, *, choice, idempotency_key, correlation_id):
        seen.append(choice)
        return _removed(actor, row, idempotency_key, correlation_id, "session.recorder")

    def inverse(actor, row_id, *, undoes, idempotency_key, correlation_id):
        seen.append(str(undoes))
        return RowOutcome.MOVED

    _declare("session.recorder", reclassify_declaration, run, inverse)
    yield seen
    _TABLE.pop("session.recorder")


@pytest.fixture
def asker(request, reclassify_declaration):
    """An act that asks for a fact, and remembers what it settled."""
    seen: list[str | None] = []
    settled: list[str] = []
    refusing: list[str] = [NO_GAME] if getattr(request, "param", False) else []

    def offer(library, rows, field_name):
        if refusing:
            return RefusedAct(refusing[0])
        return Control(Input(type="hidden", name=field_name, value=PICKED))

    def settle(library, post):
        stated = post.get(CHOICE_FIELD, "")
        if stated != PICKED:
            raise CommandRejected(f"{stated!r} is no target", sentence=PICK_ONE)
        #: Recorded here, not in `run`: a runner that trusted the
        #: carried value would still hand `run` the right string.
        settled.append(stated)
        return stated

    def run(actor, row, *, choice, idempotency_key, correlation_id):
        seen.append(choice)
        return _removed(actor, row, idempotency_key, correlation_id, "session.asker")

    def inverse(actor, row_id, *, undoes, idempotency_key, correlation_id):
        seen.append(str(undoes))
        return RowOutcome.MOVED

    _declare(
        "session.asker",
        reclassify_declaration,
        run,
        inverse,
        choice=BulkChoice(offer=offer, settle=settle),
    )
    yield Asked(seen, settled, refusing)
    _TABLE.pop("session.asker")


ASK = reverse("games:run_bulk_action", args=["session.asker"])
RECORD = reverse("games:run_bulk_action", args=["session.recorder"])


def test_an_act_that_asks_nothing_is_handed_no_choice(
    client_in, owned_library, game, recorder
):
    session = a_written_session(owned_library, game)

    act(client_in, confirm(client_in, some(session), url=RECORD), url=RECORD)

    assert recorder == [None]


def test_the_confirmation_hosts_the_acts_own_control(
    client_in, owned_library, game, asker
):
    session = a_written_session(owned_library, game)

    body = confirm(client_in, some(session), url=ASK).content.decode()

    assert f'name="{CHOICE_FIELD}"' in body
    assert f'value="{PICKED}"' in body


@pytest.mark.parametrize("asker", [True], indirect=True)
def test_an_offer_that_refuses_the_act_writes_nothing(
    client_in, owned_library, game, asker
):
    session = a_written_session(owned_library, game)

    response = confirm(client_in, some(session), url=ASK)

    assert response.status_code == 400
    assert NO_GAME in response.content.decode()
    assert asker.seen == []


def test_a_chunk_that_carries_no_choice_is_refused_and_writes_nothing(
    client_in, owned_library, game, asker
):
    session = a_written_session(owned_library, game)
    confirmation = confirm(client_in, some(session), url=ASK)
    fields = posted(confirmation)
    fields.pop(CHOICE_FIELD)

    response = client_in.post(ASK, fields)

    assert response.status_code == 400
    assert PICK_ONE in response.content.decode()
    assert asker.seen == []


def test_a_refused_settle_keeps_the_token_and_the_rows(
    client_in, owned_library, game, asker
):
    """The person answers the same question about the same rows."""
    session = a_written_session(owned_library, game)
    confirmation = confirm(client_in, some(session), url=ASK)
    fields = posted(confirmation)

    response = client_in.post(ASK, {**fields, CHOICE_FIELD: "nonsense"})

    kept = posted(response)
    assert kept[TOKEN_FIELD] == fields[TOKEN_FIELD]
    assert json.loads(kept[PROGRESS_FIELD])["rows"] == [str(session.pk)]
    assert str(session.pk) in response.content.decode()


def test_the_choice_is_settled_once_and_stored(
    client_in, owned_library, game, asker, monkeypatch
):
    monkeypatch.setattr("games.bulk_jobs.CHUNK_BUDGET", timedelta(0))
    sessions = [
        a_written_session(owned_library, game, day=A_DAY + timedelta(days=offset))
        for offset in range(3)
    ]

    response = act(client_in, confirm(client_in, some(*sessions), url=ASK), url=ASK)

    assert response.status_code == 302
    assert newest_batch(owned_library).choice == PICKED
    assert asker.settled == [PICKED]
    assert asker.seen == [PICKED, PICKED, PICKED]


def test_an_undo_is_handed_the_batch_it_undoes(client_in, owned_library, game, asker):
    session = a_written_session(owned_library, game)
    confirmation = confirm(client_in, some(session), url=ASK)
    token = posted(confirmation)[TOKEN_FIELD]
    act(client_in, confirmation, url=ASK)
    asker.seen.clear()

    client_in.post(reverse("games:undo_bulk_action", args=[token]))

    assert asker.seen == [token]


# ── The press wears the act's colour ─────────────────────────────────────────


def _confirm_button(response, label: str) -> str:
    """The confirmation's submit, found by its words."""
    html = response.content.decode()
    end = html.index(f">{label}</button>")
    return html[html.rindex("<button", 0, end) : end]


@pytest.mark.parametrize(
    ("action_name", "label", "solid"),
    [
        ("session.reclassify", "Record as historical playtime", "solid-brand"),
        ("session.remove", "Remove", "solid-danger"),
    ],
)
def test_a_confirmations_press_wears_the_acts_colour(
    client_in, owned_library, game, action_name, label, solid
):
    """The press wears the colour the act declares."""
    session = a_written_session(owned_library, game)
    url = reverse("games:run_bulk_action", args=[action_name])

    response = confirm(client_in, some(session), url=url)

    assert solid in _confirm_button(response, label)


def test_an_undo_of_a_stopped_batch_takes_back_only_its_done_rows(
    client_in, owned_library, game, monkeypatch, held_batches
):
    monkeypatch.setattr("games.bulk_jobs.CHUNK_BUDGET", timedelta(0))
    sessions = [
        a_written_session(owned_library, game, day=A_DAY + timedelta(days=offset))
        for offset in range(3)
    ]
    confirmation = confirm(client_in, some(*sessions))
    token = posted(confirmation)[TOKEN_FIELD]
    act(client_in, confirmation)
    held_batches.run_one()
    client_in.post(stop_url(token))
    held_batches.run_all()

    client_in.post(undo_url(token), {})
    held_batches.run_all()

    assert said_by(undoing(token)) == ["1 of 1 done."]
    assert PlayerSession.objects.alive().count() == 3
    assert HistoricalPlaytime.objects.alive().count() == 0


def test_an_undo_pressed_after_an_undo_ended_finds_everything_back(
    client_in, owned_library, game
):
    """A new Undo; each row already so."""
    session = a_written_session(owned_library, game)
    confirmation = confirm(client_in, some(session))
    token = posted(confirmation)[TOKEN_FIELD]
    act(client_in, confirmation)
    client_in.post(undo_url(token), {})

    client_in.post(undo_url(token), {})

    undos = BulkBatch.objects.filter(undoes=uuid.UUID(token)).order_by("created_at")
    assert said_by(undos.last()) == ["0 of 1 done, 1 already done."]
    assert PlayerSession.objects.get(pk=session.pk).removed_at is None


def test_an_undo_of_an_undo_says_so(client_in, owned_library, game):
    session = a_written_session(owned_library, game)
    confirmation = confirm(client_in, some(session))
    token = posted(confirmation)[TOKEN_FIELD]
    act(client_in, confirmation)
    client_in.post(undo_url(token), {})

    response = client_in.post(undo_url(str(undoing(token).token)), {})

    assert response.status_code == 400
    assert html_module.escape(UNDO_OF_AN_UNDO) in response.content.decode()


def test_an_undo_ends_a_batch_no_worker_owns(
    client_in, owned_library, game, chunk_queue
):
    """Stale, so Undo stops it first."""
    from games.bulk_jobs import STALE_AFTER

    session = a_written_session(owned_library, game)
    confirmation = confirm(client_in, some(session))
    token = posted(confirmation)[TOKEN_FIELD]
    chunk_queue.held = True
    act(client_in, confirmation)
    #: One row done, then the worker vanished.
    chunk_queue.run_one()
    BulkBatch.objects.filter(token=uuid.UUID(token)).update(
        state=BulkBatch.State.RUNNING,
        ended_at=None,
        updated_at=timezone.now() - STALE_AFTER - timedelta(minutes=1),
    )
    chunk_queue.held = False

    client_in.post(undo_url(token), {})

    assert batch_of(owned_library, token).state == BulkBatch.State.STOPPED
    assert PlayerSession.objects.get(pk=session.pk).removed_at is None
