"""The background runner: chunks, guards, toasts, reads."""

import html
import json
import logging
import uuid
from datetime import date, timedelta

import pytest
from bulk_batches import REAL_ENQUEUE
from bulk_posts import newest_batch, posted, selection
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django_q.exceptions import TimeoutException
from django_q.models import OrmQ
from session_rows import duration_only_row, tracked_run

from games import bulk_jobs, bulk_reclassification, tasks
from games.bulk_jobs import (
    ANNOUNCE_WINDOW,
    ENDED_BY_A_DEFECT,
    MET_THE_DEFECT,
    NO_WORKER,
    STALE_AFTER,
    STARTS_ALLOWED,
    Tally,
    batch_toast,
    end_stale,
    request_stop,
    run_chunk,
    start_batch,
    visible_batches,
)
from games.bulk_reclassification import REVIEW_THRESHOLD_HOURS
from games.models import (
    BulkBatch,
    Game,
    HistoricalPlaytime,
    LibraryEvent,
    PlayerSession,
    UserLibrary,
)
from games.views.bulk import PROGRESS_FIELD, STATEMENT_FIELD, UNREADABLE_STATEMENT

pytestmark = [pytest.mark.untracked_games, pytest.mark.django_db(transaction=True)]

A_DAY = date(2026, 3, 5)
LONG_ENOUGH = timedelta(hours=REVIEW_THRESHOLD_HOURS + 1)
RECLASSIFY = reverse("games:run_bulk_action", args=["session.reclassify"])
RECLASSIFIED = "library.playersession.reclassified"


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
    if stated.get("state") in BulkBatch.TERMINAL:
        stated.setdefault("ended_at", timezone.now())
    return BulkBatch.objects.create(**stated)


def gone_quiet(batch: BulkBatch) -> BulkBatch:
    """As if no worker wrote for a while."""
    BulkBatch.objects.filter(pk=batch.pk).update(
        updated_at=timezone.now() - STALE_AFTER - timedelta(minutes=1)
    )
    batch.refresh_from_db()
    return batch


def logged(caplog) -> str:
    return " ".join(record.message for record in caplog.records)


# ── Starting ─────────────────────────────────────────────────────────────────


def test_a_press_stores_the_batch_and_queues_its_first_chunk(
    client_in, owned_library, game, held_batches
):
    sessions = sessions_in(owned_library, game, 2)

    batch = pressed(client_in, *sessions)

    assert batch.state == BulkBatch.State.QUEUED
    assert sorted(batch.keys) == sorted(str(row.pk) for row in sessions)
    assert batch.origin == "/tracker/session/list"
    assert list(held_batches.queued) == [(batch.pk, 0)]


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


@pytest.mark.parametrize(
    "forged",
    [{"refused": -1}, {"lost": "3"}, {"lost": True}, {"reasons": ["a", "a"]}],
)
def test_a_forged_tally_is_refused_as_unreadable(
    client_in, owned_library, game, forged
):
    session = sessions_in(owned_library, game, 1)[0]
    confirmation = client_in.post(RECLASSIFY, {STATEMENT_FIELD: selection(session)})
    fields = posted(confirmation)
    fields[PROGRESS_FIELD] = json.dumps({"rows": [str(session.pk)], **forged})

    response = client_in.post(RECLASSIFY, fields)

    assert response.status_code == 400
    assert html.escape(UNREADABLE_STATEMENT) in response.content.decode()
    assert not BulkBatch.objects.exists()


def test_a_forged_key_of_another_library_comes_out_lost(
    client_in, owned_library, other_library, game
):
    """The press stores the posted keys; the run resolves them."""
    ours = sessions_in(owned_library, game, 1)[0]
    theirs = sessions_in(
        other_library, Game.objects.create(library=other_library, name="Other"), 1
    )[0]
    confirmation = client_in.post(RECLASSIFY, {STATEMENT_FIELD: selection(ours)})
    fields = posted(confirmation)
    fields[PROGRESS_FIELD] = json.dumps({"rows": [str(ours.pk), str(theirs.pk)]})

    client_in.post(RECLASSIFY, fields)

    batch = newest_batch(owned_library)
    assert (batch.done, batch.lost) == (1, 1)
    assert PlayerSession.objects.get(pk=theirs.pk).removed_at is None


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


def test_one_batch_has_one_live_undo(owned_library, held_batches):
    undone = uuid.uuid7()

    def an_undo():
        return start_batch(
            owned_library,
            "session.reclassify",
            token=uuid.uuid7(),
            keys=[uuid.uuid7()],
            tally=Tally(total=1, left=1),
            choice=None,
            origin="/",
            undoes=undone,
        )

    first = an_undo()
    second = an_undo()

    assert second == first
    assert BulkBatch.objects.filter(undoes=undone).count() == 1


def test_the_cluster_queue_commits_with_the_batch(monkeypatch, owned_library):
    monkeypatch.setattr(bulk_jobs, "enqueue", REAL_ENQUEUE)

    batch = start_batch(
        owned_library,
        "session.reclassify",
        token=uuid.uuid7(),
        keys=[],
        tally=Tally(),
        choice=None,
        origin="/",
    )

    queued = OrmQ.objects.get()
    assert queued.func() == "games.tasks.run_bulk_batch"
    assert queued.args() == (str(batch.pk), 0)
    tasks.run_bulk_batch(str(batch.pk), 0)
    batch.refresh_from_db()
    assert batch.state == BulkBatch.State.FINISHED


def test_a_batch_rolled_back_queues_nothing(monkeypatch, owned_library):
    monkeypatch.setattr(bulk_jobs, "enqueue", REAL_ENQUEUE)

    with pytest.raises(RuntimeError), transaction.atomic():
        start_batch(
            owned_library,
            "session.reclassify",
            token=uuid.uuid7(),
            keys=[],
            tally=Tally(),
            choice=None,
            origin="/",
        )
        raise RuntimeError("the press failed after")

    assert not OrmQ.objects.exists()
    assert not BulkBatch.objects.exists()


def test_a_task_naming_no_batch_is_logged_and_dropped(caplog, capture_games_logger):
    with capture_games_logger():
        tasks.run_bulk_batch("not a key", 0)

    assert "names no batch" in logged(caplog)


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
    BulkBatch.objects.filter(pk=batch.pk).update(
        state=BulkBatch.State.STOPPED, ended_at=timezone.now()
    )

    run_chunk(batch.pk, 0)

    assert HistoricalPlaytime.objects.count() == 0


def test_a_redelivery_counts_the_row_in_flight_once(
    client_in, owned_library, game, held_batches
):
    """The crash fell between its dispatch and the tally."""
    sessions = sessions_in(owned_library, game, 3)
    batch = pressed(client_in, *sessions)
    run_chunk(batch.pk, 0)
    #: The last row committed; its tally write never did.
    BulkBatch.objects.filter(pk=batch.pk).update(
        position=2,
        done=2,
        attempts=1,
        state=BulkBatch.State.RUNNING,
        ended_at=None,
    )

    run_chunk(batch.pk, 0)

    batch.refresh_from_db()
    assert batch.state == BulkBatch.State.FINISHED
    assert batch.done + batch.unchanged + batch.refused + batch.lost == 3
    for session in sessions:
        events = LibraryEvent.objects.filter(
            aggregate_id=session.pk, event_type=RECLASSIFIED
        )
        assert events.count() == 1


def test_a_chunk_that_starts_a_third_time_fails(
    client_in, owned_library, game, held_batches, caplog, capture_games_logger
):
    batch = pressed(client_in, *sessions_in(owned_library, game, 2))
    BulkBatch.objects.filter(pk=batch.pk).update(
        attempts=STARTS_ALLOWED, state=BulkBatch.State.RUNNING
    )

    with capture_games_logger() as captured:
        captured.set_level(logging.INFO, logger="games")
        run_chunk(batch.pk, 0)

    batch.refresh_from_db()
    assert batch.state == BulkBatch.State.FAILED
    assert batch.ended_at is not None
    assert HistoricalPlaytime.objects.count() == 0
    said = logged(caplog)
    assert f"started {STARTS_ALLOWED} times" in said
    for key in batch.keys:
        assert key in said


def test_an_act_gone_while_queued_fails_without_blaming_a_row(
    client_in, owned_library, game, held_batches, caplog, capture_games_logger
):
    batch = pressed(client_in, *sessions_in(owned_library, game, 2))
    BulkBatch.objects.filter(pk=batch.pk).update(action="session.retired")

    with capture_games_logger() as captured:
        captured.set_level(logging.INFO, logger="games")
        run_chunk(batch.pk, 0)

    batch.refresh_from_db()
    assert batch.state == BulkBatch.State.FAILED
    said = logged(caplog)
    assert MET_THE_DEFECT not in said
    assert said.count(ENDED_BY_A_DEFECT) == 2


def test_an_overtaken_run_stops_after_its_row(
    client_in, owned_library, game, held_batches, monkeypatch
):
    """Another delivery claimed the chunk."""
    batch = pressed(client_in, *sessions_in(owned_library, game, 3))
    held_batches.queued.clear()
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
    assert not held_batches.queued


def test_a_stop_fences_out_a_run_in_flight(
    client_in, owned_library, game, held_batches, monkeypatch
):
    """A second delivery stops it mid-row."""
    batch = pressed(client_in, *sessions_in(owned_library, game, 3))
    real = bulk_reclassification.reclassify_session

    def stopped_meanwhile(*args, **kwargs):
        outcome = real(*args, **kwargs)
        if HistoricalPlaytime.objects.count() == 1:
            request_stop(owned_library, batch.token)
            run_chunk(batch.pk, 0)
        return outcome

    monkeypatch.setattr(bulk_reclassification, "reclassify_session", stopped_meanwhile)

    run_chunk(batch.pk, 0)

    batch.refresh_from_db()
    assert batch.state == BulkBatch.State.STOPPED
    assert HistoricalPlaytime.objects.count() == 1


def test_a_timeout_stores_failed_and_keeps_the_rows_done(
    client_in,
    owned_library,
    game,
    held_batches,
    monkeypatch,
    caplog,
    capture_games_logger,
):
    """The cluster's timeout is no `Exception`."""
    batch = pressed(client_in, *sessions_in(owned_library, game, 3))
    real = bulk_reclassification.reclassify_session

    def times_out_second(*args, **kwargs):
        if HistoricalPlaytime.objects.count() == 1:
            raise TimeoutException("Task exceeded maximum timeout value (60 seconds)")
        return real(*args, **kwargs)

    monkeypatch.setattr(bulk_reclassification, "reclassify_session", times_out_second)

    with capture_games_logger() as captured, pytest.raises(TimeoutException):
        captured.set_level(logging.INFO, logger="games")
        run_chunk(batch.pk, 0)

    batch.refresh_from_db()
    assert batch.state == BulkBatch.State.FAILED
    assert (batch.done, batch.position) == (1, 1)
    assert HistoricalPlaytime.objects.count() == 1
    said = logged(caplog)
    assert MET_THE_DEFECT in said
    assert ENDED_BY_A_DEFECT in said
    assert batch.keys[1] in said
    assert batch.keys[2] in said


# ── A batch no worker owns ───────────────────────────────────────────────────


def test_a_quiet_live_batch_says_the_worker_may_be_down(owned_library):
    batch = gone_quiet(a_batch(owned_library, total=2))

    toast = batch_toast(batch)

    assert toast["type"] == "warning"
    assert "the background worker may be down" in toast["message"]
    assert toast["action"]["label"] == "Stop"


def test_stop_ends_a_quiet_batch_at_once(owned_library, caplog, capture_games_logger):
    keys = [str(uuid.uuid7()), str(uuid.uuid7())]
    batch = gone_quiet(a_batch(owned_library, rows=keys, total=2))

    with capture_games_logger() as captured:
        captured.set_level(logging.INFO, logger="games")
        assert request_stop(owned_library, batch.token)

    batch.refresh_from_db()
    assert batch.state == BulkBatch.State.STOPPED
    assert NO_WORKER in logged(caplog)


def test_a_busy_batch_is_not_ended_as_quiet(owned_library):
    batch = a_batch(owned_library, total=2)

    assert not end_stale(batch)
    batch.refresh_from_db()
    assert batch.state == BulkBatch.State.QUEUED


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
    assert carried[0]["terminal"] is False
    assert 'data-bulk-batches-url="/api/bulk/batches"' in page


def test_the_api_answers_the_asked_batches_of_this_library(
    client_in, owned_library, other_library
):
    ours = a_batch(owned_library, state=BulkBatch.State.RUNNING)
    theirs = a_batch(other_library, state=BulkBatch.State.RUNNING)

    response = client_in.get(
        "/api/bulk/batches", {"tokens": f"{ours.token},{theirs.token}"}
    )

    assert response.status_code == 200
    assert [one["token"] for one in response.json()] == [str(ours.token)]
    assert response.json()[0]["toast"] == batch_toast(ours)


def test_the_api_refuses_a_token_it_cannot_read(client_in, owned_library):
    response = client_in.get("/api/bulk/batches", {"tokens": "junk"})

    assert response.status_code == 422


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


def test_stop_on_an_ended_batch_changes_nothing(client_in, owned_library):
    batch = a_batch(owned_library, state=BulkBatch.State.FINISHED)

    response = client_in.post(reverse("games:stop_bulk_batch", args=[batch.token]))

    assert response.status_code == 302
    batch.refresh_from_db()
    assert batch.stop_requested_at is None
