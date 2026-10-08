"""A session or a record names the Release it was played on."""

import uuid
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.http import QueryDict
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from entries import (
    end_entry_access,
    prerelease_release,
    record_entry,
    remove_entry,
    second_release,
)
from graphs import default_graph
from historical_playtime_posts import posted_record
from historical_playtime_rows import record_row
from session_rows import duration_only_row

from common.components.unset_field import unset_input_name
from common.criteria import BoolCriterion
from games.bulk_parts import Control
from games.bulk_session_edit import (
    EditStatement,
    _release_of,
    edit_back,
    edit_one,
    offer_edit,
    settle_edit,
)
from games.bulk_sessions import labelled_session_resolution
from games.commands.historical_playtime import (
    HistoricalPlaytimeStatement,
    RecordHistoricalPlaytime,
    RestateHistoricalPlaytime,
)
from games.commands.playersession import (
    CreateSession,
    DescribeSession,
    MoveSessionToPlaythrough,
    RemoveSession,
    StatedRelease,
    TimedTiming,
)
from games.commands.playthrough import CreatePlaythrough, MovePlaythroughToGame
from games.commands.scope import (
    NO_COPY_OF_RELEASE,
    RELEASE_OF_ANOTHER_GAME,
    RELEASE_REMOVED,
)
from games.commands.session_reclassification import (
    ReclassifySessionAsHistoricalPlaytime,
    statement_from_session,
)
from games.end_ways import EndWay
from games.events.dispatch import (
    CommandOutcome,
    CommandRejected,
    RowNotHeld,
    RowUnreadable,
    dispatch,
)
from games.filters import (
    HistoricalPlaytimeFilter,
    PlayerSessionFilter,
    filter_query_context_for_library,
)
from games.forms import held_release_options
from games.models import (
    Game,
    HistoricalPlaytime,
    HistoricalPlaytimeProvenance,
    LibraryEvent,
    ListColumnChoice,
    Platform,
    PlayerSession,
    Playthrough,
    Release,
)
from games.reads.calendar import calendar_day_zone
from games.reads.historical_playtime_records import library_records
from games.reads.player_sessions import library_sessions
from games.reads.releases import ended_copy_ways, release_label
from games.reads.session_organization import organization_counts
from games.removal import remove
from games.views.bulk import CHOICE_FIELD
from games.views.playthrough_writes import moved_sentence
from games.writes.answers import CommandFailed
from games.writes.playersession import SessionDraft, clone_session, restate_session
from games.writes.playthrough import RunDraft, restate_run
from timetracker.temporal import TemporalValue

pytestmark = [pytest.mark.untracked_games, pytest.mark.django_db(transaction=True)]

START = datetime(2026, 1, 1, 12, tzinfo=UTC)


@pytest.fixture
def graph(owned_library):
    return default_graph(Game(name="Hades", library=owned_library), owned_library)


@pytest.fixture
def other_graph(owned_library):
    return default_graph(Game(name="Celeste", library=owned_library), owned_library)


@pytest.fixture
def entry(owned_library, graph):
    return record_entry(owned_library, graph.release)


@pytest.fixture
def run(entry, graph) -> Playthrough:
    return Playthrough.objects.get(player_game__game=graph.game)


@pytest.fixture
def other_run(owned_library, other_graph) -> Playthrough:
    record_entry(owned_library, other_graph.release)
    return Playthrough.objects.get(player_game__game=other_graph.game)


def state(library, command) -> CommandOutcome:
    return dispatch(
        command,
        actor=library.user,
        library=library,
        idempotency_key=str(uuid.uuid7()),
    ).outcome


def refused(library, command) -> CommandRejected:
    with pytest.raises(CommandRejected) as refusal:
        state(library, command)
    return refusal.value


def a_session(library, run, release=None) -> PlayerSession:
    state(
        library,
        CreateSession(
            playthrough_id=run.pk,
            timing=TimedTiming(
                started_at=START,
                ended_at=START + timedelta(hours=1),
                day_zone=calendar_day_zone(library).key,
            ),
            release_id=None if release is None else release.pk,
            implies_played=False,
        ),
    )
    return PlayerSession.objects.latest("created_at")


def created_session(run, release) -> CreateSession:
    return CreateSession(
        playthrough_id=run.pk,
        timing=TimedTiming(
            started_at=START, day_zone=calendar_day_zone(run.library).key
        ),
        release_id=release.pk,
        implies_played=False,
    )


def a_statement(run, release=None) -> HistoricalPlaytimeStatement:
    return HistoricalPlaytimeStatement(
        duration=timedelta(hours=10),
        when="2005",
        provenance=HistoricalPlaytimeProvenance.ESTIMATED,
        playthrough_ids=(run.pk,),
        device_id=None,
        emulated=False,
        note="",
        release_id=None if release is None else release.pk,
    )


def latest_types(count: int) -> list[str]:
    events = LibraryEvent.objects.order_by("-sequence")[:count]
    return [event.event_type for event in reversed(events)]


def test_a_session_names_a_release_of_a_held_copy(owned_library, graph, run):
    session = a_session(owned_library, run, graph.release)

    assert session.release_id == graph.release.pk
    created = LibraryEvent.objects.get(event_type="library.playersession.created")
    assert created.payload["release"]["kind"] == "catalog.release"


def test_an_ended_copy_still_holds_its_release(owned_library, graph, entry, run):
    end_entry_access(entry)

    assert a_session(owned_library, run, graph.release).release_id == graph.release.pk


def test_a_release_with_no_copy_is_refused(owned_library, run, entry):
    uncopied = second_release(owned_library, entry.release)

    refusal = refused(owned_library, created_session(run, uncopied))

    assert refusal.sentence == NO_COPY_OF_RELEASE


def test_a_removed_copy_holds_no_release(owned_library, graph, entry, run):
    remove_entry(entry)

    refusal = refused(owned_library, created_session(run, graph.release))

    assert refusal.sentence == NO_COPY_OF_RELEASE


def test_a_removed_release_is_refused_first(owned_library, graph, run):
    remove(graph.release)

    refusal = refused(owned_library, created_session(run, graph.release))

    assert refusal.sentence == RELEASE_REMOVED


def test_another_games_release_is_refused(owned_library, run, other_graph, other_run):
    refusal = refused(owned_library, created_session(run, other_graph.release))

    assert refusal.sentence == RELEASE_OF_ANOTHER_GAME


def test_a_release_the_library_cannot_see_is_absent(
    owned_library, run, django_user_model
):
    stranger = django_user_model.objects.create_user(username="stranger").library
    theirs = default_graph(Game(name="Tunic", library=stranger), stranger)

    with pytest.raises(RowNotHeld):
        state(owned_library, created_session(run, theirs.release))


def test_a_description_states_clears_and_repeats_a_release(owned_library, graph, run):
    session = a_session(owned_library, run)
    held = StatedRelease(graph.release.pk)

    state(owned_library, DescribeSession(session.pk, release=held))
    session.refresh_from_db()
    assert session.release_id == graph.release.pk

    assert state(owned_library, DescribeSession(session.pk, release=held)) is (
        CommandOutcome.UNCHANGED
    )

    state(owned_library, DescribeSession(session.pk, release=StatedRelease(None)))
    session.refresh_from_db()
    assert session.release_id is None


def test_a_description_keeps_a_held_release_whose_copy_is_gone(
    owned_library, graph, entry, run
):
    session = a_session(owned_library, run, graph.release)
    remove_entry(entry)

    state(owned_library, DescribeSession(session.pk, note="kept"))

    session.refresh_from_db()
    assert session.release_id == graph.release.pk
    assert session.note == "kept"


def test_a_description_states_at_least_one_fact():
    with pytest.raises(CommandRejected):
        DescribeSession(uuid.uuid7())


def test_a_move_to_another_game_clears_the_release(
    owned_library, graph, run, other_run
):
    session = a_session(owned_library, run, graph.release)

    state(
        owned_library,
        MoveSessionToPlaythrough(session_id=session.pk, playthrough_id=other_run.pk),
    )

    session.refresh_from_db()
    assert session.release_id is None
    assert latest_types(2) == [
        "library.playersession.release_changed",
        "library.playersession.moved",
    ]


def test_a_move_within_the_game_keeps_the_release(owned_library, graph, run, entry):
    session = a_session(owned_library, run, graph.release)
    state(
        owned_library,
        CreatePlaythrough(
            game_id=graph.game.pk, implies_played=False, implies_completed=False
        ),
    )
    sibling = Playthrough.objects.exclude(pk=run.pk).get(player_game=run.player_game)

    state(
        owned_library,
        MoveSessionToPlaythrough(session_id=session.pk, playthrough_id=sibling.pk),
    )

    session.refresh_from_db()
    assert session.release_id == graph.release.pk


def test_a_record_names_a_release(owned_library, graph, run):
    state(owned_library, RecordHistoricalPlaytime(a_statement(run, graph.release)))

    assert HistoricalPlaytime.objects.get().release_id == graph.release.pk


def test_a_record_refuses_another_games_release(
    owned_library, run, other_graph, other_run
):
    refusal = refused(
        owned_library, RecordHistoricalPlaytime(a_statement(run, other_graph.release))
    )

    assert refusal.sentence == RELEASE_OF_ANOTHER_GAME


def test_a_restatement_of_the_release_alone_is_a_change(owned_library, graph, run):
    state(owned_library, RecordHistoricalPlaytime(a_statement(run)))
    record = HistoricalPlaytime.objects.get()

    outcome = state(
        owned_library,
        RestateHistoricalPlaytime(record.pk, a_statement(run, graph.release)),
    )

    assert outcome is CommandOutcome.APPENDED
    record.refresh_from_db()
    assert record.release_id == graph.release.pk


def test_a_restatement_keeps_a_held_release_whose_copy_is_gone(
    owned_library, graph, entry, run
):
    state(owned_library, RecordHistoricalPlaytime(a_statement(run, graph.release)))
    record = HistoricalPlaytime.objects.get()
    remove_entry(entry)

    restated = replace(a_statement(run, graph.release), note="kept")
    state(owned_library, RestateHistoricalPlaytime(record.pk, restated))

    record.refresh_from_db()
    assert (record.note, record.release_id) == ("kept", graph.release.pk)


def test_a_restatement_onto_another_game_cannot_keep_the_release(
    owned_library, graph, run, other_run
):
    state(owned_library, RecordHistoricalPlaytime(a_statement(run, graph.release)))
    record = HistoricalPlaytime.objects.get()

    refusal = refused(
        owned_library,
        RestateHistoricalPlaytime(record.pk, a_statement(other_run, graph.release)),
    )

    assert refusal.sentence == RELEASE_OF_ANOTHER_GAME


def test_a_reclassification_carries_the_sessions_release(
    owned_library, graph, entry, run
):
    session = a_session(owned_library, run, graph.release)
    remove_entry(entry)

    state(
        owned_library,
        ReclassifySessionAsHistoricalPlaytime(
            session.pk, statement_from_session(session)
        ),
    )

    assert HistoricalPlaytime.objects.get().release_id == graph.release.pk


def test_a_run_moved_to_another_game_clears_every_release(
    owned_library, graph, run, other_graph, other_run
):
    live = a_session(owned_library, run, graph.release)
    gone = a_session(owned_library, run, graph.release)
    bare = a_session(owned_library, run)
    state(owned_library, RemoveSession(gone.pk))
    state(owned_library, RecordHistoricalPlaytime(a_statement(run, graph.release)))

    state(
        owned_library,
        MovePlaythroughToGame(playthrough_id=run.pk, game_id=other_graph.game.pk),
    )

    released = PlayerSession.objects.filter(release__isnull=False)
    assert not released.exists()
    assert HistoricalPlaytime.objects.get().release_id is None
    cleared = LibraryEvent.objects.filter(
        event_type="library.playersession.release_changed"
    )
    assert {event.aggregate_id for event in cleared} == {live.pk, gone.pk}
    assert bare.pk not in {event.aggregate_id for event in cleared}
    moved = LibraryEvent.objects.get(event_type="library.historicalplaytime.moved")
    assert moved.payload["release"] is None


def a_draft(run, release=None, **changes) -> SessionDraft:
    return SessionDraft(
        playthrough_id=run.pk,
        timing=TimedTiming(
            started_at=START,
            ended_at=START + timedelta(hours=1),
            day_zone=calendar_day_zone(run.library).key,
        ),
        device_id=None,
        note="",
        emulated=False,
        release_id=None if release is None else release.pk,
    )._replace(**changes)


def test_an_edit_moving_games_states_the_targets_release_after_the_move(
    owned_user, owned_library, graph, run, other_graph, other_run
):
    session = a_session(owned_library, run, graph.release)
    correlation_id = uuid.uuid7()

    restate_session(
        owned_user,
        session,
        a_draft(other_run, other_graph.release),
        correlation_id=correlation_id,
        implies_played=False,
    )

    session.refresh_from_db()
    assert session.release_id == other_graph.release.pk
    assert list(
        LibraryEvent.objects.filter(correlation_id=correlation_id)
        .order_by("sequence")
        .values_list("event_type", flat=True)
    ) == [
        "library.playersession.release_changed",
        "library.playersession.moved",
        "library.playersession.release_changed",
    ]


def test_an_edit_that_keeps_the_release_states_nothing_about_it(
    owned_user, owned_library, graph, run
):
    session = a_session(owned_library, run, graph.release)
    correlation_id = uuid.uuid7()

    restate_session(
        owned_user,
        session,
        a_draft(run, graph.release),
        correlation_id=correlation_id,
        implies_played=False,
    )

    assert not LibraryEvent.objects.filter(correlation_id=correlation_id).exists()


def test_a_run_move_counts_the_releases_it_cleared(
    owned_user, owned_library, graph, run, other_graph, other_run
):
    a_session(owned_library, run, graph.release)
    a_session(owned_library, run)
    state(owned_library, RecordHistoricalPlaytime(a_statement(run, graph.release)))

    moved = restate_run(
        owned_user,
        run,
        RunDraft(
            started=None,
            completed=None,
            note="",
            game_id=other_graph.game.pk,
            implies_played=False,
            implies_completed=False,
        ),
        correlation_id=uuid.uuid7(),
    )

    assert moved is not None
    assert moved.cleared_releases == 2
    assert "2 sessions and records no longer name a release of Hades." in (
        moved_sentence(moved)
    )


@pytest.fixture
def client(owned_user):
    signed_in = Client()
    signed_in.force_login(owned_user)
    return signed_in


def test_the_api_records_patches_and_reads_a_release(
    client, owned_library, graph, run, other_graph, other_run
):
    created = client.post(
        "/api/session/",
        {
            "playthrough_id": str(run.pk),
            "timing": {
                "day": "2026-01-02",
                "duration_seconds": 60,
            },
            "release_id": str(graph.release.pk),
        },
        content_type="application/json",
    )
    assert created.status_code == 201, created.content
    assert created.json()["release_id"] == str(graph.release.pk)
    session_id = created.json()["id"]

    moved = client.patch(
        f"/api/session/{session_id}",
        {
            "playthrough_id": str(other_run.pk),
            "release_id": str(other_graph.release.pk),
        },
        content_type="application/json",
    )
    assert moved.status_code == 200, moved.content
    assert moved.json()["release_id"] == str(other_graph.release.pk)

    cleared = client.patch(
        f"/api/session/{session_id}",
        {"release_id": None},
        content_type="application/json",
    )
    assert cleared.json()["release_id"] is None


def test_the_api_answers_a_release_of_another_game_with_its_sentence(
    client, graph, run, other_graph, other_run
):
    answer = client.post(
        "/api/session/",
        {
            "playthrough_id": str(run.pk),
            "timing": {
                "day": "2026-01-02",
                "duration_seconds": 60,
            },
            "release_id": str(other_graph.release.pk),
        },
        content_type="application/json",
    )

    assert answer.status_code == 409
    assert RELEASE_OF_ANOTHER_GAME in answer.content.decode()


def test_the_record_api_reads_its_release(client, owned_library, graph, run):
    state(owned_library, RecordHistoricalPlaytime(a_statement(run, graph.release)))

    answer = client.get("/api/historical-playtime/")

    assert answer.json()["items"][0]["release_id"] == str(graph.release.pk)


def test_the_held_search_lists_the_games_releases_a_copy_names(
    client, owned_library, graph, entry, run, other_graph, other_run
):
    uncopied = second_release(owned_library, graph.release)

    answer = client.get(f"/api/releases/held?game_id={graph.game.pk}")

    assert answer.status_code == 200
    values = [option["value"] for option in answer.json()]
    assert values == [str(graph.release.pk)]
    assert str(uncopied.pk) not in values
    assert "hint" not in answer.json()[0]


def test_the_held_search_hints_a_release_whose_copies_all_ended(
    client, owned_library, graph, entry, run
):
    end_entry_access(entry)

    (option,) = client.get(f"/api/releases/held?game_id={graph.game.pk}").json()

    assert option["hint"] == "Returned"


def test_the_held_search_answers_another_librarys_game_as_absent(
    client, django_user_model
):
    stranger = django_user_model.objects.create_user(username="stranger").library
    theirs = default_graph(Game(name="Tunic", library=stranger), stranger)

    answer = client.get(f"/api/releases/held?game_id={theirs.game.pk}")

    assert answer.status_code == 404


def test_the_played_search_lists_the_releases_rows_name_by_game(
    client, owned_library, graph, entry, run, other_graph, other_run
):
    a_session(owned_library, run, graph.release)
    state(
        owned_library,
        RecordHistoricalPlaytime(a_statement(other_run, other_graph.release)),
    )
    remove_entry(entry)

    every = client.get("/api/releases/played").json()
    narrowed = client.get("/api/releases/played?q=cel").json()

    assert [option["value"] for option in every] == [
        str(other_graph.release.pk),
        str(graph.release.pk),
    ]
    assert every[1]["label"].startswith("Hades · ")
    assert [option["value"] for option in narrowed] == [str(other_graph.release.pk)]


def session_post(game, run, **changes) -> dict[str, str]:
    return {
        "game": str(game.pk),
        "playthrough": str(run.pk),
        "release": "",
        "started_at": "2026-03-05 12:00",
        "started_at_zone": "",
        "ended_at": "",
        "ended_at_zone": "",
        "duration": "",
        "note": "",
        **changes,
    }


def test_the_session_form_states_a_release(client, graph, run):
    response = client.post(
        reverse("games:add_session"),
        session_post(graph.game, run, release=str(graph.release.pk)),
    )

    assert response.status_code == 302
    assert PlayerSession.objects.get().release_id == graph.release.pk


def test_the_session_form_refuses_another_games_release(
    client, graph, run, other_graph, other_run
):
    response = client.post(
        reverse("games:add_session"),
        session_post(graph.game, run, release=str(other_graph.release.pk)),
    )

    assert response.status_code == 200
    assert RELEASE_OF_ANOTHER_GAME in response.content.decode()
    assert not PlayerSession.objects.exists()


def test_the_session_form_keeps_a_held_release_whose_copy_is_gone(
    client, owned_library, graph, entry, run
):
    session = a_session(owned_library, run, graph.release)
    remove_entry(entry)
    url = reverse("games:edit_session", args=[session.pk])

    page = client.get(url)
    assert str(graph.release.pk) in page.content.decode()
    response = client.post(
        url,
        session_post(
            graph.game,
            run,
            release=str(graph.release.pk),
            started_at="2026-01-01 13:00",
            ended_at="2026-01-01 14:00",
            note="kept",
        ),
    )

    assert response.status_code == 302
    session.refresh_from_db()
    assert (session.note, session.release_id) == ("kept", graph.release.pk)


def test_the_record_form_states_a_release(client, graph, run):
    response = client.post(
        reverse("games:add_historical_playtime", args=[graph.game.pk]),
        posted_record([run.pk], when_year="2005", release=str(graph.release.pk)),
    )

    assert response.status_code == 302
    assert HistoricalPlaytime.objects.get().release_id == graph.release.pk


def test_the_record_form_refuses_another_games_release(
    client, graph, run, other_graph, other_run
):
    response = client.post(
        reverse("games:add_historical_playtime", args=[graph.game.pk]),
        posted_record([run.pk], when_year="2005", release=str(other_graph.release.pk)),
    )

    assert response.status_code == 200
    assert RELEASE_OF_ANOTHER_GAME in response.content.decode()


# ── Bulk Edit ────────────────────────────────────────────────────────────────


def bulk_edit(owned_user, session, statement, batch=None) -> str:
    return edit_one(
        owned_user,
        session,
        choice=statement.encode(),
        idempotency_key=str(uuid.uuid7()),
        correlation_id=batch or uuid.uuid7(),
    )


def bulk_undo(owned_user, session, batch) -> str:
    return edit_back(
        owned_user,
        session.pk,
        undoes=batch,
        idempotency_key=str(uuid.uuid7()),
        correlation_id=uuid.uuid7(),
    )


@pytest.mark.parametrize(
    "statement",
    [
        EditStatement(None, None, release=StatedRelease(uuid.uuid7())),
        EditStatement(None, None, release=StatedRelease(None)),
        EditStatement(None, True, release=StatedRelease(None)),
    ],
)
def test_a_bulk_statement_carries_a_release(statement):
    assert EditStatement.decode(statement.encode()) == statement


def test_bulk_edit_states_clears_and_undoes_a_release(
    owned_user, owned_library, graph, run
):
    session = a_session(owned_library, run)
    stated = bulk_edit(
        owned_user,
        session,
        EditStatement(None, None, release=StatedRelease(graph.release.pk)),
    )
    session.refresh_from_db()
    assert (stated, session.release_id) == ("moved", graph.release.pk)
    clearing = uuid.uuid7()

    bulk_edit(
        owned_user,
        session,
        EditStatement(None, None, release=StatedRelease(None)),
        clearing,
    )
    session.refresh_from_db()
    assert session.release_id is None

    bulk_undo(owned_user, session, clearing)
    session.refresh_from_db()
    assert session.release_id == graph.release.pk


def test_bulk_undo_refuses_a_gone_copy_before_any_write(
    owned_user, owned_library, graph, entry, run
):
    session = a_session(owned_library, run, graph.release)
    other = second_release(owned_library, graph.release)
    record_entry(owned_library, other)
    batch = uuid.uuid7()
    bulk_edit(
        owned_user,
        session,
        EditStatement(None, True, release=StatedRelease(other.pk)),
        batch,
    )
    remove_entry(entry)

    with pytest.raises(CommandFailed) as refused:
        bulk_undo(owned_user, session, batch)

    assert refused.value.message == NO_COPY_OF_RELEASE
    session.refresh_from_db()
    assert (session.emulated, session.release_id) == (True, other.pk)


def test_bulk_edit_refuses_another_games_release_before_any_write(
    owned_user, owned_library, graph, run, other_graph, other_run
):
    session = a_session(owned_library, other_run)

    with pytest.raises(CommandFailed) as refused:
        bulk_edit(
            owned_user,
            session,
            EditStatement(None, True, release=StatedRelease(graph.release.pk)),
        )

    assert refused.value.message == RELEASE_OF_ANOTHER_GAME
    session.refresh_from_db()
    assert session.emulated is False


def offered(library, rows) -> str:
    resolved = labelled_session_resolution(library, [row.pk for row in rows]).rows
    offer = offer_edit(library, resolved, CHOICE_FIELD)
    assert isinstance(offer, Control)
    return str(offer.node)


def test_the_bulk_release_is_offered_for_one_game_alone(
    owned_library, graph, run, other_graph, other_run
):
    one = a_session(owned_library, run, graph.release)
    other = a_session(owned_library, other_run)

    single = offered(owned_library, [one])
    several = offered(owned_library, [one, other])

    assert f'name="{CHOICE_FIELD}-release"' in single
    assert f"Keep: {release_label(graph.release)}" in single
    assert f'name="{CHOICE_FIELD}-release"' not in several


def test_bulk_settle_refuses_a_release_with_no_copy(owned_library, entry):
    uncopied = second_release(owned_library, entry.release)
    statement = EditStatement(None, None, release=StatedRelease(uncopied.pk))

    with pytest.raises(CommandRejected) as refused:
        settle_edit(owned_library, post_of(statement))

    assert refused.value.sentence == NO_COPY_OF_RELEASE


def post_of(statement: EditStatement) -> QueryDict:
    stated = QueryDict(mutable=True)
    stated[CHOICE_FIELD] = statement.encode()
    return stated


# ── Filters ──────────────────────────────────────────────────────────────────


@pytest.fixture
def demo(owned_library, graph) -> Release:
    """A prerelease Edition of the same game."""
    return prerelease_release(owned_library, graph.release)


def answered(library, criteria) -> set[PlayerSession]:
    context = filter_query_context_for_library(library)
    return set(library_sessions(library).filter(criteria.to_q(context)))


def test_a_session_on_a_prerelease_is_never_beyond_its_runs_dates(
    owned_library, graph, run, demo
):
    Playthrough.objects.filter(pk=run.pk).update(
        started=TemporalValue.from_day(date(2024, 1, 1)),
        start_recorded_at=timezone.now(),
        completed=TemporalValue.from_day(date(2024, 3, 1)),
        completion_recorded_at=timezone.now(),
    )
    rows = {}
    for side, day in (("before", date(2023, 6, 1)), ("after", date(2024, 6, 1))):
        rows[side, "demo"] = duration_only_row(
            run, day, timedelta(hours=1), release=demo
        )
        rows[side, "game"] = duration_only_row(
            run, day, timedelta(hours=1), release=graph.release
        )
        rows[side, "unstated"] = duration_only_row(run, day, timedelta(hours=1))

    for field, side in (
        ("before_playthrough_start", "before"),
        ("after_playthrough_completion", "after"),
    ):
        flagged = answered(
            owned_library, PlayerSessionFilter(**{field: BoolCriterion(value=True)})
        )
        unflagged = answered(
            owned_library, PlayerSessionFilter(**{field: BoolCriterion(value=False)})
        )
        assert flagged == {rows[side, "game"], rows[side, "unstated"]}
        assert unflagged == set(rows.values()) - flagged
    assert organization_counts(owned_library).before_start == 2


def test_sessions_filter_by_release_and_edition_kind(owned_library, graph, run, demo):
    on_the_demo = duration_only_row(
        run, date(2023, 6, 1), timedelta(hours=1), release=demo
    )
    on_the_game = duration_only_row(
        run, date(2023, 6, 2), timedelta(hours=1), release=graph.release
    )
    unstated = duration_only_row(run, date(2023, 6, 3), timedelta(hours=1))

    by_release = PlayerSessionFilter.from_json(
        {"release": {"value": [str(graph.release.pk)], "modifier": "INCLUDES"}}
    )
    demos = PlayerSessionFilter.from_json(
        {"edition_kind": {"value": ["prerelease"], "modifier": "INCLUDES"}}
    )
    none_stated = PlayerSessionFilter.from_json(
        {"release": {"value": [], "modifier": "IS_NULL"}}
    )

    assert answered(owned_library, by_release) == {on_the_game}
    assert answered(owned_library, demos) == {on_the_demo}
    assert answered(owned_library, none_stated) == {unstated}


def test_records_filter_by_edition_kind(owned_library, graph, run, demo):
    demo_record = record_row([run], release=demo)
    record_row([run], release=graph.release)
    record_row([run])

    demos = HistoricalPlaytimeFilter.from_json(
        {"edition_kind": {"value": ["prerelease"], "modifier": "INCLUDES"}}
    )
    context = filter_query_context_for_library(owned_library)

    assert set(library_records(owned_library).filter(demos.to_q(context))) == {
        demo_record
    }


def test_records_filter_by_release(owned_library, graph, run, demo):
    on_the_game = record_row([run], release=graph.release)
    record_row([run], release=demo)

    by_release = HistoricalPlaytimeFilter.from_json(
        {"release": {"value": [str(graph.release.pk)], "modifier": "INCLUDES"}}
    )
    context = filter_query_context_for_library(owned_library)

    assert set(library_records(owned_library).filter(by_release.to_q(context))) == {
        on_the_game
    }


# ── Review follow-ups ────────────────────────────────────────────────────────


def test_a_patch_naming_no_release_keeps_it(client, owned_library, graph, run):
    session = a_session(owned_library, run, graph.release)

    answer = client.patch(
        f"/api/session/{session.pk}", {"note": "x"}, content_type="application/json"
    )

    assert answer.json()["release_id"] == str(graph.release.pk)


def test_a_patch_whose_release_refuses_writes_nothing(
    client, owned_library, graph, run, other_graph, other_run
):
    session = a_session(owned_library, run, graph.release)
    events = LibraryEvent.objects.count()

    answer = client.patch(
        f"/api/session/{session.pk}",
        {"playthrough_id": str(other_run.pk), "release_id": str(graph.release.pk)},
        content_type="application/json",
    )

    assert answer.status_code == 409
    assert RELEASE_OF_ANOTHER_GAME in answer.content.decode()
    assert LibraryEvent.objects.count() == events
    session.refresh_from_db()
    assert (session.playthrough_id, session.release_id) == (run.pk, graph.release.pk)


def test_a_patch_moving_alone_says_it_cleared_the_release(
    client, owned_library, graph, run, other_run
):
    session = a_session(owned_library, run, graph.release)

    answer = client.patch(
        f"/api/session/{session.pk}",
        {"playthrough_id": str(other_run.pk)},
        content_type="application/json",
    )

    assert answer.json()["release_id"] is None
    assert "no longer names a release" in answer.headers["X-Events"]


def test_a_patch_naming_an_unseen_release_is_absent(
    client, owned_library, run, django_user_model
):
    session = a_session(owned_library, run)
    stranger = django_user_model.objects.create_user(username="stranger").library
    theirs = default_graph(Game(name="Tunic", library=stranger), stranger)

    answer = client.patch(
        f"/api/session/{session.pk}",
        {"release_id": str(theirs.release.pk)},
        content_type="application/json",
    )

    assert answer.status_code == 404


def test_an_edit_whose_release_refuses_writes_nothing(
    owned_user, owned_library, graph, run, other_graph, other_run
):
    session = a_session(owned_library, run, graph.release)
    uncopied = second_release(owned_library, other_graph.release)
    events = LibraryEvent.objects.count()

    with pytest.raises(CommandFailed) as refused:
        restate_session(
            owned_user,
            session,
            a_draft(other_run, uncopied, note="moved"),
            correlation_id=uuid.uuid7(),
            implies_played=False,
        )

    assert refused.value.message == NO_COPY_OF_RELEASE
    assert LibraryEvent.objects.count() == events


def test_a_held_release_the_catalog_removed_stays(
    client, owned_user, owned_library, graph, run
):
    session = a_session(owned_library, run, graph.release)
    state(owned_library, RecordHistoricalPlaytime(a_statement(run, graph.release)))
    record = HistoricalPlaytime.objects.get()
    remove(graph.release)

    response = client.post(
        reverse("games:edit_session", args=[session.pk]),
        session_post(
            graph.game,
            run,
            release=str(graph.release.pk),
            started_at="2026-01-01 13:00",
            ended_at="2026-01-01 14:00",
            note="kept",
        ),
    )
    state(
        owned_library,
        RestateHistoricalPlaytime(
            record.pk, replace(a_statement(run, graph.release), note="kept")
        ),
    )

    assert response.status_code == 302
    session.refresh_from_db()
    record.refresh_from_db()
    assert (session.note, session.release_id) == ("kept", graph.release.pk)
    assert (record.note, record.release_id) == ("kept", graph.release.pk)


def test_the_reclassify_page_carries_a_release_whose_copy_is_gone(
    client, owned_library, graph, entry, run
):
    session = a_session(owned_library, run, graph.release)
    remove_entry(entry)

    response = client.post(
        reverse("games:reclassify_session", args=[session.pk]),
        posted_record([run.pk], when_year="2026", release=str(graph.release.pk)),
    )

    assert response.status_code == 302, response.content
    assert HistoricalPlaytime.objects.get().release_id == graph.release.pk


def test_the_record_edit_page_keeps_a_release_whose_copy_is_gone(
    client, owned_library, graph, entry, run
):
    state(owned_library, RecordHistoricalPlaytime(a_statement(run, graph.release)))
    record = HistoricalPlaytime.objects.get()
    remove_entry(entry)
    url = reverse("games:edit_historical_playtime", args=[record.pk])

    response = client.post(
        url,
        posted_record(
            [run.pk], hours="10", when_year="2005", release=str(graph.release.pk)
        ),
    )

    assert response.status_code == 302, response.content
    record.refresh_from_db()
    assert record.release_id == graph.release.pk


def test_moving_a_run_back_restores_no_release(
    owned_library, graph, run, other_graph, other_run
):
    session = a_session(owned_library, run, graph.release)
    state(
        owned_library,
        MovePlaythroughToGame(playthrough_id=run.pk, game_id=other_graph.game.pk),
    )
    state(
        owned_library,
        MovePlaythroughToGame(playthrough_id=run.pk, game_id=graph.game.pk),
    )

    session.refresh_from_db()
    assert session.release_id is None


def test_resume_states_no_release(owned_user, owned_library, graph, run):
    a_session(owned_library, run, graph.release)

    resumed = clone_session(
        owned_user,
        graph.game,
        correlation_id=uuid.uuid7(),
    ).session_id

    assert PlayerSession.objects.get(pk=resumed).release_id is None


def test_a_release_with_a_live_copy_beside_an_ended_one_is_not_hinted(
    owned_library, graph, entry
):
    end_entry_access(entry)
    record_entry(owned_library, graph.release)

    assert ended_copy_ways(owned_library, [graph.release.pk]) == {}


def test_the_latest_recorded_end_names_the_hint(owned_library, graph, entry):
    second = record_entry(owned_library, graph.release)
    end_entry_access(entry, way=EndWay.SOLD)
    end_entry_access(second, way=EndWay.LOST)

    assert ended_copy_ways(owned_library, [graph.release.pk]) == {
        graph.release.pk: EndWay.LOST
    }


def test_an_unstated_end_hints_ended(owned_library, graph, entry):
    end_entry_access(entry, way=EndWay.UNSTATED)

    (option,) = held_release_options([graph.release.pk], library=owned_library)

    assert option["hint"] == "Ended"


def test_a_resolver_ignores_a_value_that_is_no_key(owned_library):
    assert held_release_options(["not-a-key"], library=owned_library) == []


def test_the_played_search_leaves_out_removed_sessions(
    client, owned_library, graph, run
):
    session = a_session(owned_library, run, graph.release)
    state(owned_library, RemoveSession(session.pk))

    assert client.get("/api/releases/played").json() == []


@pytest.mark.parametrize("raw", ['{"release": 7}', '{"release": "no-key"}'])
def test_a_carried_release_that_is_no_key_refuses(raw):
    with pytest.raises(CommandRejected):
        EditStatement.decode(raw)


def test_a_recorded_release_with_no_key_is_a_defect():
    event = LibraryEvent(payload={"release": {"id": "nope"}})

    with pytest.raises(RowUnreadable):
        _release_of(event)


def test_the_bulk_control_states_keeps_and_unsets_a_release(
    owned_library, graph, entry
):
    picked = settle_edit(owned_library, control(release=str(graph.release.pk)))
    unset = settle_edit(owned_library, control(unset_release="1"))

    assert EditStatement.decode(picked) == EditStatement(
        None, None, release=StatedRelease(graph.release.pk)
    )
    assert EditStatement.decode(unset) == EditStatement(
        None, None, release=StatedRelease(None)
    )


def test_the_bulk_control_refuses_a_release_with_no_copy(owned_library, entry):
    uncopied = second_release(owned_library, entry.release)

    with pytest.raises(CommandRejected) as refused:
        settle_edit(owned_library, control(release=str(uncopied.pk)))

    assert NO_COPY_OF_RELEASE in str(refused.value.sentence)


def test_a_record_with_no_copy_of_its_release_is_refused(owned_library, run, entry):
    uncopied = second_release(owned_library, entry.release)

    refusal = refused(
        owned_library, RecordHistoricalPlaytime(a_statement(run, uncopied))
    )

    assert refusal.sentence == NO_COPY_OF_RELEASE


def test_the_toast_names_one_cleared_release(
    owned_user, owned_library, graph, run, other_graph, other_run
):
    a_session(owned_library, run, graph.release)
    gone = a_session(owned_library, run, graph.release)
    state(owned_library, RemoveSession(gone.pk))

    moved = restate_run(
        owned_user,
        run,
        RunDraft(
            started=None,
            completed=None,
            note="",
            game_id=other_graph.game.pk,
            implies_played=False,
            implies_completed=False,
        ),
        correlation_id=uuid.uuid7(),
    )

    assert moved is not None
    assert moved.cleared_releases == 1
    assert "One session or record no longer names a release of Hades." in (
        moved_sentence(moved)
    )


def control(**answers) -> QueryDict:
    names = {
        key: unset_input_name(f"{CHOICE_FIELD}-{key.removeprefix('unset_')}")
        if key.startswith("unset_")
        else f"{CHOICE_FIELD}-{key}"
        for key in answers
    }
    stated = QueryDict(mutable=True)
    stated.update({names[key]: value for key, value in answers.items()})
    return stated


def test_a_purge_takes_rows_naming_a_private_release(
    owned_user, owned_library, graph, run
):
    a_session(owned_library, run, graph.release)
    state(owned_library, RecordHistoricalPlaytime(a_statement(run, graph.release)))

    call_command(
        "purge_user_library",
        "--user",
        owned_user.username,
        "--confirm",
        owned_user.username,
        stdout=StringIO(),
    )

    assert not PlayerSession.objects.exists()
    assert not Release.objects.filter(pk=graph.release.pk).exists()


# ── The list column ──────────────────────────────────────────────────────────


def on_dreamcast(release: Release) -> str:
    """A label no other page text holds."""
    Release.objects.filter(pk=release.pk).update(
        platform=Platform.objects.create(name="Dreamcast", group="Sega")
    )
    release.refresh_from_db()
    return release_label(release)


def test_the_sessions_list_hides_the_release_until_chosen(
    client, owned_user, owned_library, graph, run
):
    label = on_dreamcast(graph.release)
    a_session(owned_library, run, graph.release)
    url = reverse("games:list_sessions")

    assert label not in client.get(url).content.decode()

    ListColumnChoice.objects.create(
        user=owned_user, mode="sessions", shown={"release": True}
    )

    assert label in client.get(url).content.decode()


def test_the_historical_list_shows_a_chosen_release(
    client, owned_user, owned_library, graph, run
):
    label = on_dreamcast(graph.release)
    state(owned_library, RecordHistoricalPlaytime(a_statement(run, graph.release)))
    url = reverse("games:list_historical_playtime")
    assert label not in client.get(url).content.decode()
    ListColumnChoice.objects.create(
        user=owned_user, mode="historical_playtime", shown={"release": True}
    )

    assert label in client.get(url).content.decode()
