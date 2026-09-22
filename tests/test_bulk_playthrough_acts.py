"""Stating one endpoint at today, on many runs."""

import html as html_module
import json
import uuid
from datetime import date

import pytest
from django.contrib.messages import get_messages
from django.http import QueryDict
from django.urls import reverse
from session_rows import tracked_run

from games.bulk_actions import BULK_ACTIONS
from games.bulk_playthrough_acts import (
    CHANGED_SINCE,
    COMPLETE_RUNS,
    DAY_UNREADABLE,
    NOT_STATED_BY_THIS_BATCH,
    START_RUNS,
    DayStatement,
    settle_day,
)
from games.commands.playthrough import (
    CorrectPlaythroughStart,
    StartPlaythrough,
)
from games.events.dispatch import CommandRejected, dispatch
from games.models import (
    Game,
    LibraryEvent,
    PlayerGame,
    PlayerGameStatus,
    Playthrough,
)
from games.reads.calendar import calendar_today
from games.views.bulk import (
    CHOICE_FIELD,
    PROGRESS_FIELD,
    STATEMENT_FIELD,
    TOKEN_FIELD,
)
from games.writes.playergame import new_correlation_id, record_facts
from timetracker.temporal import TemporalValue

pytestmark = [pytest.mark.untracked_games, pytest.mark.django_db(transaction=True)]

START_URL = reverse("games:run_bulk_action", args=[START_RUNS.name])
COMPLETE_URL = reverse("games:run_bulk_action", args=[COMPLETE_RUNS.name])

STATUS_CHANGED = "library.playergame.status_changed"
OTHER_DAY = TemporalValue.from_day(date(2020, 1, 2))


@pytest.fixture
def client_in(client, owned_user):
    client.force_login(owned_user)
    return client


@pytest.fixture
def game(owned_library):
    return Game.objects.create(library=owned_library, name="Outer Wilds")


@pytest.fixture
def second_game(owned_library):
    return Game.objects.create(library=owned_library, name="Tunic")


def some(*runs) -> str:
    return json.dumps({"mode": "some", "keys": sorted(str(run.pk) for run in runs)})


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
    post = QueryDict(mutable=True)
    post.update(fields)
    return post


def _run(client, url, *runs):
    """Confirm, then post the confirmation through to the end.

    Answers the token as well: the batch's Undo is keyed on it.
    """
    confirmation = client.post(url, {STATEMENT_FIELD: some(*runs)})
    fields = posted(confirmation)
    return fields[TOKEN_FIELD], client.post(url, fields)


def _undo(client, token):
    """Press the Undo the batch's answer offers."""
    return client.post(reverse("games:undo_bulk_action", args=[token]))


def said(response) -> list[str]:
    """Every sentence the answer queued."""
    return [str(message) for message in get_messages(response.wsgi_request)]


def _status_events(game):
    tracked = PlayerGame.objects.get(game=game)
    return LibraryEvent.objects.filter(
        aggregate_id=tracked.pk, event_type=STATUS_CHANGED
    ).order_by("sequence")


def _statused(game) -> PlayerGameStatus:
    return PlayerGameStatus(PlayerGame.objects.get(game=game).status)


# ── The day the batch states ─────────────────────────────────────────────────


def test_a_day_survives_its_own_encoding():
    stated = DayStatement(date(2026, 3, 5))

    assert DayStatement.decode(stated.encode()) == stated


def test_settling_is_idempotent(owned_library):
    first = settle_day(
        owned_library, _post(**{CHOICE_FIELD: DayStatement(date(2026, 3, 5)).encode()})
    )

    assert settle_day(owned_library, _post(**{CHOICE_FIELD: first})) == first


def test_an_unreadable_day_is_refused_with_a_sentence(owned_library):
    with pytest.raises(CommandRejected) as refusal:
        settle_day(owned_library, _post(**{CHOICE_FIELD: "the fifth"}))

    assert refusal.value.sentence == DAY_UNREADABLE


def test_both_acts_are_declared():
    assert BULK_ACTIONS[START_RUNS.name] is START_RUNS
    assert BULK_ACTIONS[COMPLETE_RUNS.name] is COMPLETE_RUNS


# ── Forward ──────────────────────────────────────────────────────────────────


def test_a_selected_run_states_a_start_today(client_in, owned_library, game):
    run = tracked_run(owned_library, game)

    _run(client_in, START_URL, run)

    run.refresh_from_db()
    assert run.started == TemporalValue.from_day(calendar_today(owned_library))
    assert run.start_recorded_at is not None


def test_the_confirmation_names_the_day_and_the_side_effect(
    client_in, owned_library, game
):
    run = tracked_run(owned_library, game)

    confirmation = client_in.post(COMPLETE_URL, {STATEMENT_FIELD: some(run)})

    markup = confirmation.content.decode()
    assert calendar_today(owned_library).isoformat() in markup
    assert "Each game is marked Completed" in markup


def test_a_run_that_states_a_start_is_refused_by_row(
    client_in, owned_user, owned_library, game, second_game
):
    stated = tracked_run(owned_library, game)
    dispatch(
        StartPlaythrough(playthrough_id=stated.pk, when=OTHER_DAY, note=""),
        actor=owned_user,
        library=owned_library,
        idempotency_key="by-hand",
    )
    fresh = tracked_run(owned_library, second_game)

    _, answer = _run(client_in, START_URL, stated, fresh)

    stated.refresh_from_db()
    fresh.refresh_from_db()
    assert stated.started == OTHER_DAY
    assert fresh.started == TemporalValue.from_day(calendar_today(owned_library))
    assert any("already has a start" in sentence for sentence in said(answer))


def test_a_run_that_states_today_already_counts_as_already_so(
    client_in, owned_user, owned_library, game
):
    run = tracked_run(owned_library, game)
    today = TemporalValue.from_day(calendar_today(owned_library))
    dispatch(
        StartPlaythrough(playthrough_id=run.pk, when=today, note=""),
        actor=owned_user,
        library=owned_library,
        idempotency_key="by-hand",
    )

    _, answer = _run(client_in, START_URL, run)

    assert any("already" in sentence for sentence in said(answer))


def test_a_completion_states_completed_on_the_game(client_in, owned_library, game):
    run = tracked_run(owned_library, game)

    _run(client_in, COMPLETE_URL, run)

    assert _statused(game) == PlayerGameStatus.COMPLETED
    assert _status_events(game).count() == 1


def test_a_start_states_played_only_where_offered(
    client_in, owned_library, game, second_game
):
    first = tracked_run(owned_library, game)
    second = tracked_run(owned_library, second_game)
    PlayerGame.objects.filter(game=second_game).update(
        status=PlayerGameStatus.ABANDONED
    )

    _run(client_in, START_URL, first, second)

    assert _statused(game) == PlayerGameStatus.PLAYED
    assert _statused(second_game) == PlayerGameStatus.ABANDONED


def test_a_chunk_posted_twice_acts_once(client_in, owned_library, game):
    run = tracked_run(owned_library, game)

    confirmation = client_in.post(START_URL, {STATEMENT_FIELD: some(run)})
    fields = posted(confirmation)
    client_in.post(START_URL, fields)
    client_in.post(START_URL, fields)

    assert (
        LibraryEvent.objects.filter(
            aggregate_id=run.pk, event_type="library.playthrough.started"
        ).count()
        == 1
    )
    assert _status_events(game).count() == 1


def test_the_stamped_day_is_the_confirmation_s(client_in, owned_library, game):
    run = tracked_run(owned_library, game)

    confirmation = client_in.post(START_URL, {STATEMENT_FIELD: some(run)})

    assert (
        posted(confirmation)[CHOICE_FIELD] == calendar_today(owned_library).isoformat()
    )


def test_a_doctored_day_field_states_that_day(client_in, owned_library, game):
    run = tracked_run(owned_library, game)

    confirmation = client_in.post(START_URL, {STATEMENT_FIELD: some(run)})
    fields = posted(confirmation) | {CHOICE_FIELD: "2001-09-11"}
    client_in.post(START_URL, fields)

    run.refresh_from_db()
    assert run.started == TemporalValue.from_day(date(2001, 9, 11))


# ── Backward ─────────────────────────────────────────────────────────────────


def test_an_undo_voids_the_start_and_puts_the_status_back(
    client_in, owned_library, game
):
    run = tracked_run(owned_library, game)
    token, _ = _run(client_in, START_URL, run)

    _undo(client_in, token)

    run.refresh_from_db()
    assert run.started is None
    assert run.start_recorded_at is None
    assert _statused(game) == PlayerGameStatus.UNPLAYED


def test_an_undo_of_a_completion_puts_an_earlier_word_back(
    client_in, owned_user, owned_library, game
):
    run = tracked_run(owned_library, game)
    record_facts(
        owned_user,
        game,
        status=PlayerGameStatus.PLAYED,
        correlation_id=new_correlation_id(),
    )
    token, _ = _run(client_in, COMPLETE_URL, run)

    _undo(client_in, token)

    run.refresh_from_db()
    assert run.completed is None
    assert _statused(game) == PlayerGameStatus.PLAYED


def test_an_undo_leaves_a_status_a_person_changed(
    client_in, owned_user, owned_library, game
):
    run = tracked_run(owned_library, game)
    token, _ = _run(client_in, COMPLETE_URL, run)
    #: A person's own statement, which is an event; a column written
    #: behind the stream would be drift, not a change to respect.
    record_facts(
        owned_user,
        game,
        status=PlayerGameStatus.RETIRED,
        correlation_id=new_correlation_id(),
    )

    _undo(client_in, token)

    run.refresh_from_db()
    assert run.completed is None
    assert _statused(game) == PlayerGameStatus.RETIRED


def test_two_rows_at_one_game_restore_one_status(client_in, owned_library, game):
    first = tracked_run(owned_library, game)
    second = Playthrough.objects.create(
        pk=uuid.uuid7(),
        library=owned_library,
        player_game=first.player_game,
        kind=first.kind,
        created_at=first.created_at,
    )
    token, _ = _run(client_in, START_URL, first, second)

    _undo(client_in, token)

    assert _statused(game) == PlayerGameStatus.UNPLAYED
    for run in (first, second):
        run.refresh_from_db()
        assert run.started is None


def test_a_corrected_endpoint_refuses_the_undo(
    client_in, owned_user, owned_library, game
):
    run = tracked_run(owned_library, game)
    token, _ = _run(client_in, START_URL, run)
    dispatch(
        CorrectPlaythroughStart(playthrough_id=run.pk, when=OTHER_DAY, note=""),
        actor=owned_user,
        library=owned_library,
        idempotency_key="corrected-since",
    )

    undone = _undo(client_in, token)

    run.refresh_from_db()
    assert run.started == OTHER_DAY
    assert CHANGED_SINCE in said(undone)


def test_a_restated_endpoint_refuses_the_undo(
    client_in, owned_user, owned_library, game
):
    """A void and a second statement are one case."""
    run = tracked_run(owned_library, game)
    token, _ = _run(client_in, START_URL, run)
    _undo(client_in, token)
    dispatch(
        StartPlaythrough(playthrough_id=run.pk, when=OTHER_DAY, note=""),
        actor=owned_user,
        library=owned_library,
        idempotency_key="stated-again",
    )

    undone = _undo(client_in, token)

    run.refresh_from_db()
    assert run.started == OTHER_DAY
    assert CHANGED_SINCE in said(undone)


def test_an_undo_pressed_twice_is_already_so(client_in, owned_library, game):
    run = tracked_run(owned_library, game)
    token, _ = _run(client_in, START_URL, run)
    _undo(client_in, token)

    again = _undo(client_in, token)

    run.refresh_from_db()
    assert run.started is None
    assert any("already" in sentence for sentence in said(again))


def test_a_row_of_another_batch_states_its_own_sentence(
    client_in, owned_user, owned_library, game
):
    run = tracked_run(owned_library, game)
    dispatch(
        StartPlaythrough(playthrough_id=run.pk, when=OTHER_DAY, note=""),
        actor=owned_user,
        library=owned_library,
        idempotency_key="by-hand",
    )
    #: A batch that states nothing about this row, so its Undo has
    #: nothing of its own to take back.
    from games.bulk_playthrough_acts import void_start_one

    with pytest.raises(Exception) as refused:
        void_start_one(
            owned_user,
            run.pk,
            undoes=uuid.uuid7(),
            idempotency_key="not-ours",
            correlation_id=uuid.uuid7(),
        )

    assert NOT_STATED_BY_THIS_BATCH in str(refused.value.message)
    run.refresh_from_db()
    assert run.started == OTHER_DAY
