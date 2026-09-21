"""Many sessions moved to one playthrough, and put back."""

import html as html_module
import json
import uuid
from datetime import date, timedelta

import pytest
from django.http import QueryDict
from django.urls import reverse
from django.utils import timezone
from session_rows import duration_only_row, tracked_run

from games.bulk_move import (
    ANOTHER_GAME,
    NOT_MOVED_BY_THIS_BATCH,
    RUN_LABEL_ATTRIBUTE,
    TARGET_GONE,
    TWO_GAMES,
    move_one,
    move_resolution,
    move_scope,
    offer_target,
    run_before,
    settle_target,
)
from games.commands.playersession import CreateSession, DurationOnlyTiming
from games.events.dispatch import CommandRejected, dispatch
from games.models import (
    Device,
    Game,
    LibraryEvent,
    PlayerGame,
    PlayerSession,
    Playthrough,
    PlaythroughKind,
)
from games.reads.session_run_labels import IMPORTED_HISTORY_LABEL
from games.views.bulk import (
    CHOICE_FIELD,
    CONFIRMATION_SAMPLE,
    PROGRESS_FIELD,
    STATEMENT_FIELD,
    TOKEN_FIELD,
)
from games.writes.answers import CommandFailed
from games.writes.playersession import move_session

pytestmark = pytest.mark.django_db(transaction=True)

A_DAY = date(2026, 3, 5)
AN_HOUR = timedelta(hours=1)
MOVE_URL = reverse("games:run_bulk_action", args=["session.move"])


@pytest.fixture
def game(owned_library):
    return Game.objects.create(library=owned_library, name="Outer Wilds")


@pytest.fixture
def other_game(owned_library):
    return Game.objects.create(library=owned_library, name="Celeste")


@pytest.fixture
def client_in(client, owned_user):
    client.force_login(owned_user)
    return client


def a_run(owned_library, game, *, kind=PlaythroughKind.ORDINARY, name=""):
    return Playthrough.objects.create(
        pk=uuid.uuid7(),
        library=owned_library,
        player_game=PlayerGame.objects.get(library=owned_library, game=game),
        kind=kind,
        name=name,
        created_at=timezone.now(),
    )


def a_session(run, day=A_DAY, **columns):
    return duration_only_row(run, day, AN_HOUR, **columns)


def a_bucket_session(owned_user, ordinary, bucket, day=A_DAY) -> PlayerSession:
    """A row in the bucket, made the one way there is.

    A command refuses to record into a bucket; only a move reaches
    one, which is how the legacy conversion filled them.
    """
    session = a_recorded_session(owned_user, ordinary, day)
    move_session(owned_user, session, bucket.pk, correlation_id=uuid.uuid7())
    session.refresh_from_db()
    return session


def a_recorded_session(owned_user, run, day=A_DAY) -> PlayerSession:
    """A session with the events a real one has.

    The Undo reads where a row sat from the row's own stream, so a
    hand-written projection row states nothing it can read.
    """
    dispatch(
        CreateSession(
            playthrough_id=run.pk,
            timing=DurationOnlyTiming(day=day, duration=AN_HOUR),
        ),
        actor=owned_user,
        library=owned_user.library,
        idempotency_key=str(uuid.uuid7()),
    )
    return PlayerSession.objects.get(playthrough=run, stated_day=day)


def post(**fields) -> QueryDict:
    stated = QueryDict(mutable=True)
    stated.update(fields)
    return stated


# ── The scope and the resolve ────────────────────────────────────────────────


def test_the_scope_narrows_by_the_statements_filter(owned_library, game, other_game):
    wanted = a_session(tracked_run(owned_library, game))
    a_session(tracked_run(owned_library, other_game))

    narrowed = move_scope(
        owned_library,
        json.dumps(
            {"game_filter": {"name": {"value": "Outer Wilds", "modifier": "EQUALS"}}}
        ),
    )

    assert list(narrowed.values_list("pk", flat=True)) == [wanted.pk]


def test_a_key_of_another_library_is_lost(owned_library, game, django_user_model):
    stranger = django_user_model.objects.create_user(
        username="second-owner", password="p"
    ).library
    theirs = Game.objects.create(library=stranger, name="Hollow Knight")
    foreign = a_session(tracked_run(stranger, theirs))

    resolution = move_resolution(owned_library, [foreign.pk])

    assert resolution.rows == ()
    assert [entry.lost for entry in resolution.refused] == [True]


def test_every_resolved_row_carries_its_runs_name(owned_library, game):
    """A game holding one run names it too, so the column reads."""
    sole = a_session(tracked_run(owned_library, game))
    bucket = a_session(
        a_run(owned_library, game, kind=PlaythroughKind.IMPORTED_HISTORY)
    )

    resolution = move_resolution(owned_library, [sole.pk, bucket.pk])

    labels = {row.pk: getattr(row, RUN_LABEL_ATTRIBUTE) for row in resolution.rows}
    assert labels == {sole.pk: "Playthrough 1", bucket.pk: IMPORTED_HISTORY_LABEL}


# ── The question ─────────────────────────────────────────────────────────────


def test_two_games_refuse_the_whole_act(owned_library, game, other_game):
    rows = move_resolution(
        owned_library,
        [
            a_session(tracked_run(owned_library, game)).pk,
            a_session(tracked_run(owned_library, other_game)).pk,
        ],
    ).rows

    assert offer_target(owned_library, rows, CHOICE_FIELD) == TWO_GAMES.format(count=2)


def test_one_game_answers_a_control(owned_library, game):
    rows = move_resolution(
        owned_library, [a_session(tracked_run(owned_library, game)).pk]
    ).rows

    offered = str(offer_target(owned_library, rows, CHOICE_FIELD))

    assert f'name="{CHOICE_FIELD}"' in offered
    assert str(game.pk) in offered


def test_the_game_count_is_the_selection_not_the_sample(
    owned_library, game, other_game
):
    """A page that asked about the printed rows would move the rest.

    The rows sort newest first and the confirmation prints fifty, so
    the one row at the second game is the fifty-first.
    """
    ours = tracked_run(owned_library, game)
    keys = [
        a_session(ours, day=A_DAY + timedelta(days=offset)).pk
        for offset in range(CONFIRMATION_SAMPLE)
    ]
    keys.append(
        a_session(
            tracked_run(owned_library, other_game), day=A_DAY - timedelta(days=1)
        ).pk
    )
    rows = move_resolution(owned_library, keys).rows

    assert len(rows) == CONFIRMATION_SAMPLE + 1
    assert offer_target(owned_library, rows, CHOICE_FIELD) == TWO_GAMES.format(count=2)


def test_no_rows_ask_nothing(owned_library):
    assert str(offer_target(owned_library, (), CHOICE_FIELD)) == ""


# ── The settle ───────────────────────────────────────────────────────────────


def test_a_live_ordinary_run_settles(owned_library, game):
    run = tracked_run(owned_library, game)

    assert settle_target(owned_library, post(**{CHOICE_FIELD: str(run.pk)})) == str(
        run.pk
    )


def test_a_run_at_another_game_settles_too(owned_library, game, other_game):
    """The game is the row's rule, not the target's."""
    run = tracked_run(owned_library, other_game)
    tracked_run(owned_library, game)

    assert settle_target(owned_library, post(**{CHOICE_FIELD: str(run.pk)})) == str(
        run.pk
    )


@pytest.mark.parametrize("stated", ["", "not-a-uuid"])
def test_an_unreadable_target_refuses(owned_library, stated):
    with pytest.raises(CommandRejected):
        settle_target(owned_library, post(**{CHOICE_FIELD: stated}))


def test_another_librarys_run_refuses(owned_library, django_user_model):
    stranger = django_user_model.objects.create_user(
        username="second-owner", password="p"
    ).library
    theirs = Game.objects.create(library=stranger, name="Hollow Knight")
    run = tracked_run(stranger, theirs)

    with pytest.raises(CommandRejected) as refusal:
        settle_target(owned_library, post(**{CHOICE_FIELD: str(run.pk)}))

    assert refusal.value.sentence == TARGET_GONE


def test_a_removed_run_refuses(owned_library, game):
    run = tracked_run(owned_library, game)
    Playthrough.objects.filter(pk=run.pk).update(removed_at=timezone.now())

    with pytest.raises(CommandRejected) as refusal:
        settle_target(owned_library, post(**{CHOICE_FIELD: str(run.pk)}))

    assert refusal.value.sentence == TARGET_GONE


def test_a_bucket_refuses(owned_library, game):
    tracked_run(owned_library, game)
    bucket = a_run(owned_library, game, kind=PlaythroughKind.IMPORTED_HISTORY)

    with pytest.raises(CommandRejected) as refusal:
        settle_target(owned_library, post(**{CHOICE_FIELD: str(bucket.pk)}))

    assert refusal.value.sentence == TARGET_GONE


# ── One row ──────────────────────────────────────────────────────────────────


def test_a_row_moves(owned_user, owned_library, game):
    target = tracked_run(owned_library, game)
    bucket = a_run(owned_library, game, kind=PlaythroughKind.IMPORTED_HISTORY)
    session = a_session(bucket)

    outcome = move_one(owned_user, session, str(target.pk), "one-move", uuid.uuid7())

    assert outcome.value == "moved"
    session.refresh_from_db()
    assert session.playthrough_id == target.pk


def test_a_row_already_on_the_target_is_unchanged(owned_user, owned_library, game):
    target = tracked_run(owned_library, game)
    session = a_session(target)

    outcome = move_one(owned_user, session, str(target.pk), "one-move", uuid.uuid7())

    assert outcome.value == "unchanged"


def test_a_row_at_another_game_is_refused(owned_user, owned_library, game, other_game):
    target = tracked_run(owned_library, game)
    session = a_session(tracked_run(owned_library, other_game))

    with pytest.raises(CommandFailed) as refusal:
        move_one(owned_user, session, str(target.pk), "one-move", uuid.uuid7())

    assert refusal.value.status_code == 409
    assert refusal.value.message == ANOTHER_GAME
    session.refresh_from_db()
    assert session.playthrough_id != target.pk


def test_the_last_row_out_of_a_bucket_takes_the_bucket_away(
    owned_user, owned_library, game
):
    target = tracked_run(owned_library, game)
    bucket = a_run(owned_library, game, kind=PlaythroughKind.IMPORTED_HISTORY)
    session = a_session(bucket)

    move_one(owned_user, session, str(target.pk), "one-move", uuid.uuid7())

    bucket.refresh_from_db()
    assert bucket.removed_at is not None


def test_a_game_holding_two_buckets_has_both_taken_away(
    owned_user, owned_library, game
):
    target = tracked_run(owned_library, game)
    first = a_run(owned_library, game, kind=PlaythroughKind.IMPORTED_HISTORY)
    second = a_run(owned_library, game, kind=PlaythroughKind.IMPORTED_HISTORY)
    session = a_session(first)

    move_one(owned_user, session, str(target.pk), "one-move", uuid.uuid7())

    for bucket in (first, second):
        bucket.refresh_from_db()
        assert bucket.removed_at is not None


def test_a_bucket_a_removed_session_names_is_left_alone(
    owned_user, owned_library, game
):
    """A removed row is restorable, so the bucket stays."""
    target = tracked_run(owned_library, game)
    bucket = a_run(owned_library, game, kind=PlaythroughKind.IMPORTED_HISTORY)
    gone = a_session(bucket, day=A_DAY + timedelta(days=1))
    PlayerSession.objects.filter(pk=gone.pk).update(removed_at=timezone.now())
    session = a_session(bucket)

    move_one(owned_user, session, str(target.pk), "one-move", uuid.uuid7())

    bucket.refresh_from_db()
    assert bucket.removed_at is None


def test_a_bucket_whose_removal_refuses_leaves_the_row_moved(
    owned_user, owned_library, game, monkeypatch
):
    target = tracked_run(owned_library, game)
    bucket = a_run(owned_library, game, kind=PlaythroughKind.IMPORTED_HISTORY)
    session = a_session(bucket)

    def refuses(*args, **kwargs):
        raise CommandFailed("no", 409)

    monkeypatch.setattr("games.bulk_move.remove_run", refuses)

    outcome = move_one(owned_user, session, str(target.pk), "one-move", uuid.uuid7())

    assert outcome.value == "moved"
    session.refresh_from_db()
    assert session.playthrough_id == target.pk


def test_a_row_with_a_device_and_a_note_previews_both(owned_library, game):
    device = Device.objects.create(library=owned_library, name="Deck")
    session = a_session(tracked_run(owned_library, game), device=device, note="hi")

    rows = move_resolution(owned_library, [session.pk]).rows

    assert rows[0].device.name == "Deck"
    assert rows[0].note == "hi"


# ── The Undo ─────────────────────────────────────────────────────────────────


def _batch(client, *sessions, target):
    """Confirm and act, answering the question with `target`."""
    confirmation = client.post(
        MOVE_URL,
        {
            STATEMENT_FIELD: json.dumps(
                {"mode": "some", "keys": [str(session.pk) for session in sessions]}
            )
        },
    )
    body = confirmation.content.decode()
    fields = {}
    for name in (TOKEN_FIELD, PROGRESS_FIELD):
        marker = f'name="{name}" value="'
        start = body.index(marker) + len(marker)
        fields[name] = html_module.unescape(body[start : body.index('"', start)])
    client.post(MOVE_URL, {**fields, CHOICE_FIELD: str(target.pk)})
    return fields[TOKEN_FIELD]


def _undo(client, token):
    return client.post(reverse("games:undo_bulk_action", args=[token]))


def test_an_undo_returns_a_row_to_the_run_its_creation_named(
    client_in, owned_user, owned_library, game
):
    target = tracked_run(owned_library, game)
    bucket = a_run(owned_library, game, kind=PlaythroughKind.IMPORTED_HISTORY)
    session = a_bucket_session(owned_user, target, bucket)

    token = _batch(client_in, session, target=target)
    _undo(client_in, token)

    session.refresh_from_db()
    assert session.playthrough_id == bucket.pk


def test_an_undo_puts_back_the_bucket_the_batch_took_away(
    client_in, owned_user, owned_library, game
):
    target = tracked_run(owned_library, game)
    bucket = a_run(owned_library, game, kind=PlaythroughKind.IMPORTED_HISTORY)
    session = a_bucket_session(owned_user, target, bucket)

    token = _batch(client_in, session, target=target)
    bucket.refresh_from_db()
    assert bucket.removed_at is not None

    _undo(client_in, token)

    bucket.refresh_from_db()
    assert bucket.removed_at is None


def test_run_before_reads_an_earlier_move(owned_user, owned_library, game):
    first = tracked_run(owned_library, game)
    second = a_run(owned_library, game, name="Second run")
    third = a_run(owned_library, game, name="Third run")
    session = a_recorded_session(owned_user, first)
    move_one(owned_user, session, str(second.pk), "first-move", uuid.uuid7())
    batch = uuid.uuid7()
    move_one(owned_user, session, str(third.pk), "second-move", batch)

    assert run_before(owned_library, session.pk, batch) == second.pk


def test_a_key_that_is_not_this_batchs_is_refused(owned_user, owned_library, game):
    target = tracked_run(owned_library, game)
    session = a_recorded_session(
        owned_user, a_run(owned_library, game, name="Second run")
    )
    move_one(owned_user, session, str(target.pk), "one-move", uuid.uuid7())

    with pytest.raises(CommandRejected) as refusal:
        run_before(owned_library, session.pk, uuid.uuid7())

    assert refusal.value.sentence == NOT_MOVED_BY_THIS_BATCH


def test_an_undo_refuses_a_run_removed_by_hand_after_the_batch(
    client_in, owned_user, owned_library, game
):
    """Restoring it would put back a run somebody took away on purpose."""
    target = tracked_run(owned_library, game)
    earlier = a_run(owned_library, game, name="Second run")
    session = a_recorded_session(owned_user, earlier)

    token = _batch(client_in, session, target=target)
    Playthrough.objects.filter(pk=earlier.pk).update(removed_at=timezone.now())

    _undo(client_in, token)

    session.refresh_from_db()
    assert session.playthrough_id == target.pk
    earlier.refresh_from_db()
    assert earlier.removed_at is not None


def test_a_run_the_batch_created_is_not_taken_away_by_its_undo(
    client_in, owned_user, owned_library, game
):
    target = a_run(owned_library, game, name="Made first")
    bucket = a_run(owned_library, game, kind=PlaythroughKind.IMPORTED_HISTORY)
    sole = tracked_run(owned_library, game)
    session = a_bucket_session(owned_user, sole, bucket)

    token = _batch(client_in, session, target=target)
    _undo(client_in, token)

    target.refresh_from_db()
    assert target.removed_at is None


def test_the_batchs_events_name_the_move_and_the_bucket(
    client_in, owned_user, owned_library, game
):
    target = tracked_run(owned_library, game)
    bucket = a_run(owned_library, game, kind=PlaythroughKind.IMPORTED_HISTORY)
    session = a_session(bucket)

    token = _batch(client_in, session, target=target)

    written = set(
        LibraryEvent.objects.filter(correlation_id=uuid.UUID(token)).values_list(
            "event_type", flat=True
        )
    )
    assert written == {"library.playersession.moved", "library.playthrough.removed"}


def test_the_undo_of_a_stopped_batch_leaves_untouched_rows_alone(
    client_in, owned_user, owned_library, game
):
    target = tracked_run(owned_library, game)
    bucket = a_run(owned_library, game, kind=PlaythroughKind.IMPORTED_HISTORY)
    moved = a_bucket_session(owned_user, target, bucket)
    untouched = a_bucket_session(
        owned_user, target, bucket, day=A_DAY + timedelta(days=1)
    )

    token = _batch(client_in, moved, target=target)
    _undo(client_in, token)

    untouched.refresh_from_db()
    assert untouched.playthrough_id == bucket.pk
