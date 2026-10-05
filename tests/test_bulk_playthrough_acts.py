"""Stating one endpoint at today, on many runs."""

import html as html_module
import json
import uuid
from datetime import date

import pytest
from bulk_posts import said
from django.http import QueryDict
from django.urls import reverse
from django.utils import timezone
from session_rows import tracked_run

from games.bulk_actions import BULK_ACTIONS
from games.bulk_playthrough_acts import (
    COMPLETE_RUNS,
    DAY_UNREADABLE,
    START_RUNS,
    DayStatement,
    settle_day,
    void_completion_one,
    void_start_one,
)
from games.commands.playthrough import (
    RUN_UNDO,
    CorrectPlaythroughStart,
    MovePlaythroughToGame,
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
from games.writes.answers import CommandFailed
from games.writes.playergame import (
    new_correlation_id,
    record_facts,
    remove_from_library,
    track_game,
)
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


def _tracked(user, name) -> Game:
    """Through the command: an Undo reads the stream."""
    game = Game.objects.create(library=user.library, name=name)
    track_game(user, game, correlation_id=new_correlation_id())
    return game


@pytest.fixture
def game(owned_user):
    return _tracked(owned_user, "Outer Wilds")


@pytest.fixture
def second_game(owned_user):
    return _tracked(owned_user, "Tunic")


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


def _status_events(game):
    tracked = PlayerGame.objects.get(game=game)
    return LibraryEvent.objects.filter(
        aggregate_id=tracked.pk, event_type=STATUS_CHANGED
    ).order_by("sequence")


def _statused(game) -> PlayerGameStatus:
    return PlayerGameStatus(PlayerGame.objects.get(game=game).status)


def _move(user, library, run, target, key):
    dispatch(
        MovePlaythroughToGame(playthrough_id=run.pk, game_id=target.pk),
        actor=user,
        library=library,
        idempotency_key=key,
    )


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


def test_an_undo_after_a_move_puts_the_old_game_s_status_back(
    client_in, owned_user, owned_library, game, second_game
):
    run = tracked_run(owned_library, game)
    token, _ = _run(client_in, COMPLETE_URL, run)
    _move(owned_user, owned_library, run, second_game, "move")

    _undo(client_in, token)

    run.refresh_from_db()
    assert run.completed is None
    assert _statused(game) == PlayerGameStatus.UNPLAYED
    assert _statused(second_game) == PlayerGameStatus.UNPLAYED


def test_an_undo_reads_the_game_the_batch_found(
    client_in, owned_user, owned_library, game, second_game
):
    """Moved in, stated, moved back: the middle game."""
    run = tracked_run(owned_library, game)
    _move(owned_user, owned_library, run, second_game, "there")
    token, _ = _run(client_in, COMPLETE_URL, run)
    _move(owned_user, owned_library, run, game, "back")
    record_facts(
        owned_user,
        game,
        status=PlayerGameStatus.PLAYED,
        correlation_id=new_correlation_id(),
    )

    _undo(client_in, token)

    assert _statused(second_game) == PlayerGameStatus.UNPLAYED
    assert _statused(game) == PlayerGameStatus.PLAYED


def test_an_undo_after_the_old_game_left_voids_alone(
    client_in, owned_user, owned_library, game, second_game
):
    run = tracked_run(owned_library, game)
    token, _ = _run(client_in, COMPLETE_URL, run)
    _move(owned_user, owned_library, run, second_game, "move")
    remove_from_library(owned_user, game, correlation_id=new_correlation_id())

    _undo(client_in, token)

    run.refresh_from_db()
    assert run.completed is None


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
    assert RUN_UNDO.changed_since in said(undone)


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
    assert RUN_UNDO.changed_since in said(undone)


def test_a_stream_with_no_creation_ends_the_undo_before_the_void(
    client_in, owned_library
):
    """A projection row written by hand has no stream behind it."""
    game = Game.objects.create(library=owned_library, name="Written by hand")
    run = tracked_run(owned_library, game)
    token, _ = _run(client_in, START_URL, run)

    _undo(client_in, token)

    run.refresh_from_db()
    assert run.started is not None
    assert _statused(game) == PlayerGameStatus.PLAYED


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
    with pytest.raises(CommandFailed) as refused:
        void_start_one(
            owned_user,
            run.pk,
            undoes=uuid.uuid7(),
            idempotency_key="not-ours",
            correlation_id=uuid.uuid7(),
        )

    assert RUN_UNDO.not_stated in str(refused.value.message)
    run.refresh_from_db()
    assert run.started == OTHER_DAY


@pytest.mark.parametrize(
    ("inverse", "day_column", "marker_column"),
    [
        (void_start_one, "started", "start_recorded_at"),
        (void_completion_one, "completed", "completion_recorded_at"),
    ],
)
def test_an_endpoint_stated_with_no_event_refuses_the_undo(
    owned_user, owned_library, game, inverse, day_column, marker_column
):
    """A marker no event wrote is no batch's."""
    run = tracked_run(owned_library, game)
    Playthrough.objects.filter(pk=run.pk).update(
        **{day_column: OTHER_DAY, marker_column: timezone.now()}
    )

    with pytest.raises(CommandFailed) as refused:
        inverse(
            owned_user,
            run.pk,
            undoes=uuid.uuid7(),
            idempotency_key="marker-alone",
            correlation_id=uuid.uuid7(),
        )

    assert refused.value.message == RUN_UNDO.not_stated
    assert refused.value.status_code == 409
    run.refresh_from_db()
    assert getattr(run, day_column) == OTHER_DAY
