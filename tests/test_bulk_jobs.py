"""The background runner: chunks, guards, toasts, reads."""

import html
import json
import uuid
from datetime import date, timedelta

import pytest
from bulk_posts import newest_batch, posted, selection
from django.urls import reverse
from django.utils import timezone
from django_q.exceptions import TimeoutException
from session_rows import duration_only_row, tracked_run

from games import bulk_jobs, bulk_reclassification
from games.bulk_jobs import (
    ANNOUNCE_WINDOW,
    STARTS_ALLOWED,
    Tally,
    batch_toast,
    run_chunk,
    start_batch,
    visible_batches,
)
from games.bulk_reclassification import REVIEW_THRESHOLD_HOURS
from games.models import BulkBatch, Game, HistoricalPlaytime, UserLibrary
from games.views.bulk import STATEMENT_FIELD

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
def other_library(django_user_model):
    return django_user_model.objects.create_user(username="other", password="p").library


@pytest.fixture
def game(owned_library):
    return Game.objects.create(library=owned_library, name="Outer Wilds")


@pytest.fixture
def one_row_chunks(monkeypatch):
    monkeypatch.setattr(bulk_jobs, "CHUNK_BUDGET", timedelta(0))


def sessions_in(library, game, count):
    run = tracked_run(library, game)
    return [
        duration_only_row(run, A_DAY + timedelta(days=offset), LONG_ENOUGH)
        for offset in range(count)
    ]


def pressed(client, *rows) -> BulkBatch:
    confirmation = client.post(RECLASSIFY, {STATEMENT_FIELD: selection(*rows)})
    client.post(RECLASSIFY, posted(confirmation))
    batch = newest_batch(rows[0].library)
    assert batch is not None
    return batch


def a_batch(library: UserLibrary, **columns) -> BulkBatch:
    stated = {
        "token": uuid.uuid7(),
        "library": library,
        "action": "session.reclassify",
        "origin": "/tracker/session/list",
        "rows": [],
        **columns,
    }
    return BulkBatch.objects.create(**stated)


# ── Starting ─────────────────────────────────────────────────────────────────


def test_a_press_stores_the_batch_and_queues_its_first_chunk(
    client_in, owned_library, game, held_batches
):
    sessions = sessions_in(owned_library, game, 2)

    batch = pressed(client_in, *sessions)

    assert batch.state == BulkBatch.State.QUEUED
    assert sorted(batch.rows) == sorted(str(row.pk) for row in sessions)
    assert batch.origin == "/tracker/session/list"
    assert held_batches.queued == [(batch.pk, 0)]


def test_a_token_pressed_twice_stores_one_batch(
    client_in, owned_library, game, held_batches
):
    session = sessions_in(owned_library, game, 1)[0]
    confirmation = client_in.post(RECLASSIFY, {STATEMENT_FIELD: selection(session)})

    first = client_in.post(RECLASSIFY, posted(confirmation))
    second = client_in.post(RECLASSIFY, posted(confirmation))

    assert first.status_code == second.status_code == 302
    assert BulkBatch.objects.count() == 1
    assert len(held_batches.queued) == 1


def test_a_token_that_is_no_uuidv7_is_refused(client_in, owned_library, game):
    session = sessions_in(owned_library, game, 1)[0]
    confirmation = client_in.post(RECLASSIFY, {STATEMENT_FIELD: selection(session)})

    response = client_in.post(
        RECLASSIFY, {**posted(confirmation), "submission": "not a token"}
    )

    assert response.status_code == 400
    assert not BulkBatch.objects.exists()


def test_one_token_in_two_libraries_is_two_batches(owned_library, other_library):
    token = uuid.uuid7()
    for library in (owned_library, other_library):
        start_batch(
            library,
            "session.reclassify",
            token=token,
            keys=[],
            tally=Tally(),
            choice=None,
            origin="/",
        )

    assert BulkBatch.objects.filter(token=token).count() == 2


# ── Running ──────────────────────────────────────────────────────────────────


def test_every_chunk_runs_until_the_rows_end(
    client_in, owned_library, game, one_row_chunks
):
    batch = pressed(client_in, *sessions_in(owned_library, game, 3))

    batch.refresh_from_db()
    assert batch.state == BulkBatch.State.FINISHED
    assert (batch.done, batch.position, batch.chunk) == (3, 3, 2)
    assert batch.ended_at is not None
    assert HistoricalPlaytime.objects.count() == 3


def test_a_stale_chunk_number_does_nothing(
    client_in, owned_library, game, held_batches
):
    batch = pressed(client_in, *sessions_in(owned_library, game, 1))

    run_chunk(batch.pk, 1)

    batch.refresh_from_db()
    assert (batch.state, batch.attempts) == (BulkBatch.State.QUEUED, 0)


def test_a_terminal_batch_does_nothing(client_in, owned_library, game, held_batches):
    batch = pressed(client_in, *sessions_in(owned_library, game, 1))
    BulkBatch.objects.filter(pk=batch.pk).update(state=BulkBatch.State.STOPPED)

    run_chunk(batch.pk, 0)

    assert HistoricalPlaytime.objects.count() == 0


def test_a_redelivered_chunk_resumes_at_its_position(
    client_in, owned_library, game, held_batches
):
    """A crash leaves the tally written per row."""
    sessions = sessions_in(owned_library, game, 3)
    batch = pressed(client_in, *sessions)
    real = bulk_reclassification.reclassify_session
    calls = {"n": 0}

    def crashes_on_the_second(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise SystemExit("the worker died")
        return real(*args, **kwargs)

    bulk_reclassification.reclassify_session = crashes_on_the_second
    try:
        with pytest.raises(SystemExit):
            run_chunk(batch.pk, 0)
    finally:
        bulk_reclassification.reclassify_session = real
    #: A crash writes no failure mark.
    BulkBatch.objects.filter(pk=batch.pk).update(state=BulkBatch.State.RUNNING)

    run_chunk(batch.pk, 0)

    batch.refresh_from_db()
    assert batch.state == BulkBatch.State.FINISHED
    assert (batch.done, batch.unchanged, batch.lost) == (3, 0, 0)
    assert HistoricalPlaytime.objects.count() == 3


def test_a_chunk_that_starts_a_third_time_fails(
    client_in, owned_library, game, held_batches
):
    batch = pressed(client_in, *sessions_in(owned_library, game, 1))
    BulkBatch.objects.filter(pk=batch.pk).update(
        attempts=STARTS_ALLOWED, state=BulkBatch.State.RUNNING
    )

    run_chunk(batch.pk, 0)

    batch.refresh_from_db()
    assert batch.state == BulkBatch.State.FAILED
    assert HistoricalPlaytime.objects.count() == 0


def test_an_overtaken_run_stops_after_its_row(
    client_in, owned_library, game, held_batches, monkeypatch
):
    """Another delivery claimed the chunk."""
    batch = pressed(client_in, *sessions_in(owned_library, game, 3))
    real = bulk_reclassification.reclassify_session

    def overtaken(*args, **kwargs):
        outcome = real(*args, **kwargs)
        BulkBatch.objects.filter(pk=batch.pk).update(attempts=5)
        return outcome

    monkeypatch.setattr(bulk_reclassification, "reclassify_session", overtaken)

    run_chunk(batch.pk, 0)

    batch.refresh_from_db()
    assert batch.position == 0
    assert batch.state == BulkBatch.State.RUNNING
    assert HistoricalPlaytime.objects.count() == 1


def test_a_timeout_stores_failed_and_leaves(
    client_in, owned_library, game, held_batches, monkeypatch
):
    """The cluster's timeout is no `Exception`."""
    batch = pressed(client_in, *sessions_in(owned_library, game, 2))

    def times_out(*args, **kwargs):
        raise TimeoutException("Task exceeded maximum timeout value (60 seconds)")

    monkeypatch.setattr(bulk_reclassification, "reclassify_session", times_out)

    with pytest.raises(TimeoutException):
        run_chunk(batch.pk, 0)

    batch.refresh_from_db()
    assert batch.state == BulkBatch.State.FAILED
    assert batch.ended_at is not None


# ── Following ────────────────────────────────────────────────────────────────


def test_a_queued_batch_says_it_waits_and_offers_stop(owned_library):
    batch = a_batch(owned_library, total=40)

    toast = batch_toast(batch)

    assert toast["message"].endswith(": waiting to start. 0 of 40 done, 40 left.")
    assert toast["action"]["label"] == "Stop"
    assert toast["sticky"]
    assert toast["id"] == f"bulk-batch:{batch.token}"


def test_a_running_batch_counts_what_is_left(owned_library):
    batch = a_batch(
        owned_library, total=40, done=3, position=3, state=BulkBatch.State.RUNNING
    )

    assert batch_toast(batch)["message"].endswith(": 3 of 40 done, 37 left.")


def test_a_stopping_batch_offers_no_second_stop(owned_library):
    batch = a_batch(
        owned_library,
        total=2,
        state=BulkBatch.State.RUNNING,
        stop_requested_at=timezone.now(),
    )

    toast = batch_toast(batch)

    assert ": stopping. " in toast["message"]
    assert "action" not in toast


def test_a_failed_batch_names_its_error(owned_library):
    batch = a_batch(owned_library, total=2, done=1, state=BulkBatch.State.FAILED)

    toast = batch_toast(batch)

    assert toast["type"] == "error"
    assert f"(error {str(batch.token)[-12:]})" in toast["message"]
    assert toast["action"]["label"] == "Undo"


def test_an_end_states_its_reasons_in_one_toast(owned_library):
    batch = a_batch(
        owned_library,
        total=2,
        done=1,
        position=2,
        refused=1,
        reasons=["That one is in the bucket."],
        state=BulkBatch.State.FINISHED,
    )

    message = batch_toast(batch)["message"]

    assert message.endswith(
        ": 1 of 2 done, 1 left as it is. That one is in the bucket."
    )


def test_an_end_that_moved_nothing_keeps_its_timer(owned_library):
    batch = a_batch(owned_library, total=1, refused=1, state=BulkBatch.State.FINISHED)

    toast = batch_toast(batch)

    assert (toast["type"], toast["sticky"]) == ("info", False)
    assert "action" not in toast


def test_an_undo_is_titled_as_one_and_offers_none(owned_library):
    batch = a_batch(
        owned_library,
        total=1,
        done=1,
        undoes=uuid.uuid7(),
        state=BulkBatch.State.FINISHED,
    )

    toast = batch_toast(batch)

    assert toast["message"].startswith("Undo: ")
    assert "action" not in toast


def test_an_act_the_table_lost_offers_no_undo(owned_library):
    batch = a_batch(
        owned_library,
        action="session.retired",
        total=1,
        done=1,
        state=BulkBatch.State.FINISHED,
    )

    assert "action" not in batch_toast(batch)


def test_the_page_reads_running_and_unseen_ends(owned_library):
    now = timezone.now()
    running = a_batch(owned_library, state=BulkBatch.State.RUNNING)
    unseen = a_batch(owned_library, state=BulkBatch.State.FINISHED, ended_at=now)
    a_batch(
        owned_library,
        state=BulkBatch.State.FINISHED,
        ended_at=now,
        announced_at=now,
    )
    a_batch(
        owned_library,
        state=BulkBatch.State.FINISHED,
        ended_at=now - ANNOUNCE_WINDOW - timedelta(minutes=1),
    )

    assert visible_batches(owned_library) == [running, unseen]


def test_another_librarys_batch_is_absent(owned_library, other_library):
    a_batch(other_library, state=BulkBatch.State.RUNNING)

    assert visible_batches(owned_library) == []


def test_a_page_carries_the_librarys_batches(client_in, owned_library):
    batch = a_batch(owned_library, state=BulkBatch.State.RUNNING, total=1)

    page = client_in.get(reverse("games:list_sessions")).content.decode()

    marker = 'data-bulk-batches="'
    start = page.index(marker) + len(marker)
    carried = json.loads(html.unescape(page[start : page.index('"', start)]))
    assert [one["token"] for one in carried] == [str(batch.token)]
    assert 'data-bulk-batches-url="/api/bulk/batches"' in page


def test_the_api_answers_the_asked_batches_of_this_library(
    client_in, owned_library, other_library
):
    ours = a_batch(owned_library, state=BulkBatch.State.RUNNING)
    theirs = a_batch(other_library, state=BulkBatch.State.RUNNING)

    response = client_in.get(
        "/api/bulk/batches", {"tokens": f"{ours.token},{theirs.token},junk"}
    )

    assert response.status_code == 200
    assert [one["token"] for one in response.json()] == [str(ours.token)]
    assert response.json()[0]["toast"] == batch_toast(ours)


def test_a_dismissed_end_is_announced(client_in, owned_library, other_library):
    ours = a_batch(owned_library, state=BulkBatch.State.FINISHED)
    theirs = a_batch(other_library, state=BulkBatch.State.FINISHED)

    answered = client_in.post(f"/api/bulk/batches/{ours.token}/announced")
    refused = client_in.post(f"/api/bulk/batches/{theirs.token}/announced")

    assert (answered.status_code, refused.status_code) == (204, 404)
    ours.refresh_from_db()
    theirs.refresh_from_db()
    assert ours.announced_at is not None
    assert theirs.announced_at is None
