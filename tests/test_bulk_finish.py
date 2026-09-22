"""Finishing many sessions at one instant."""

import html as html_module
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from django.contrib.messages import get_messages
from django.http import QueryDict
from django.urls import reverse
from session_rows import timed_row, tracked_run

from games.bulk_actions import BULK_ACTIONS
from games.bulk_finish import (
    FINISH_SESSION,
    INSTANT_UNREADABLE,
    FinishStatement,
    settle_finish,
)
from games.events.dispatch import CommandRejected
from games.models import Game, LibraryEvent
from games.views.bulk import (
    CHOICE_FIELD,
    PROGRESS_FIELD,
    STATEMENT_FIELD,
    TOKEN_FIELD,
)

pytestmark = [pytest.mark.untracked_games, pytest.mark.django_db(transaction=True)]

STARTED_AT = datetime(2026, 3, 5, 12, tzinfo=UTC)
FINISH_URL = reverse("games:run_bulk_action", args=["session.finish"])


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


def a_running_session(library, game, offset=0):
    return timed_row(
        tracked_run(library, game),
        started_at=STARTED_AT + timedelta(hours=offset),
        ended_at=None,
    )


def some(*sessions) -> str:
    return json.dumps(
        {"mode": "some", "keys": sorted(str(session.pk) for session in sessions)}
    )


def posted(response) -> dict[str, str]:
    """The hidden fields the confirmation would submit."""
    markup = response.content.decode()
    fields: dict[str, str] = {}
    for name in (TOKEN_FIELD, PROGRESS_FIELD, CHOICE_FIELD):
        marker = f'name="{name}" value="'
        if marker in markup:
            start = markup.index(marker) + len(marker)
            fields[name] = html_module.unescape(
                markup[start : markup.index('"', start)]
            )
    return fields


def _post(**fields: str) -> QueryDict:
    """A POST body, encoded. Never a hand-written query string: an ISO
    instant's `+00:00` decodes as a space, and the test then measures its own
    encoding rather than the act's."""
    post = QueryDict(mutable=True)
    post.update(fields)
    return post


# ── The statement the batch carries ──────────────────────────────────────────


def test_a_statement_survives_its_own_encoding():
    stated = FinishStatement(STARTED_AT, "Asia/Tokyo")

    assert FinishStatement.decode(stated.encode()) == stated


def test_a_statement_with_no_zone_survives_too():
    stated = FinishStatement(STARTED_AT, None)

    assert FinishStatement.decode(stated.encode()) == stated


def test_settling_is_idempotent(owned_library):
    """Chunk two holds no `<browser-time-zone>` and no zone field.

    The waypoint renders hidden pairs alone, so every chunk after the first
    settles the answer the chunk before it gave.
    """
    first = settle_finish(
        owned_library,
        _post(
            **{CHOICE_FIELD: FinishStatement(STARTED_AT, None).encode()},
            browser_time_zone="Asia/Tokyo",
        ),
    )

    again = settle_finish(owned_library, _post(**{CHOICE_FIELD: first}))

    assert FinishStatement.decode(first).ended_at_zone == "Asia/Tokyo"
    assert again == first


def test_an_unreadable_instant_is_refused_with_a_sentence(owned_library):
    with pytest.raises(CommandRejected) as refusal:
        settle_finish(owned_library, _post(**{CHOICE_FIELD: "not-an-instant|UTC"}))

    assert refusal.value.sentence == INSTANT_UNREADABLE


def test_an_unusable_zone_settles_to_no_zone(owned_library):
    settled = settle_finish(
        owned_library,
        _post(
            **{CHOICE_FIELD: FinishStatement(STARTED_AT, None).encode()},
            browser_time_zone="Mars/Olympus",
        ),
    )

    assert FinishStatement.decode(settled).ended_at_zone is None


# ── The act, through the runner ──────────────────────────────────────────────


def _run(client, *sessions):
    """Confirm, then post the confirmation through to the end."""
    confirmation = client.post(FINISH_URL, {STATEMENT_FIELD: some(*sessions)})
    fields = posted(confirmation)
    return confirmation, client.post(FINISH_URL, fields)


def test_a_running_row_is_ended_at_the_stamped_instant(client_in, owned_library, game):
    session = a_running_session(owned_library, game)

    _run(client_in, session)

    session.refresh_from_db()
    assert session.ended_at is not None
    assert session.ended_at_zone is None


def test_a_row_that_is_not_running_is_refused_and_named(client_in, owned_library, game):
    finished = timed_row(
        tracked_run(owned_library, game),
        started_at=STARTED_AT,
        ended_at=STARTED_AT + timedelta(hours=1),
    )

    _, answer = _run(client_in, finished)

    finished.refresh_from_db()
    #: `EndSession` refuses a row that states an end, so the row is untouched
    #: and the batch names it in the toast rather than stopping.
    assert finished.ended_at == STARTED_AT + timedelta(hours=1)
    assert not LibraryEvent.objects.filter(
        aggregate_id=finished.pk, event_type="library.playersession.ended"
    ).exists()
    said = [str(message) for message in get_messages(answer.wsgi_request)]
    assert any("1 left as it is" in sentence for sentence in said), said


def test_the_confirmation_posted_twice_ends_every_row_once(
    client_in, owned_library, game
):
    """The regression test for the fingerprint.

    `ConfirmPage` has no submit-once guard, so the same form can arrive twice
    — a double submit, or Back onto a bfcached page. Both posts carry one
    token and one tally, so every row the first ended is dispatched again
    under the same key. With the instant stamped into the form the payload is
    identical and those rows replay; minted per POST, every one would raise
    `IdempotencyKeyMismatch` and be reported refused.
    """
    sessions = [a_running_session(owned_library, game, offset) for offset in range(3)]
    confirmation = client_in.post(FINISH_URL, {STATEMENT_FIELD: some(*sessions)})
    fields = posted(confirmation)

    client_in.post(FINISH_URL, fields)
    client_in.post(FINISH_URL, fields)

    ends = LibraryEvent.objects.filter(event_type="library.playersession.ended")
    assert ends.count() == len(sessions)
    for session in sessions:
        session.refresh_from_db()
        assert session.ended_at is not None
    #: One instant across the batch, and the repeat did not mint another.
    assert len({session.ended_at for session in sessions}) == 1


def test_a_batch_spanning_two_chunks_ends_every_row_at_one_instant(
    client_in, owned_library, game, monkeypatch
):
    monkeypatch.setattr("games.views.bulk.CHUNK_BUDGET", timedelta(0))
    sessions = [a_running_session(owned_library, game, offset) for offset in range(3)]

    confirmation = client_in.post(FINISH_URL, {STATEMENT_FIELD: some(*sessions)})
    answer = client_in.post(FINISH_URL, posted(confirmation))
    while posted(answer).get(TOKEN_FIELD):
        fields = posted(answer)
        if not json.loads(fields[PROGRESS_FIELD])["rows"]:
            break
        answer = client_in.post(FINISH_URL, fields)

    instants = set()
    for session in sessions:
        session.refresh_from_db()
        assert session.ended_at is not None
        instants.add(session.ended_at)
    assert len(instants) == 1


def test_the_batch_names_itself_so_the_undo_can_find_it(client_in, owned_library, game):
    from games.views.bulk import _act_of

    session = a_running_session(owned_library, game)

    _run(client_in, session)

    end = LibraryEvent.objects.get(event_type="library.playersession.ended")
    assert end.source_metadata["bulk"]["action"] == "session.finish"
    assert _act_of(owned_library, end.correlation_id) is FINISH_SESSION


def test_the_inverse_puts_a_finished_row_back_to_running(
    client_in, owned_library, game, owned_user
):
    session = a_running_session(owned_library, game)
    _run(client_in, session)
    end = LibraryEvent.objects.get(event_type="library.playersession.ended")

    FINISH_SESSION.inverse(
        owned_user,
        session.pk,
        undoes=end.correlation_id,
        idempotency_key="an-undo",
        correlation_id=uuid.uuid7(),
    )

    session.refresh_from_db()
    assert session.ended_at is None
    assert session.started_at == STARTED_AT


def test_the_act_is_declared(owned_library):
    assert BULK_ACTIONS["session.finish"] is FINISH_SESSION
    assert FINISH_SESSION.choice is not None
