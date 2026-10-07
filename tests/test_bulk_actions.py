"""What a bulk act declares, and what its declaration refuses."""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from django.utils import timezone
from session_rows import duration_only_row, timed_row, tracked_run

from games.bulk_actions import _TABLE, BULK_ACTIONS, BulkAction
from games.bulk_parts import (
    ActTitle,
    EventRows,
    LedgerRows,
    Presentations,
    PreviewColumn,
    RowOutcome,
)
from games.bulk_reclassification import (
    ALREADY_RECORDED,
    IN_THE_BUCKET,
    NOT_AVAILABLE,
    NOT_WRITTEN,
    REVIEW_THRESHOLD_HOURS,
    SHORT_MANY,
    SHORT_ONE,
    convertible_sessions,
    reviewable_sessions,
    short_rows_note,
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
            implies_played=False,
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
    assert reclassify.undo_rows == EventRows(PlayerSession)


def test_a_model_no_event_speaks_about_is_refused():
    with pytest.raises(ValueError, match="'game'"):
        EventRows(Game)


def test_a_ledger_over_a_projection_is_refused():
    with pytest.raises(TypeError, match="projection"):
        LedgerRows(PlayerSession)


def test_a_name_the_table_already_holds_is_refused(reclassify):
    with pytest.raises(ValueError, match="already"):
        BulkAction(
            name="session.reclassify",
            label=reclassify.label,
            title=reclassify.title,
            confirm_label=reclassify.confirm_label,
            subject=reclassify.subject,
            color=reclassify.color,
            undo_rows=reclassify.undo_rows,
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
            color=reclassify.color,
            undo_rows=reclassify.undo_rows,
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


def test_the_review_filter_leaves_a_short_session_out(
    owned_user, owned_library, run, reclassify
):
    """The review filter narrows the scope."""
    short = a_written_session(
        owned_library, owned_user, run, duration=timedelta(hours=1)
    )

    assert short not in set(reclassify.scope(owned_library, review_filter()))


def test_the_scope_takes_a_short_session_the_filter_admits(
    owned_user, owned_library, run, reclassify
):
    """An unnarrowed statement reaches short rows."""
    short = a_written_session(
        owned_library, owned_user, run, duration=timedelta(hours=1)
    )

    assert short in set(reclassify.scope(owned_library, "{}"))


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


def test_a_short_row_is_offered_all_the_same(
    owned_user, owned_library, run, reclassify
):
    """Length never refuses a row."""
    short = a_written_session(
        owned_library, owned_user, run, duration=timedelta(hours=1)
    )

    resolution = reclassify.resolve(owned_library, [short.pk])

    assert [row.pk for row in resolution.rows] == [short.pk]
    assert resolution.refused == ()


def test_a_row_the_base_drops_for_no_named_reason_is_a_defect(
    owned_user, owned_library, run, reclassify, monkeypatch
):
    """An unnamed narrowing fails, never mislabels."""
    import games.bulk_reclassification as reclassification

    base = reclassification.convertible_sessions
    monkeypatch.setattr(
        reclassification,
        "convertible_sessions",
        lambda library: base(library).filter(
            effective_duration__gte=timedelta(hours=REVIEW_THRESHOLD_HOURS)
        ),
    )
    short = a_written_session(
        owned_library, owned_user, run, duration=timedelta(hours=1)
    )

    with pytest.raises(AssertionError, match=str(short.pk)):
        reclassify.resolve(owned_library, [short.pk])


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
    reclassify.run(
        owned_user,
        session,
        choice=None,
        idempotency_key="one-conversion",
        correlation_id=uuid.uuid7(),
    )

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
    reclassify.run(
        owned_user,
        session,
        choice=None,
        idempotency_key="one-conversion",
        correlation_id=uuid.uuid7(),
    )
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

    reclassify.run(
        owned_user,
        session,
        choice=None,
        idempotency_key="one-conversion",
        correlation_id=correlation_id,
    )
    reclassify.run(
        owned_user,
        session,
        choice=None,
        idempotency_key="one-conversion",
        correlation_id=correlation_id,
    )

    assert HistoricalPlaytime.objects.filter(library=owned_library).count() == 1


def test_the_run_converts_and_the_inverse_returns(
    owned_user, owned_library, run, reclassify
):
    session = a_written_session(owned_library, owned_user, run)
    correlation_id = uuid.uuid7()

    reclassify.run(
        owned_user,
        session,
        choice=None,
        idempotency_key="one-conversion",
        correlation_id=correlation_id,
    )
    session.refresh_from_db()
    assert session.removed_at is not None

    reclassify.inverse(
        owned_user,
        session.pk,
        undoes=uuid.uuid7(),
        idempotency_key="undo-one",
        correlation_id=uuid.uuid7(),
    )
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
        color=reclassify.color,
        undo_rows=reclassify.undo_rows,
        fallback=reclassify.fallback,
        scope=reclassify.scope,
        resolve=reclassify.resolve,
        run=reclassify.run,
        inverse=reclassify.inverse,
        preview=preview,
    )


# ── What the act cautions about ──────────────────────────────────────────────


def test_an_act_cautions_about_nothing_by_default(reclassify):
    name = "session.silent_caution"
    try:
        assert _spare(reclassify, name, reclassify.preview).caution is None
    finally:
        _TABLE.pop(name, None)


def test_rows_at_the_threshold_are_worth_no_note(owned_user, owned_library, run):
    rows = [a_written_session(owned_library, owned_user, run)]

    assert short_rows_note(rows) is None


def test_one_short_row_is_noted_in_the_singular(owned_user, owned_library, run):
    short = a_written_session(
        owned_library, owned_user, run, duration=timedelta(hours=1)
    )
    long_enough = a_written_session(
        owned_library, owned_user, run, day=date(2026, 3, 6)
    )

    assert short_rows_note([short, long_enough]) == SHORT_ONE.format(
        hours=REVIEW_THRESHOLD_HOURS
    )


def test_several_short_rows_are_counted(owned_user, owned_library, run):
    """The note counts only short rows."""
    short = [
        a_written_session(
            owned_library,
            owned_user,
            run,
            day=date(2026, 3, day),
            duration=timedelta(hours=hours),
        )
        for day, hours in ((6, 1), (7, 7))
    ]
    long_enough = a_written_session(owned_library, owned_user, run)

    assert short_rows_note([*short, long_enough]) == SHORT_MANY.format(
        count=2, hours=REVIEW_THRESHOLD_HOURS
    )


def test_the_note_counts_exactly_the_rows_the_review_would_not_suggest(
    owned_user, owned_library, run
):
    """Note and review share one threshold."""
    threshold = timedelta(hours=REVIEW_THRESHOLD_HOURS)
    durations = (
        threshold - timedelta(minutes=1),
        threshold,
        threshold + timedelta(minutes=1),
        timedelta(hours=1),
    )
    for offset, duration in enumerate(durations):
        a_written_session(
            owned_library,
            owned_user,
            run,
            day=A_DAY + timedelta(days=offset),
            duration=duration,
        )
    rows = list(convertible_sessions(owned_library))
    unsuggested = len(rows) - reviewable_sessions(owned_library).count()

    assert unsuggested == 2
    assert short_rows_note(rows) == SHORT_MANY.format(
        count=unsuggested, hours=REVIEW_THRESHOLD_HOURS
    )


# ── The title the count picks ────────────────────────────────────────────────


def test_a_title_answers_its_singular_at_exactly_one():
    title = ActTitle(one="Remove this session", many="Remove {count} sessions")

    assert title.for_count(1) == "Remove this session"
    assert title.for_count(0) == "Remove 0 sessions"
    assert title.for_count(2) == "Remove 2 sessions"
    assert title.for_count(None) == "Remove these sessions"


@pytest.mark.parametrize(
    "one,many",
    [("", "Remove {count} sessions"), ("Remove this session", "")],
)
def test_a_title_stating_half_of_itself_is_refused(one, many):
    """At the declaration, so the next act states both or fails at import."""
    with pytest.raises(ValueError, match="states both"):
        ActTitle(one=one, many=many)


#: A preview that reads nothing off a row, so a heading case needs no rows.
_NAMELESS: tuple[PreviewColumn[PlayerSession], ...] = (
    PreviewColumn("Row", lambda row, _: "a row"),
)


def test_the_confirmation_heads_one_row_in_the_singular(reclassify, presentations):
    from games.views.bulk_pages import ConfirmBatch

    name = "session.one_row_title"
    try:
        page = str(
            ConfirmBatch(
                _spare(reclassify, name, _NAMELESS),
                rows=[object()],
                refused=(),
                hidden=[],
                post_url="/bulk/x/",
                csrf_token="token",
                cancel_url="/",
                sample_cap=50,
                presentations=presentations,
            )
        )
    finally:
        _TABLE.pop(name, None)

    assert reclassify.title.one in page
    assert "Record 1 session" not in page


def test_the_confirmation_heads_three_rows_in_the_plural(reclassify, presentations):
    from games.views.bulk_pages import ConfirmBatch

    name = "session.three_row_title"
    try:
        page = str(
            ConfirmBatch(
                _spare(reclassify, name, _NAMELESS),
                rows=[object(), object(), object()],
                refused=(),
                hidden=[],
                post_url="/bulk/x/",
                csrf_token="token",
                cancel_url="/",
                sample_cap=50,
                presentations=presentations,
            )
        )
    finally:
        _TABLE.pop(name, None)

    assert reclassify.title.for_count(3) in page


@pytest.mark.parametrize(
    "one,many",
    [
        ("Remove this session", "Remove these sessions"),
        ("Remove this session", "Remove {count} of {count} sessions"),
        ("Remove {count} session", "Remove {count} sessions"),
    ],
)
def test_a_title_that_does_not_count_once_is_refused(one, many):
    """Only `many` states the count, and once."""
    from games.bulk_parts import ActTitle

    with pytest.raises(ValueError, match="states {count} once"):
        ActTitle(one=one, many=many)


def test_every_declared_act_states_both_halves():
    for action in BULK_ACTIONS.values():
        assert action.title.one
        assert action.title.many
        assert "{count}" in action.title.many


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


def _reclassify_confirmation(
    reclassify: BulkAction, rows, presentations, *, sample_cap: int = 50
) -> str:
    """The confirmation page over these rows."""
    from games.views.bulk_pages import ConfirmBatch

    return str(
        ConfirmBatch(
            reclassify,
            rows=rows,
            refused=(),
            hidden=[],
            post_url="/bulk/session.reclassify/",
            csrf_token="token",
            cancel_url="/",
            sample_cap=sample_cap,
            presentations=presentations,
        )
    )


def test_the_confirmation_says_the_caution_over_the_rows(
    owned_user, owned_library, run, reclassify, presentations
):
    """Note above the table; press stays."""
    short = a_written_session(
        owned_library, owned_user, run, duration=timedelta(hours=1)
    )

    page = _reclassify_confirmation(reclassify, [short], presentations)

    said = SHORT_ONE.format(hours=REVIEW_THRESHOLD_HOURS)
    assert said in page
    assert page.index(said) < page.index("<table")
    assert reclassify.confirm_label in page


def test_the_caution_counts_rows_past_the_sample(
    owned_user, owned_library, run, reclassify, presentations
):
    """The note counts rows past the sample."""
    short = [
        a_written_session(
            owned_library,
            owned_user,
            run,
            day=A_DAY + timedelta(days=offset),
            duration=timedelta(hours=1),
        )
        for offset in range(2)
    ]

    page = _reclassify_confirmation(reclassify, short, presentations, sample_cap=1)

    assert SHORT_MANY.format(count=2, hours=REVIEW_THRESHOLD_HOURS) in page


def test_a_confirmation_over_long_rows_says_no_caution(
    owned_user, owned_library, run, reclassify, presentations
):
    long_enough = a_written_session(owned_library, owned_user, run)

    page = _reclassify_confirmation(reclassify, [long_enough], presentations)

    assert f"shorter than {REVIEW_THRESHOLD_HOURS} hours" not in page


def test_the_reclassification_states_its_three_columns(reclassify):
    assert [column.heading for column in reclassify.preview] == [
        "Game",
        "Day",
        "Duration",
    ]
    assert reclassify.preview[-1].align == "right"


def test_an_act_whose_run_takes_a_fact_by_position_is_refused(reclassify):
    """Two of the three facts are text.

    Named, they cannot be given in each other's place;
    positional, no check refuses it -- and a protocol does
    not constrain an implementation's parameter kinds, so
    the declaration is where this can be said.
    """

    def takes_it_by_position(actor, row, choice, idempotency_key, correlation_id):
        return RowOutcome.MOVED

    with pytest.raises(ValueError, match="by position"):
        BulkAction(
            name="session.positional",
            label=reclassify.label,
            title=reclassify.title,
            confirm_label=reclassify.confirm_label,
            subject=reclassify.subject,
            color=reclassify.color,
            undo_rows=reclassify.undo_rows,
            fallback=reclassify.fallback,
            scope=reclassify.scope,
            resolve=reclassify.resolve,
            run=takes_it_by_position,
            inverse=reclassify.inverse,
            preview=reclassify.preview,
        )


def test_an_inverse_that_takes_no_batch_is_refused(reclassify):
    """The inverse states the batch it undoes."""

    def takes_no_batch(actor, row_id, *, idempotency_key, correlation_id):
        return RowOutcome.MOVED

    with pytest.raises(ValueError, match="takes no undoes"):
        BulkAction(
            name="session.batchless",
            label=reclassify.label,
            title=reclassify.title,
            confirm_label=reclassify.confirm_label,
            subject=reclassify.subject,
            color=reclassify.color,
            undo_rows=reclassify.undo_rows,
            fallback=reclassify.fallback,
            scope=reclassify.scope,
            resolve=reclassify.resolve,
            run=reclassify.run,
            inverse=takes_no_batch,
            preview=reclassify.preview,
        )
