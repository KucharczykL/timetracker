"""The three Remove acts: what they offer, and what the command refuses."""

import html as html_module
import json
import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.http import Http404
from django.urls import reverse
from session_rows import duration_only_row, tracked_run

from common.criteria import FilterError
from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DateTimePresentation,
)
from common.duration_presentation import (
    DEFAULT_DURATION_FORMAT_PROFILE,
    DurationPresentation,
)
from games.bulk_actions import BULK_ACTIONS, Presentations, RowOutcome
from games.bulk_removal import (
    RECORD_GONE,
    RUN_GONE,
)
from games.bulk_sessions import SESSION_GONE
from games.commands.historical_playtime import HistoricalPlaytimeStatement
from games.commands.playthrough import ActStatement
from games.commands.session_reclassification import statement_from_session
from games.models import (
    Game,
    HistoricalPlaytime,
    HistoricalPlaytimeProvenance,
    PlayerSession,
    Playthrough,
    PlaythroughKind,
)
from games.writes.answers import CommandFailed
from games.writes.historical_playtime import record_historical_playtime
from games.writes.playergame import new_correlation_id, track_game
from games.writes.playersession import reclassify_session
from games.writes.playthrough import RunDraft, record_run
from timetracker.temporal import TemporalValue

pytestmark = [pytest.mark.untracked_games, pytest.mark.django_db(transaction=True)]

A_DAY = date(2026, 3, 5)
ANOTHER_DAY = date(2026, 4, 9)
AN_HOUR = timedelta(hours=1)


@pytest.fixture(autouse=True)
def prague_calendar(owned_user, set_user_setting):
    set_user_setting(owned_user, "DISPLAY_TIME_ZONE", "Europe/Prague")


@pytest.fixture
def presentations() -> Presentations:
    return Presentations(
        dates=DateTimePresentation(
            profile=DEFAULT_DATE_TIME_FORMAT_PROFILE,
            locale="en-us",
            timezone=ZoneInfo("UTC"),
        ),
        durations=DurationPresentation(
            profile=DEFAULT_DURATION_FORMAT_PROFILE, locale="en-us"
        ),
    )


@pytest.fixture
def game(owned_library):
    return Game.objects.create(library=owned_library, name="Outer Wilds")


@pytest.fixture
def other_game(owned_library):
    return Game.objects.create(library=owned_library, name="Hades")


@pytest.fixture
def remove_session_action():
    return BULK_ACTIONS["session.remove"]


@pytest.fixture
def remove_run_action():
    return BULK_ACTIONS["playthrough.remove"]


@pytest.fixture
def remove_record_action():
    return BULK_ACTIONS["historicalplaytime.remove"]


def a_session(library, game, *, day=A_DAY, note="") -> PlayerSession:
    return duration_only_row(tracked_run(library, game), day, AN_HOUR, note=note)


def a_record(actor, library, game, *, when="2005", hours=100) -> HistoricalPlaytime:
    run = tracked_run(library, game)
    record_id = record_historical_playtime(
        actor,
        HistoricalPlaytimeStatement(
            duration=timedelta(hours=hours),
            when=when,
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


def _one_run(actor, game, started: date) -> None:
    record_run(
        actor,
        game,
        RunDraft(
            started=ActStatement(TemporalValue.from_day(started)),
            completed=ActStatement(None),
            note="",
        ),
        correlation_id=new_correlation_id(),
    )


def two_runs(actor, game) -> tuple[Playthrough, Playthrough]:
    """The run the game was born with, and a second.

    The first statement is adopted by the born run, so a second
    genuine row needs a second statement.
    """
    _one_run(actor, game, A_DAY)
    _one_run(actor, game, ANOTHER_DAY)
    first, second = Playthrough.objects.filter(
        player_game__game=game, kind=PlaythroughKind.ORDINARY
    ).order_by("created_at", "pk")
    return first, second


def narrowing(**criterion) -> str:
    return json.dumps(criterion)


# ── Scope ────────────────────────────────────────────────────────────────────


def test_the_session_scope_narrows_by_the_statements_filter(
    owned_library, game, other_game, remove_session_action
):
    wanted = a_session(owned_library, game, note="keep")
    spare = a_session(owned_library, other_game)

    scoped = remove_session_action.scope(
        owned_library, narrowing(note={"value": "keep", "modifier": "INCLUDES"})
    )

    assert set(scoped.values_list("pk", flat=True)) == {wanted.pk}
    assert set(
        remove_session_action.scope(owned_library, "").values_list("pk", flat=True)
    ) == {wanted.pk, spare.pk}


def test_the_session_scope_states_the_lists_own_read(
    owned_library, game, remove_session_action
):
    """A removed row is no act's row, filter or no filter."""
    live = a_session(owned_library, game)
    gone = a_session(owned_library, game, day=ANOTHER_DAY)
    PlayerSession.objects.filter(pk=gone.pk).update(removed_at=datetime.now(tz=UTC))

    scoped = remove_session_action.scope(owned_library, "")

    assert set(scoped.values_list("pk", flat=True)) == {live.pk}


def test_the_run_scope_compiles_a_statement_naming_the_condition(
    owned_user, owned_library, game, remove_run_action
):
    """`activity` is a quick facet of this mode, and no column."""
    track_game(owned_user, game, correlation_id=new_correlation_id())

    scoped = remove_run_action.scope(
        owned_library,
        narrowing(activity={"value": ["never_played"], "modifier": "INCLUDES"}),
    )

    assert list(scoped.values_list("pk", flat=True)) == [
        Playthrough.objects.get(player_game__game=game).pk
    ]


def test_the_record_scope_narrows_by_the_statements_filter(
    owned_user, owned_library, game, other_game, remove_record_action
):
    wanted = a_record(owned_user, owned_library, game, hours=100)
    a_record(owned_user, owned_library, other_game, hours=5)

    scoped = remove_record_action.scope(
        owned_library,
        narrowing(duration_hours={"value": 50, "modifier": "GREATER_THAN"}),
    )

    assert set(scoped.values_list("pk", flat=True)) == {wanted.pk}


@pytest.mark.parametrize(
    "name", ["session.remove", "playthrough.remove", "historicalplaytime.remove"]
)
def test_a_filter_no_act_can_read_is_refused_rather_than_dropped(name, owned_library):
    """Widening the act to the whole base is the one thing a drop does."""
    action = BULK_ACTIONS[name]

    with pytest.raises(FilterError):
        action.scope(owned_library, json.dumps({"no_such_field": {"value": 1}}))


# ── Resolve ──────────────────────────────────────────────────────────────────


def test_a_session_key_of_another_library_comes_out_lost(
    owned_library, game, django_user_model, remove_session_action
):
    stranger = django_user_model.objects.create_user("stranger", password="secret123")
    theirs = Game.objects.create(library=stranger.library, name="Celeste")
    foreign = a_session(stranger.library, theirs)
    mine = a_session(owned_library, game)

    resolution = remove_session_action.resolve(owned_library, [mine.pk, foreign.pk])

    assert [row.pk for row in resolution.rows] == [mine.pk]
    assert [(entry.key, entry.lost) for entry in resolution.refused] == [
        (str(foreign.pk), True)
    ]
    assert resolution.refused[0].sentence == SESSION_GONE


def test_a_run_key_that_is_gone_comes_out_lost(
    owned_user, owned_library, game, remove_run_action
):
    track_game(owned_user, game, correlation_id=new_correlation_id())
    run = Playthrough.objects.get(player_game__game=game)

    resolution = remove_run_action.resolve(owned_library, [run.pk, uuid.uuid7()])

    assert [row.pk for row in resolution.rows] == [run.pk]
    assert resolution.refused[0].sentence == RUN_GONE


def test_a_record_key_that_is_gone_comes_out_lost(
    owned_user, owned_library, game, remove_record_action
):
    record = a_record(owned_user, owned_library, game)

    resolution = remove_record_action.resolve(owned_library, [record.pk, uuid.uuid7()])

    assert [row.pk for row in resolution.rows] == [record.pk]
    assert resolution.refused[0].sentence == RECORD_GONE


def test_a_runs_number_is_counted_across_the_game_not_the_selection(
    owned_user, owned_library, game, remove_run_action, presentations
):
    """A partition narrowed to one tick calls every run the first."""
    first, second = two_runs(owned_user, game)

    resolution = remove_run_action.resolve(owned_library, [second.pk])

    stated = remove_run_action.preview[0].cell(resolution.rows[0], presentations)
    assert first.pk != second.pk
    assert stated == "Playthrough 2"


# ── Run and inverse ──────────────────────────────────────────────────────────


def test_removing_a_session_marks_it_and_restoring_clears_the_mark(
    owned_user, owned_library, game, remove_session_action
):
    session = a_session(owned_library, game)

    moved = remove_session_action.run(
        owned_user,
        session,
        choice=None,
        idempotency_key="remove-one",
        correlation_id=uuid.uuid7(),
    )

    assert moved is RowOutcome.MOVED
    session.refresh_from_db()
    assert session.removed_at is not None

    back = remove_session_action.inverse(
        owned_user,
        session.pk,
        undoes=uuid.uuid7(),
        idempotency_key="restore-one",
        correlation_id=uuid.uuid7(),
    )

    assert back is RowOutcome.MOVED
    session.refresh_from_db()
    assert session.removed_at is None


def test_a_row_already_removed_answers_unchanged(
    owned_user, owned_library, game, remove_session_action
):
    session = a_session(owned_library, game)
    remove_session_action.run(
        owned_user,
        session,
        choice=None,
        idempotency_key="remove-one",
        correlation_id=uuid.uuid7(),
    )

    again = remove_session_action.run(
        owned_user,
        session,
        choice=None,
        idempotency_key="remove-again",
        correlation_id=uuid.uuid7(),
    )

    assert again is RowOutcome.UNCHANGED


def test_the_last_live_ordinary_run_is_refused_while_its_sibling_is_removed(
    owned_user, owned_library, game, remove_run_action
):
    """The command's rule, one row, and the batch goes on."""
    first, second = two_runs(owned_user, game)

    assert (
        remove_run_action.run(
            owned_user,
            second,
            choice=None,
            idempotency_key="remove-second",
            correlation_id=uuid.uuid7(),
        )
        is RowOutcome.MOVED
    )

    with pytest.raises(CommandFailed) as refusal:
        remove_run_action.run(
            owned_user,
            first,
            choice=None,
            idempotency_key="remove-first",
            correlation_id=uuid.uuid7(),
        )

    assert refusal.value.status_code == 409
    assert "only playthrough" in refusal.value.message
    first.refresh_from_db()
    assert first.removed_at is None


def test_restoring_a_session_a_live_record_was_made_from_is_refused(
    owned_user, owned_library, game, remove_session_action
):
    """#1098's rule reaches the Undo as one row's sentence."""
    session = duration_only_row(
        tracked_run(owned_library, game), A_DAY, timedelta(hours=9)
    )
    reclassify_session(
        owned_user,
        session,
        statement_from_session(session),
        idempotency_key="one-conversion",
        correlation_id=uuid.uuid7(),
    )

    with pytest.raises(CommandFailed) as refusal:
        remove_session_action.inverse(
            owned_user,
            session.pk,
            undoes=uuid.uuid7(),
            idempotency_key="restore-one",
            correlation_id=uuid.uuid7(),
        )

    assert refusal.value.status_code == 409


def test_removing_a_record_and_putting_it_back(
    owned_user, owned_library, game, remove_record_action
):
    record = a_record(owned_user, owned_library, game)

    remove_record_action.run(
        owned_user,
        record,
        choice=None,
        idempotency_key="remove-one",
        correlation_id=uuid.uuid7(),
    )
    record.refresh_from_db()
    assert record.removed_at is not None

    remove_record_action.inverse(
        owned_user,
        record.pk,
        undoes=uuid.uuid7(),
        idempotency_key="restore-one",
        correlation_id=uuid.uuid7(),
    )
    record.refresh_from_db()
    assert record.removed_at is None


# ── The declaration ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name", ["session.remove", "playthrough.remove", "historicalplaytime.remove"]
)
def test_each_acts_undo_reads_the_rows_its_act_wrote(
    owned_user, owned_library, game, name
):
    """The declaration against the stream, not against a copy of itself.

    `__post_init__` already refuses an aggregate no event speaks
    about; what is left to prove is that the aggregate named is the
    one the removal appends under.
    """
    from games.reads.events import batch_aggregate_ids

    action = BULK_ACTIONS[name]
    row = _a_row_for(name, owned_user, owned_library, game)
    correlation_id = uuid.uuid7()

    action.run(
        owned_user,
        row,
        choice=None,
        idempotency_key=str(uuid.uuid7()),
        correlation_id=correlation_id,
    )

    assert batch_aggregate_ids(
        owned_library, correlation_id, action.inverse_aggregate
    ) == [row.pk]


# ── Through the route ────────────────────────────────────────────────────────


def _act_url(name: str) -> str:
    return reverse("games:run_bulk_action", args=[name])


@pytest.fixture
def client_in(client, owned_user):
    client.force_login(owned_user)
    return client


def _statement(*keys) -> str:
    return json.dumps({"mode": "some", "keys": sorted(str(key) for key in keys)})


def _hidden(html: str) -> dict[str, str]:
    """The fields the confirmation would submit."""
    fields: dict[str, str] = {}
    for name in ("submission", "progress"):
        marker = f'name="{name}" value="'
        if marker in html:
            start = html.index(marker) + len(marker)
            fields[name] = html_module.unescape(html[start : html.index('"', start)])
    return fields


@pytest.mark.parametrize(
    "name, headings",
    [
        ("session.remove", ("Game", "Day", "Duration")),
        ("playthrough.remove", ("Playthrough", "Game", "Started", "Completed")),
        ("historicalplaytime.remove", ("Game", "When", "Duration")),
    ],
)
def test_each_acts_confirmation_states_its_own_columns(
    client_in, owned_user, owned_library, game, name, headings
):
    """The cells run, which is the one thing a declaration cannot prove.

    Nothing reads a preview until a person stands on the confirmation,
    so a wrong path there is a defect page between the press and the
    write.
    """
    row = _a_row_for(name, owned_user, owned_library, game)

    html = client_in.post(
        _act_url(name), {"selection": _statement(row.pk)}
    ).content.decode()

    for heading in headings:
        assert heading in html
    assert html.count("data-bulk-sample-row") == 1


@pytest.mark.parametrize(
    "name", ["session.remove", "playthrough.remove", "historicalplaytime.remove"]
)
def test_each_act_removes_the_row_it_confirmed(
    client_in, owned_user, owned_library, game, name
):
    row = _a_row_for(name, owned_user, owned_library, game)
    confirmation = client_in.post(_act_url(name), {"selection": _statement(row.pk)})

    client_in.post(
        _act_url(name),
        {
            "selection": _statement(row.pk),
            **_hidden(confirmation.content.decode()),
        },
    )

    row.refresh_from_db()
    assert row.removed_at is not None


def _a_row_for(name: str, owned_user, owned_library, game):
    """One row of the kind the named act takes."""
    if name == "session.remove":
        return a_session(owned_library, game)
    if name == "historicalplaytime.remove":
        return a_record(owned_user, owned_library, game)
    #: A second run, so its game keeps one and the act is not refused.
    return two_runs(owned_user, game)[1]


def test_an_endpoint_no_act_stated_reads_as_a_dash(
    owned_user, owned_library, game, remove_run_action, presentations
):
    """The dash the list writes, so both screens read alike.

    An act with no day is a stated endpoint of unknown day, which
    reads `Unknown`; the dash is for the act that never happened.
    """
    _one_run(owned_user, game, A_DAY)
    record_run(
        owned_user,
        game,
        RunDraft(
            started=ActStatement(TemporalValue.from_day(ANOTHER_DAY)),
            #: Never finished, so no act to date.
            completed=None,
            note="",
        ),
        correlation_id=new_correlation_id(),
    )
    second = Playthrough.objects.filter(
        player_game__game=game, kind=PlaythroughKind.ORDINARY
    ).order_by("created_at", "pk")[1]
    resolution = remove_run_action.resolve(owned_library, [second.pk])

    completed = remove_run_action.preview[3].cell(resolution.rows[0], presentations)

    assert completed == "-"


def test_a_removed_run_is_put_back_by_its_inverse(
    owned_user, owned_library, game, remove_run_action
):
    """The one inverse that reads a run through a plain manager."""
    _, second = two_runs(owned_user, game)
    remove_run_action.run(
        owned_user,
        second,
        choice=None,
        idempotency_key="remove-one",
        correlation_id=uuid.uuid7(),
    )

    back = remove_run_action.inverse(
        owned_user,
        second.pk,
        undoes=uuid.uuid7(),
        idempotency_key="restore-one",
        correlation_id=uuid.uuid7(),
    )

    assert back is RowOutcome.MOVED
    second.refresh_from_db()
    assert second.removed_at is None


def test_an_inverse_that_finds_no_row_is_not_found(
    owned_user, owned_library, game, remove_run_action
):
    """`Http404`, which the runner catches, not the manager's own.

    A `DoesNotExist` is neither of the two the batch catches, so it
    would leave through the view and the rows the batch never reached
    would go unnamed in the log.
    """
    with pytest.raises(Http404):
        remove_run_action.inverse(
            owned_user,
            uuid.uuid7(),
            undoes=uuid.uuid7(),
            idempotency_key="restore-one",
            correlation_id=uuid.uuid7(),
        )


def test_a_statement_naming_a_related_entity_narrows_the_act(
    owned_library, game, other_game, remove_session_action
):
    """What the query context buys: a relation clause compiles.

    Without it the clause refuses outright, so the act would answer a
    defect where the list the person read answered rows.
    """
    wanted = a_session(owned_library, game)
    a_session(owned_library, other_game)

    scoped = remove_session_action.scope(
        owned_library,
        narrowing(game_filter={"name": {"value": game.name, "modifier": "EQUALS"}}),
    )

    assert set(scoped.values_list("pk", flat=True)) == {wanted.pk}


def test_a_filter_naming_no_criteria_is_refused(owned_library, remove_session_action):
    """`null` parses, states nothing, and must not read the whole base."""
    with pytest.raises(FilterError):
        remove_session_action.scope(owned_library, "null")
