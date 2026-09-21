"""Many sessions moved to one playthrough, and put back."""

import html as html_module
import json
import uuid
from datetime import date, timedelta

import pytest
from django.contrib.messages import get_messages
from django.http import QueryDict
from django.urls import reverse
from django.utils import timezone
from session_rows import duration_only_row, tracked_run

from games.bulk_actions import AsksNothing, Control, RefusedAct
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
    HistoricalPlaytimeRun,
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
    """A row in the bucket, made the one way.

    `CreateSession` refuses one outright; only a move
    reaches a bucket.
    """
    session = a_recorded_session(owned_user, ordinary, day)
    move_session(owned_user, session, bucket.pk, correlation_id=uuid.uuid7())
    session.refresh_from_db()
    return session


def a_recorded_session(owned_user, run, day=A_DAY) -> PlayerSession:
    """A session with the events a real one has.

    The Undo reads the row's own stream, which a
    hand-written projection row does not have.
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

    assert offer_target(owned_library, rows, CHOICE_FIELD) == RefusedAct(
        TWO_GAMES.format(count=2)
    )


def test_one_game_answers_a_control(owned_library, game):
    rows = move_resolution(
        owned_library, [a_session(tracked_run(owned_library, game)).pk]
    ).rows

    answered = offer_target(owned_library, rows, CHOICE_FIELD)

    assert isinstance(answered, Control)
    offered = str(answered.node)
    assert f'name="{CHOICE_FIELD}"' in offered
    assert str(game.pk) in offered


def test_the_game_count_is_the_selection_not_the_sample(
    owned_library, game, other_game
):
    """The count is the selection's, not the sample's.

    Newest first, fifty printed, so the row at the second
    game is the fifty-first.
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
    assert offer_target(owned_library, rows, CHOICE_FIELD) == RefusedAct(
        TWO_GAMES.format(count=2)
    )


def test_no_rows_ask_nothing(owned_library):
    """Not an empty control: there is no question to put."""
    assert offer_target(owned_library, (), CHOICE_FIELD) == AsksNothing()


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

    outcome = move_one(
        owned_user,
        session,
        choice=str(target.pk),
        idempotency_key="one-move",
        correlation_id=uuid.uuid7(),
    )

    assert outcome.value == "moved"
    session.refresh_from_db()
    assert session.playthrough_id == target.pk


def test_a_row_already_on_the_target_is_unchanged(owned_user, owned_library, game):
    target = tracked_run(owned_library, game)
    session = a_session(target)

    outcome = move_one(
        owned_user,
        session,
        choice=str(target.pk),
        idempotency_key="one-move",
        correlation_id=uuid.uuid7(),
    )

    assert outcome.value == "unchanged"


def test_a_row_at_another_game_is_refused(owned_user, owned_library, game, other_game):
    target = tracked_run(owned_library, game)
    session = a_session(tracked_run(owned_library, other_game))

    with pytest.raises(CommandFailed) as refusal:
        move_one(
            owned_user,
            session,
            choice=str(target.pk),
            idempotency_key="one-move",
            correlation_id=uuid.uuid7(),
        )

    assert refusal.value.status_code == 409
    assert refusal.value.message == ANOTHER_GAME
    session.refresh_from_db()
    assert session.playthrough_id != target.pk


def test_the_last_row_out_of_a_bucket_takes_the_bucket_away(
    owned_user, owned_library, game
):
    target = tracked_run(owned_library, game)
    bucket = a_run(owned_library, game, kind=PlaythroughKind.IMPORTED_HISTORY)
    session = a_bucket_session(owned_user, target, bucket)
    batch = uuid.uuid7()

    move_one(
        owned_user,
        session,
        choice=str(target.pk),
        idempotency_key="one-move",
        correlation_id=batch,
    )

    bucket.refresh_from_db()
    assert bucket.removed_at is not None


def test_only_the_bucket_the_row_left_is_taken_away(owned_user, owned_library, game):
    """An act removes only what it emptied."""
    target = tracked_run(owned_library, game)
    emptied = a_run(owned_library, game, kind=PlaythroughKind.IMPORTED_HISTORY)
    stranger = a_run(owned_library, game, kind=PlaythroughKind.IMPORTED_HISTORY)
    session = a_bucket_session(owned_user, target, emptied)

    move_one(
        owned_user,
        session,
        choice=str(target.pk),
        idempotency_key="one-move",
        correlation_id=uuid.uuid7(),
    )

    emptied.refresh_from_db()
    stranger.refresh_from_db()
    assert emptied.removed_at is not None
    assert stranger.removed_at is None


def test_a_move_between_two_runs_leaves_the_games_bucket_alone(
    owned_user, owned_library, game
):
    """No bucket touched, so none taken away."""
    source = tracked_run(owned_library, game)
    target = a_run(owned_library, game, name="Target run")
    stranger = a_run(owned_library, game, kind=PlaythroughKind.IMPORTED_HISTORY)
    session = a_recorded_session(owned_user, source)

    move_one(
        owned_user,
        session,
        choice=str(target.pk),
        idempotency_key="one-move",
        correlation_id=uuid.uuid7(),
    )

    stranger.refresh_from_db()
    assert stranger.removed_at is None


def test_a_replayed_chunk_still_asks_about_the_bucket(owned_user, owned_library, game):
    """The row names the target by then, so the events are asked.

    A bucket a live sibling kept survives the first pass. The
    sibling goes, the chunk is posted again under the same key,
    and the move answers `Unchanged` -- which is why the question
    is put to the batch's events and not to the row.
    """
    target = tracked_run(owned_library, game)
    bucket = a_run(owned_library, game, kind=PlaythroughKind.IMPORTED_HISTORY)
    sibling = a_bucket_session(
        owned_user, target, bucket, day=A_DAY + timedelta(days=1)
    )
    session = a_bucket_session(owned_user, target, bucket)
    batch = uuid.uuid7()

    move_one(
        owned_user,
        session,
        choice=str(target.pk),
        idempotency_key="one-move",
        correlation_id=batch,
    )
    bucket.refresh_from_db()
    assert bucket.removed_at is None

    PlayerSession.objects.filter(pk=sibling.pk).update(removed_at=timezone.now())
    move_one(
        owned_user,
        session,
        choice=str(target.pk),
        idempotency_key="one-move",
        correlation_id=batch,
    )

    bucket.refresh_from_db()
    assert bucket.removed_at is None, "a removed sibling still names it"


def test_a_bucket_a_removed_session_names_is_left_alone(
    owned_user, owned_library, game
):
    """A removed row is restorable, so the bucket stays."""
    target = tracked_run(owned_library, game)
    bucket = a_run(owned_library, game, kind=PlaythroughKind.IMPORTED_HISTORY)
    gone = a_bucket_session(owned_user, target, bucket, day=A_DAY + timedelta(days=1))
    PlayerSession.objects.filter(pk=gone.pk).update(removed_at=timezone.now())
    session = a_bucket_session(owned_user, target, bucket)

    move_one(
        owned_user,
        session,
        choice=str(target.pk),
        idempotency_key="one-move",
        correlation_id=uuid.uuid7(),
    )

    bucket.refresh_from_db()
    assert bucket.removed_at is None


def test_a_record_naming_a_bucket_keeps_it(owned_user, owned_library, game):
    """The second registered referrer, not only the first."""
    target = tracked_run(owned_library, game)
    bucket = a_run(owned_library, game, kind=PlaythroughKind.IMPORTED_HISTORY)
    session = a_bucket_session(owned_user, target, bucket)
    HistoricalPlaytimeRun.objects.create(
        pk=uuid.uuid7(),
        library=owned_library,
        record=a_record(owned_user, owned_library, target),
        playthrough=bucket,
    )

    move_one(
        owned_user,
        session,
        choice=str(target.pk),
        idempotency_key="one-move",
        correlation_id=uuid.uuid7(),
    )

    bucket.refresh_from_db()
    assert bucket.removed_at is None


def test_a_bucket_whose_removal_refuses_leaves_the_row_moved(
    owned_user, owned_library, game, monkeypatch
):
    target = tracked_run(owned_library, game)
    bucket = a_run(owned_library, game, kind=PlaythroughKind.IMPORTED_HISTORY)
    session = a_bucket_session(owned_user, target, bucket)

    def refuses(*args, **kwargs):
        raise CommandFailed("no", 409)

    monkeypatch.setattr("games.bulk_move.remove_run", refuses)

    outcome = move_one(
        owned_user,
        session,
        choice=str(target.pk),
        idempotency_key="one-move",
        correlation_id=uuid.uuid7(),
    )

    assert outcome.value == "moved"
    session.refresh_from_db()
    assert session.playthrough_id == target.pk


def test_a_bucket_removal_that_is_a_defect_ends_the_batch(
    owned_user, owned_library, game, monkeypatch
):
    """A 500 is the runner's to answer, not this act's to hide."""
    target = tracked_run(owned_library, game)
    bucket = a_run(owned_library, game, kind=PlaythroughKind.IMPORTED_HISTORY)
    session = a_bucket_session(owned_user, target, bucket)

    def breaks(*args, **kwargs):
        raise CommandFailed("broken", 500)

    monkeypatch.setattr("games.bulk_move.remove_run", breaks)

    with pytest.raises(CommandFailed) as defect:
        move_one(
            owned_user,
            session,
            choice=str(target.pk),
            idempotency_key="one-move",
            correlation_id=uuid.uuid7(),
        )

    assert defect.value.status_code == 500


def test_a_row_with_a_device_and_a_note_previews_both(owned_library, game):
    device = Device.objects.create(library=owned_library, name="Deck")
    session = a_session(tracked_run(owned_library, game), device=device, note="hi")

    rows = move_resolution(owned_library, [session.pk]).rows

    assert rows[0].device.name == "Deck"
    assert rows[0].note == "hi"


# ── The Undo ─────────────────────────────────────────────────────────────────


def _posted(response) -> dict[str, str]:
    """The hidden fields the confirmation would submit."""
    body = response.content.decode()
    fields = {}
    for name in (TOKEN_FIELD, PROGRESS_FIELD):
        marker = f'name="{name}" value="'
        start = body.index(marker) + len(marker)
        fields[name] = html_module.unescape(body[start : body.index('"', start)])
    return fields


def _confirm(client, *sessions):
    """The first POST, which names the rows."""
    return client.post(
        MOVE_URL,
        {
            STATEMENT_FIELD: json.dumps(
                {"mode": "some", "keys": [str(session.pk) for session in sessions]}
            )
        },
    )


def _batch(client, *sessions, target):
    """Confirm and act, answering the question with `target`."""
    fields = _posted(_confirm(client, *sessions))
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


def test_an_undo_returns_a_row_to_the_run_that_created_it(
    client_in, owned_user, owned_library, game
):
    """The commonest shape: a row this batch moved for the first time.

    Its earlier run is named by a `created` payload, not by an
    earlier `moved` one, and nothing else reads that key.
    """
    source = tracked_run(owned_library, game)
    target = a_run(owned_library, game, name="Target run")
    session = a_recorded_session(owned_user, source)

    token = _batch(client_in, session, target=target)
    session.refresh_from_db()
    assert session.playthrough_id == target.pk

    _undo(client_in, token)

    session.refresh_from_db()
    assert session.playthrough_id == source.pk
    source.refresh_from_db()
    assert source.removed_at is None


def test_a_batch_refuses_a_cross_game_row_and_moves_the_rest(
    client_in, owned_user, owned_library, game, other_game
):
    """The game is the row's rule, so one bad row is one refusal.

    A continuation's rows can span two games, which is why the
    settle says nothing about the game. The tally is the person's
    to edit, so this is the shape that reaches the runner.
    """
    target = tracked_run(owned_library, game)
    ours = a_recorded_session(owned_user, a_run(owned_library, game, name="Second"))
    theirs = a_recorded_session(owned_user, tracked_run(owned_library, other_game))

    fields = _posted(_confirm(client_in, ours))
    #: Both rows, as a person editing the progress form would state.
    fields[PROGRESS_FIELD] = json.dumps(
        {"rows": [str(ours.pk), str(theirs.pk)], "total": 2}
    )
    answer = client_in.post(
        MOVE_URL, {**fields, CHOICE_FIELD: str(target.pk)}, follow=True
    )

    ours.refresh_from_db()
    theirs.refresh_from_db()
    assert ours.playthrough_id == target.pk
    assert theirs.playthrough_id != target.pk
    assert ANOTHER_GAME in " ".join(
        str(message) for message in get_messages(answer.wsgi_request)
    )


def test_run_before_reads_an_earlier_move(owned_user, owned_library, game):
    first = tracked_run(owned_library, game)
    second = a_run(owned_library, game, name="Second run")
    third = a_run(owned_library, game, name="Third run")
    session = a_recorded_session(owned_user, first)
    move_one(
        owned_user,
        session,
        choice=str(second.pk),
        idempotency_key="first-move",
        correlation_id=uuid.uuid7(),
    )
    batch = uuid.uuid7()
    move_one(
        owned_user,
        session,
        choice=str(third.pk),
        idempotency_key="second-move",
        correlation_id=batch,
    )

    assert run_before(owned_library, session.pk, batch) == second.pk


def test_a_key_that_is_not_this_batchs_is_refused(owned_user, owned_library, game):
    target = tracked_run(owned_library, game)
    session = a_recorded_session(
        owned_user, a_run(owned_library, game, name="Second run")
    )
    move_one(
        owned_user,
        session,
        choice=str(target.pk),
        idempotency_key="one-move",
        correlation_id=uuid.uuid7(),
    )

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
    session = a_bucket_session(owned_user, target, bucket)

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


def a_record(owned_user, owned_library, run):
    """One historical playtime record, to name a run with."""
    from datetime import timedelta as _timedelta

    from games.commands.historical_playtime import HistoricalPlaytimeStatement
    from games.models import HistoricalPlaytime, HistoricalPlaytimeProvenance
    from games.writes.historical_playtime import record_historical_playtime

    record_id = record_historical_playtime(
        owned_user,
        HistoricalPlaytimeStatement(
            duration=_timedelta(hours=10),
            when="2005",
            provenance=HistoricalPlaytimeProvenance.ESTIMATED,
            playthrough_ids=(run.pk,),
            device_id=None,
            emulated=False,
            note="",
        ),
        idempotency_key=str(uuid.uuid7()),
        correlation_id=uuid.uuid7(),
    )
    return HistoricalPlaytime.objects.get(pk=record_id)


def test_a_move_with_no_target_answers_a_defect(owned_user, owned_library, game):
    """The runner settles before a row, so `None` is ours.

    The guard sits inside `answered`, where a defect becomes
    an answer the batch ends on. Carried out of that block by
    a later edit it would escape as a bare 500, and the rows
    left alone would go unnamed in the log.
    """
    session = a_session(tracked_run(owned_library, game))

    with pytest.raises(CommandFailed) as defect:
        move_one(
            owned_user,
            session,
            choice=None,
            idempotency_key="one-move",
            correlation_id=uuid.uuid7(),
        )

    assert defect.value.status_code == 500
