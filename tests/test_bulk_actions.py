"""What a bulk act declares, and what its declaration refuses."""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from django.utils import timezone
from session_rows import duration_only_row, timed_row, tracked_run

from games.bulk_actions import (
    _TABLE,
    BULK_ACTIONS,
    BulkAction,
    Cardinality,
    Presentations,
    PreviewColumn,
)
from games.bulk_reclassification import (
    ALREADY_RECORDED,
    IN_THE_BUCKET,
    NOT_AVAILABLE,
    NOT_WRITTEN,
    REVIEW_THRESHOLD_HOURS,
    UNDER_THRESHOLD,
)
from games.commands.playergame import TrackGame
from games.commands.playersession import CreateSession, DurationOnlyTiming
from games.events.dispatch import dispatch
from games.models import (
    Game,
    HistoricalPlaytime,
    PlayerSession,
    Playthrough,
    PlaythroughKind,
)
from games.views.session_reclassification import review_filter

pytestmark = [pytest.mark.untracked_games, pytest.mark.django_db(transaction=True)]

A_DAY = date(2026, 3, 5)
STARTED_AT = datetime(2026, 3, 5, 20, 0, tzinfo=UTC)
LONG_ENOUGH = timedelta(hours=REVIEW_THRESHOLD_HOURS + 1)


@pytest.fixture(autouse=True)
def prague_calendar(owned_user, set_user_setting):
    set_user_setting(owned_user, "DISPLAY_TIME_ZONE", "Europe/Prague")


@pytest.fixture
def game(owned_library):
    return Game.objects.create(library=owned_library, name="Outer Wilds")


@pytest.fixture
def run(owned_user, owned_library, game) -> Playthrough:
    dispatch(
        TrackGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="track",
    )
    return Playthrough.objects.get(player_game__game=game)


@pytest.fixture
def reclassify() -> BulkAction:
    return BULK_ACTIONS["session.reclassify"]


def a_written_session(library, actor, run, duration=LONG_ENOUGH, day=A_DAY):
    dispatch(
        CreateSession(
            playthrough_id=run.pk,
            timing=DurationOnlyTiming(day=day, duration=duration),
        ),
        actor=actor,
        library=library,
        idempotency_key=str(uuid.uuid7()),
    )
    return PlayerSession.objects.get(playthrough=run, stated_day=day)


def a_bucket_session(library, actor, game):
    """A written-down row in the imported-history bucket."""
    player_game = tracked_run(library, game).player_game
    bucket = Playthrough.objects.create(
        pk=uuid.uuid7(),
        library=library,
        player_game=player_game,
        kind=PlaythroughKind.IMPORTED_HISTORY,
        created_at=timezone.now(),
    )
    return duration_only_row(bucket, A_DAY, LONG_ENOUGH)


# ── The declaration ──────────────────────────────────────────────────────────


def test_the_table_holds_the_reclassification(reclassify):
    assert reclassify.cardinality is Cardinality.MANY
    assert reclassify.inverse_aggregate == "playersession"


def test_an_aggregate_no_event_declares_is_refused(reclassify):
    with pytest.raises(ValueError, match="playersesion"):
        BulkAction(
            name="session.typo",
            label=reclassify.label,
            title=reclassify.title,
            confirm_label=reclassify.confirm_label,
            subject=reclassify.subject,
            cardinality=Cardinality.MANY,
            color=reclassify.color,
            inverse_aggregate="playersesion",
            fallback=reclassify.fallback,
            scope=reclassify.scope,
            resolve=reclassify.resolve,
            run=reclassify.run,
            inverse=reclassify.inverse,
            preview=reclassify.preview,
        )


def test_a_name_the_table_already_holds_is_refused(reclassify):
    with pytest.raises(ValueError, match="already"):
        BulkAction(
            name="session.reclassify",
            label=reclassify.label,
            title=reclassify.title,
            confirm_label=reclassify.confirm_label,
            subject=reclassify.subject,
            cardinality=Cardinality.MANY,
            color=reclassify.color,
            inverse_aggregate="playersession",
            fallback=reclassify.fallback,
            scope=reclassify.scope,
            resolve=reclassify.resolve,
            run=reclassify.run,
            inverse=reclassify.inverse,
            preview=reclassify.preview,
        )


def test_every_act_names_itself_as_the_table_keys_it():
    assert all(name == action.name for name, action in BULK_ACTIONS.items())


def test_making_the_value_declares_it(reclassify):
    """One path, so a declaration cannot reach the table unrefused."""
    name = "session.spare"
    try:
        spare = BulkAction(
            name=name,
            label=reclassify.label,
            title=reclassify.title,
            confirm_label=reclassify.confirm_label,
            subject=reclassify.subject,
            cardinality=Cardinality.ONE,
            color=reclassify.color,
            inverse_aggregate="playersession",
            fallback=reclassify.fallback,
            scope=reclassify.scope,
            resolve=reclassify.resolve,
            run=reclassify.run,
            inverse=reclassify.inverse,
            preview=reclassify.preview,
        )
        assert BULK_ACTIONS[name] is spare
    finally:
        #: The table outlives the test; nothing else takes an act away.
        _TABLE.pop(name, None)


def test_the_table_is_read_and_not_written():
    with pytest.raises(TypeError):
        BULK_ACTIONS["session.reclassify"] = None  # type: ignore[index]


# ── The scope ────────────────────────────────────────────────────────────────


def test_the_scope_leaves_the_bucket_out(
    owned_user, owned_library, game, run, reclassify
):
    """The filter alone cannot say it.

    reviewable_sessions() narrows on the run's kind, and no session
    filter field states one, so a scope built from the filter alone
    would take bucket rows in and refuse them one by one.
    """
    wanted = a_written_session(owned_library, owned_user, run)
    bucket_row = a_bucket_session(owned_library, owned_user, game)

    scoped = set(reclassify.scope(owned_library, review_filter()))

    assert wanted in scoped
    assert bucket_row not in scoped


def test_the_scope_leaves_a_short_session_out(
    owned_user, owned_library, run, reclassify
):
    short = a_written_session(
        owned_library, owned_user, run, duration=timedelta(hours=1)
    )

    assert short not in set(reclassify.scope(owned_library, review_filter()))


def test_a_filter_that_cannot_be_parsed_refuses_the_act(owned_library, reclassify):
    from common.criteria import FilterError

    with pytest.raises(FilterError):
        reclassify.scope(owned_library, "{not json")


# ── The resolve ──────────────────────────────────────────────────────────────


def test_a_reviewable_row_resolves(owned_user, owned_library, run, reclassify):
    session = a_written_session(owned_library, owned_user, run)

    resolution = reclassify.resolve(owned_library, [session.pk])

    assert [row.pk for row in resolution.rows] == [session.pk]
    assert resolution.refused == ()


def test_a_key_no_row_answers_is_lost(owned_library, reclassify):
    resolution = reclassify.resolve(owned_library, [uuid.uuid7()])

    assert resolution.rows == ()
    assert [refused.sentence for refused in resolution.refused] == [NOT_AVAILABLE]
    assert resolution.refused[0].lost


def test_a_short_row_is_refused_and_not_lost(
    owned_user, owned_library, run, reclassify
):
    short = a_written_session(
        owned_library, owned_user, run, duration=timedelta(hours=1)
    )

    resolution = reclassify.resolve(owned_library, [short.pk])

    assert [refused.sentence for refused in resolution.refused] == [UNDER_THRESHOLD]
    assert not resolution.refused[0].lost


def test_a_bucket_row_is_refused(owned_user, owned_library, game, reclassify):
    bucket_row = a_bucket_session(owned_library, owned_user, game)

    resolution = reclassify.resolve(owned_library, [bucket_row.pk])

    assert [refused.sentence for refused in resolution.refused] == [IN_THE_BUCKET]


def test_a_measured_row_is_refused(owned_user, owned_library, game, reclassify):
    run = tracked_run(owned_library, game)
    measured = timed_row(run, STARTED_AT, STARTED_AT + LONG_ENOUGH)

    resolution = reclassify.resolve(owned_library, [measured.pk])

    assert [refused.sentence for refused in resolution.refused] == [NOT_WRITTEN]


def test_a_row_already_recorded_is_refused(owned_user, owned_library, run, reclassify):
    session = a_written_session(owned_library, owned_user, run)
    reclassify.run(owned_user, session, "one-conversion", uuid.uuid7())

    resolution = reclassify.resolve(owned_library, [session.pk])

    assert [refused.sentence for refused in resolution.refused] == [ALREADY_RECORDED]


def test_a_row_live_beside_its_record_is_refused(
    owned_user, owned_library, run, reclassify
):
    """Drift, met at the resolve rather than at a dispatch.

    A live session beside a live record made from it is a state no
    command admits, so the command that meets it answers a defect, and
    a defect ends the whole batch rather than one row.
    """
    session = a_written_session(owned_library, owned_user, run)
    reclassify.run(owned_user, session, "one-conversion", uuid.uuid7())
    #: No command writes this; an audit reports it.
    PlayerSession.objects.filter(pk=session.pk).update(removed_at=None)

    resolution = reclassify.resolve(owned_library, [session.pk])

    assert resolution.rows == ()
    assert [refused.sentence for refused in resolution.refused] == [ALREADY_RECORDED]


def test_another_librarys_row_is_lost(owned_library, reclassify, django_user_model):
    stranger = django_user_model.objects.create_user(username="stranger", password="p")
    game = Game.objects.create(library=stranger.library, name="Celeste")
    theirs = duration_only_row(tracked_run(stranger.library, game), A_DAY, LONG_ENOUGH)

    resolution = reclassify.resolve(owned_library, [theirs.pk])

    assert resolution.rows == ()
    assert resolution.refused[0].lost


# ── The run and its inverse ──────────────────────────────────────────────────


def test_one_key_twice_converts_once(owned_user, owned_library, run, reclassify):
    """The runner keys a row from the token, so a key is the act.

    A chunk that is posted twice acts once only while the run passes
    the key it is given through to the dispatch. A run that minted its
    own key would convert the same session twice.
    """
    session = a_written_session(owned_library, owned_user, run)
    correlation_id = uuid.uuid7()

    reclassify.run(owned_user, session, "one-conversion", correlation_id)
    reclassify.run(owned_user, session, "one-conversion", correlation_id)

    assert HistoricalPlaytime.objects.filter(library=owned_library).count() == 1


def test_the_run_converts_and_the_inverse_returns(
    owned_user, owned_library, run, reclassify
):
    session = a_written_session(owned_library, owned_user, run)
    correlation_id = uuid.uuid7()

    reclassify.run(owned_user, session, "one-conversion", correlation_id)
    session.refresh_from_db()
    assert session.removed_at is not None

    reclassify.inverse(owned_user, session.pk, "undo-one", uuid.uuid7())
    session.refresh_from_db()
    assert session.removed_at is None


# ── The confirmation's rows ──────────────────────────────────────────────────


@pytest.fixture
def presentations() -> Presentations:
    from zoneinfo import ZoneInfo

    from common.date_time_presentation import (
        DEFAULT_DATE_TIME_FORMAT_PROFILE,
        DateTimePresentation,
    )
    from common.duration_presentation import (
        DEFAULT_DURATION_FORMAT_PROFILE,
        DurationPresentation,
    )

    return Presentations(
        dates=DateTimePresentation(
            profile=DEFAULT_DATE_TIME_FORMAT_PROFILE,
            locale="en-us",
            timezone=ZoneInfo("UTC"),
        ),
        durations=DurationPresentation(
            profile=DEFAULT_DURATION_FORMAT_PROFILE,
            locale="en-us",
        ),
    )


def _spare(reclassify: BulkAction, name: str, preview) -> BulkAction:
    return BulkAction(
        name=name,
        label=reclassify.label,
        title=reclassify.title,
        confirm_label=reclassify.confirm_label,
        subject="record",
        cardinality=Cardinality.MANY,
        color=reclassify.color,
        inverse_aggregate="playersession",
        fallback=reclassify.fallback,
        scope=reclassify.scope,
        resolve=reclassify.resolve,
        run=reclassify.run,
        inverse=reclassify.inverse,
        preview=preview,
    )


def test_the_confirmation_renders_the_columns_the_act_states(reclassify, presentations):
    """Any number, and one row apiece: the runner owns neither."""
    from games.views.bulk_pages import ConfirmBatch

    rows = [object(), object()]
    preview = tuple(
        PreviewColumn(f"Fact {number}", lambda row, _, number=number: f"cell {number}")
        for number in range(4)
    )
    name = "session.four_columns"
    try:
        page = ConfirmBatch(
            _spare(reclassify, name, preview),
            rows=rows,
            refused=(),
            hidden=[],
            post_url="/bulk/x/",
            csrf_token="token",
            cancel_url="/",
            sample_cap=50,
            presentations=presentations,
        )
    finally:
        _TABLE.pop(name, None)

    html = str(page)
    assert html.count("data-bulk-sample-row") == len(rows)
    for number in range(4):
        assert f"Fact {number}" in html
        assert html.count(f"cell {number}") == len(rows)


def test_a_confirmation_over_no_rows_names_the_acts_subject(reclassify, presentations):
    from games.views.bulk_pages import ConfirmBatch

    name = "session.no_rows"
    try:
        page = ConfirmBatch(
            _spare(reclassify, name, reclassify.preview),
            rows=[],
            refused=(),
            hidden=[],
            post_url="/bulk/x/",
            csrf_token="token",
            cancel_url="/",
            sample_cap=50,
            presentations=presentations,
        )
    finally:
        _TABLE.pop(name, None)

    assert "None of those records can be changed." in str(page)


def test_the_reclassification_states_its_three_columns(reclassify):
    assert [column.heading for column in reclassify.preview] == [
        "Game",
        "Day",
        "Duration",
    ]
    assert reclassify.preview[-1].align == "right"
