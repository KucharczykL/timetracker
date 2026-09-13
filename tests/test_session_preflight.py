"""What the legacy Session census reports."""

import json
import uuid
from dataclasses import fields
from datetime import date, datetime, timedelta
from io import StringIO
from zoneinfo import ZoneInfo

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.utils import timezone

from games.events.rebuild import write_targets
from games.management.commands.preflight_sessions import (
    GENERATED_PREFIX,
    MACHINE_PREFIX,
)
from games.models import (
    Game,
    PlayerGame,
    Playthrough,
    PlaythroughKind,
    Session,
    UserLibrary,
)
from games.preflight.session import (
    NO_COUNTS,
    AssignmentOutcome,
    LibraryPreflight,
    PreflightCounts,
    RunInterval,
    Samples,
    TimingVerdict,
    assign_run,
    claims,
    classify_timing,
    preflight_library,
    shared_catalog_counts,
)
from games.removal import remove
from timetracker.temporal import TemporalValue

UTC = ZoneInfo("UTC")
START = datetime(2024, 3, 1, 10, 0, tzinfo=UTC)


def session(
    *, end: datetime | None = None, manual: timedelta | None = timedelta(0)
) -> Session:
    """An unsaved row holding only what the rule reads."""
    return Session(timestamp_start=START, timestamp_end=end, duration_manual=manual)


def test_an_end_after_the_start_with_no_manual_duration_is_timed():
    row = session(end=START + timedelta(hours=1))
    assert classify_timing(row) is TimingVerdict.TIMED


def test_an_end_equal_to_the_start_is_timed():
    assert classify_timing(session(end=START)) is TimingVerdict.TIMED


def test_no_end_with_a_manual_duration_is_duration_only():
    row = session(manual=timedelta(hours=2))
    assert classify_timing(row) is TimingVerdict.DURATION_ONLY


def test_an_end_and_a_manual_duration_is_corrected():
    row = session(end=START + timedelta(hours=1), manual=timedelta(hours=2))
    assert classify_timing(row) is TimingVerdict.CORRECTED


def test_no_end_and_no_manual_duration_is_running():
    assert classify_timing(session()) is TimingVerdict.RUNNING


def test_an_end_before_the_start_is_negative_elapsed():
    row = session(end=START - timedelta(hours=1))
    assert classify_timing(row) is TimingVerdict.NEGATIVE_ELAPSED


def test_a_reversed_row_is_named_by_its_interval_not_its_duration():
    row = session(end=START - timedelta(hours=1), manual=timedelta(hours=2))
    assert classify_timing(row) is TimingVerdict.NEGATIVE_ELAPSED


def test_a_negative_manual_duration_is_negative_manual():
    row = session(manual=timedelta(hours=-1))
    assert classify_timing(row) is TimingVerdict.NEGATIVE_MANUAL


def test_a_negative_manual_duration_outranks_a_timed_interval():
    row = session(end=START + timedelta(hours=1), manual=timedelta(hours=-1))
    assert classify_timing(row) is TimingVerdict.NEGATIVE_MANUAL


def test_a_null_manual_duration_reads_as_zero():
    assert classify_timing(session(manual=None)) is TimingVerdict.RUNNING


def test_a_null_manual_duration_leaves_a_timed_row_timed():
    row = session(end=START + timedelta(hours=1), manual=None)
    assert classify_timing(row) is TimingVerdict.TIMED


@pytest.mark.parametrize("verdict", list(TimingVerdict))
def test_every_verdict_spells_its_own_name(verdict: TimingVerdict):
    assert verdict.value == verdict.name.lower()


def test_counts_sum_field_by_field():
    left = PreflightCounts(sessions_in_scope=3, timed=2, day_differs=1)
    right = PreflightCounts(sessions_in_scope=4, timed=1, sole_run=5)
    assert left + right == PreflightCounts(
        sessions_in_scope=7, timed=3, day_differs=1, sole_run=5
    )


def test_the_empty_counts_are_an_identity():
    populated = PreflightCounts(sessions_in_scope=9, bucket_primary=2)
    assert populated + NO_COUNTS == populated
    assert NO_COUNTS + populated == populated


def test_counts_render_every_field():
    rendered = PreflightCounts(timed=1).as_dict()
    assert set(rendered) == {field.name for field in fields(PreflightCounts)}
    assert rendered["timed"] == 1


def test_every_verdict_has_a_count_named_after_it():
    names = {field.name for field in fields(PreflightCounts)}
    assert {verdict.value for verdict in TimingVerdict} <= names


def test_samples_render_as_strings():
    identifier = uuid.uuid4()
    rendered = Samples(running=(identifier,)).as_dict()
    assert rendered["running"] == [str(identifier)]
    assert rendered["bucket_primary"] == []
    assert set(rendered) == {field.name for field in fields(Samples)}


DAY = date(2024, 3, 1)


def interval(started: date | None = None, completed: date | None = None) -> RunInterval:
    """A run bounded by whichever days are known."""
    return RunInterval(uuid.uuid4(), started, completed)


def test_a_sole_run_takes_the_session_however_far_outside_it_falls():
    only = interval(date(2020, 1, 1), date(2020, 2, 1))
    assignment = assign_run([only], DAY)
    assert assignment.outcome is AssignmentOutcome.SOLE_RUN
    assert assignment.run_id == only.run_id
    assert assignment.claimers == 0


def test_a_sole_run_stating_no_day_still_takes_the_session():
    assignment = assign_run([interval()], DAY)
    assert assignment.outcome is AssignmentOutcome.SOLE_RUN


def test_a_game_with_no_live_run_buckets():
    assignment = assign_run([], DAY)
    assert assignment.outcome is AssignmentOutcome.BUCKET
    assert assignment.run_id is None
    assert assignment.claimers == 0


def test_one_claimer_among_several_runs_takes_the_session():
    claimer = interval(date(2024, 2, 1), date(2024, 4, 1))
    other = interval(date(2023, 1, 1), date(2023, 2, 1))
    assignment = assign_run([other, claimer], DAY)
    assert assignment.outcome is AssignmentOutcome.CONTAINED
    assert assignment.run_id == claimer.run_id
    assert assignment.claimers == 1


def test_a_day_inside_no_run_buckets():
    runs = [
        interval(date(2023, 1, 1), date(2023, 2, 1)),
        interval(date(2025, 1, 1), date(2025, 2, 1)),
    ]
    assignment = assign_run(runs, DAY)
    assert assignment.outcome is AssignmentOutcome.BUCKET
    assert assignment.claimers == 0


def test_a_day_inside_two_runs_buckets_and_counts_both():
    runs = [
        interval(date(2024, 1, 1), date(2024, 4, 1)),
        interval(date(2024, 2, 1), date(2024, 5, 1)),
    ]
    assignment = assign_run(runs, DAY)
    assert assignment.outcome is AssignmentOutcome.BUCKET
    assert assignment.run_id is None
    assert assignment.claimers == 2


def test_a_start_only_run_claims_its_start_day_and_every_later_one():
    run = interval(started=DAY)
    assert claims(run, DAY)
    assert claims(run, DAY + timedelta(days=3650))
    assert not claims(run, DAY - timedelta(days=1))


def test_a_completion_only_run_claims_its_day_and_every_earlier_one():
    run = interval(completed=DAY)
    assert claims(run, DAY)
    assert claims(run, DAY - timedelta(days=3650))
    assert not claims(run, DAY + timedelta(days=1))


def test_a_dated_run_claims_both_its_endpoints_and_nothing_outside():
    run = interval(DAY, DAY + timedelta(days=7))
    assert claims(run, DAY)
    assert claims(run, DAY + timedelta(days=7))
    assert not claims(run, DAY - timedelta(days=1))
    assert not claims(run, DAY + timedelta(days=8))


def test_a_run_stating_no_day_claims_nothing():
    assert not claims(interval(), DAY)


# --- The per-library walk ---------------------------------------------------

PRAGUE = ZoneInfo("Europe/Prague")


@pytest.fixture
def owned_game(owned_library):
    """One tracked game, with the run the fixture gives it."""

    def make(name: str = "Tracked", **kwargs) -> Game:
        return Game.objects.create(name=name, library=owned_library, **kwargs)

    return make


def play(
    game: Game,
    start: datetime,
    *,
    end: datetime | None = None,
    manual: timedelta = timedelta(0),
    **kwargs,
) -> Session:
    """One session at that game."""
    return Session.objects.create(
        game=game,
        timestamp_start=start,
        timestamp_end=end,
        duration_manual=manual,
        **kwargs,
    )


def sole_run_of(game: Game) -> Playthrough:
    return Playthrough.objects.get(player_game__game=game)


def census(library, **kwargs) -> LibraryPreflight:
    """The census, proven to write nothing while it runs."""

    def refuse(execute, sql, params, many, context):
        if write_targets(sql):
            raise AssertionError(f"The census wrote: {sql[:120]}")
        return execute(sql, params, many, context)

    with connection.execute_wrapper(refuse):
        return preflight_library(library, **kwargs)


@pytest.mark.django_db
def test_a_game_with_no_sessions_is_counted_and_nothing_else(owned_library, owned_game):
    owned_game()
    counts = census(owned_library).counts
    assert counts.games_owned == 1
    assert counts.games_without_sessions == 1
    assert counts.sessions_in_scope == 0
    assert counts.classified == 0


@pytest.mark.django_db
def test_each_verdict_reaches_its_own_count(owned_library, owned_game):
    game = owned_game()
    play(game, START, end=START + timedelta(hours=1))
    play(game, START, manual=timedelta(hours=2))
    play(game, START)
    counts = census(owned_library).counts
    assert counts.timed == 1
    assert counts.duration_only == 1
    assert counts.running == 1
    assert counts.classified == 3
    assert counts.sessions_in_scope == 3
    assert counts.unaccounted == 0


@pytest.mark.django_db
def test_a_removed_session_is_counted_beside_its_verdict(owned_library, owned_game):
    game = owned_game()
    session = play(game, START, end=START + timedelta(hours=1))
    remove(session)
    counts = census(owned_library).counts
    assert counts.removed == 1
    assert counts.timed == 1
    assert counts.classified == 1


@pytest.mark.django_db
def test_a_session_on_a_removed_game_takes_no_verdict(owned_library, owned_game):
    game = owned_game()
    play(game, START, end=START + timedelta(hours=1))
    remove(game)
    counts = census(owned_library).counts
    assert counts.on_removed_game == 1
    assert counts.classified == 0
    assert counts.timed == 0
    assert counts.unaccounted == 0


@pytest.mark.django_db
def test_a_session_whose_game_is_untracked_counts_without_player_game(
    owned_library, owned_game
):
    game = owned_game()
    play(game, START, end=START + timedelta(hours=1))
    Playthrough.objects.filter(player_game__game=game).delete()
    PlayerGame.objects.filter(game=game).delete()
    counts = census(owned_library).counts
    assert counts.without_player_game == 1
    assert counts.classified == 0
    assert counts.unaccounted == 0


@pytest.mark.django_db
def test_a_session_on_a_removed_tracking_row_counts_on_removed_player_game(
    owned_library, owned_game
):
    game = owned_game()
    play(game, START, end=START + timedelta(hours=1))
    #: The mark is the projector's, so no command states it here.
    PlayerGame.objects.filter(game=game).update(removed_at=timezone.now())
    counts = census(owned_library).counts
    assert counts.on_removed_player_game == 1
    assert counts.classified == 0
    assert counts.unaccounted == 0


@pytest.mark.django_db
def test_a_removed_and_untracked_game_is_counted_once(owned_library, owned_game):
    game = owned_game()
    play(game, START, end=START + timedelta(hours=1))
    Playthrough.objects.filter(player_game__game=game).delete()
    PlayerGame.objects.filter(game=game).delete()
    remove(game)
    counts = census(owned_library).counts
    assert counts.on_removed_game == 1
    assert counts.without_player_game == 0
    assert counts.unaccounted == 0


@pytest.mark.django_db
def test_a_session_at_a_game_holding_one_run_takes_it(owned_library, owned_game):
    game = owned_game()
    play(game, START, end=START + timedelta(hours=1))
    counts = census(owned_library).counts
    assert counts.sole_run == 1
    assert counts.contained_primary == 0
    assert counts.bucket_primary == 0
    assert counts.bucket_secondary == 0


@pytest.mark.django_db
def test_a_second_run_makes_the_day_decide_and_the_zone_move_it(
    owned_library, owned_game, settings
):
    """The same instant is 1 March in UTC and 2 March in Prague."""
    settings.TIME_ZONE = "UTC"
    game = owned_game()
    tracked = PlayerGame.objects.get(game=game)
    dated = sole_run_of(game)
    dated.started = TemporalValue.from_day(date(2024, 2, 1))
    dated.completed = TemporalValue.from_day(date(2024, 3, 1))
    dated.start_recorded_at = START
    dated.completion_recorded_at = START
    dated.save()
    Playthrough.objects.create(
        pk=uuid.uuid7(),
        library=owned_library,
        player_game=tracked,
        kind=PlaythroughKind.ORDINARY,
        created_at=timezone.now(),
    )
    play(
        game,
        datetime(2024, 3, 1, 23, 30, tzinfo=UTC),
        end=None,
        manual=timedelta(hours=1),
    )

    counts = census(owned_library, day_zone=PRAGUE).counts
    assert counts.sole_run == 0
    assert counts.contained_primary == 1
    assert counts.bucket_primary == 0
    assert counts.contained_secondary == 0
    assert counts.bucket_secondary == 1
    assert counts.games_needing_bucket_primary == 0
    assert counts.games_needing_bucket_secondary == 1


@pytest.mark.django_db
def test_the_zone_delta_counts_a_day_a_month_and_a_year_crossing(
    owned_library, owned_game, settings
):
    settings.TIME_ZONE = "UTC"
    game = owned_game()
    play(game, datetime(2024, 3, 1, 23, 30, tzinfo=UTC))
    play(game, datetime(2024, 3, 31, 23, 30, tzinfo=UTC))
    play(game, datetime(2024, 12, 31, 23, 30, tzinfo=UTC))
    play(game, datetime(2024, 6, 1, 10, 0, tzinfo=UTC))
    counts = census(owned_library, day_zone=PRAGUE).counts
    assert counts.day_differs == 3
    assert counts.month_differs == 2
    assert counts.year_differs == 1


@pytest.mark.django_db
def test_a_row_naming_its_committed_zone_is_counted(owned_library, owned_game):
    game = owned_game()
    play(game, START, timestamp_start_timezone="Europe/Prague")
    play(game, START)
    counts = census(owned_library).counts
    assert counts.committed_zone_stated == 1


@pytest.mark.django_db
def test_one_library_never_counts_another_libraries_rows(
    owned_library, owned_game, django_user_model
):
    other = django_user_model.objects.create_user(username="other", password="p")
    theirs = Game.objects.create(name="Theirs", library=other.library)
    play(theirs, START, end=START + timedelta(hours=1))
    owned_game()
    counts = census(owned_library).counts
    assert counts.games_owned == 1
    assert counts.sessions_in_scope == 0


@pytest.mark.django_db
def test_a_shared_game_reaches_no_library_and_is_counted_on_its_own(
    owned_library, owned_game
):
    shared = Game.objects.create(name="Shared", library=None)
    play(shared, START, end=START + timedelta(hours=1))
    owned_game()
    counts = census(owned_library).counts
    assert counts.games_owned == 1
    assert counts.sessions_in_scope == 0
    catalog = shared_catalog_counts()
    assert catalog.shared_games == 1
    assert catalog.shared_game_sessions == 1


@pytest.mark.django_db
def test_samples_cap_at_the_size_asked_for(owned_library, owned_game):
    game = owned_game()
    for _ in range(4):
        play(game, START)
    assert len(census(owned_library, sample_size=2).samples.running) == 2
    assert census(owned_library, sample_size=0).samples.running == ()


@pytest.mark.django_db
def test_the_report_names_the_two_zones_it_read(owned_library, settings):
    settings.TIME_ZONE = "UTC"
    report = census(owned_library, day_zone=PRAGUE)
    assert report.zones == ("UTC", "Europe/Prague")
    assert report.library_id == owned_library.pk
    assert report.username == owned_library.user.username
    assert set(report.as_dict()) == {
        "library_id",
        "username",
        "zones",
        "counts",
        "samples",
    }


# --- The command ------------------------------------------------------------


def run_command(*arguments: str) -> str:
    output = StringIO()
    call_command("preflight_sessions", *arguments, stdout=output)
    return output.getvalue()


def payload_of(output: str) -> dict:
    for line in output.splitlines():
        if line.startswith(MACHINE_PREFIX):
            return json.loads(line.removeprefix(MACHINE_PREFIX))
    raise AssertionError("The command printed no machine line.")


@pytest.mark.django_db
def test_a_scope_naming_no_library_reads_nothing_and_exits_zero():
    output = run_command("--all-libraries")
    assert "No library was read" in output
    assert payload_of(output)["libraries"] == []


@pytest.mark.django_db
def test_the_machine_line_carries_the_schema_the_zones_and_the_summary(
    owned_library, owned_game
):
    game = owned_game()
    play(game, START, end=START + timedelta(hours=1))
    payload = payload_of(run_command("--user", owned_library.user.username))
    assert payload["schema_version"] == 1
    assert payload["summary"]["timed"] == 1
    assert set(payload["summary"]) == {field.name for field in fields(PreflightCounts)}
    assert len(payload["libraries"][0]["zones"]) == 2
    assert payload["shared_catalog"]["shared_games"] == 0


@pytest.mark.django_db
def test_two_runs_print_the_same_bytes_but_for_the_generated_line(
    owned_library, owned_game
):
    game = owned_game()
    play(game, START, end=START + timedelta(hours=1))

    def without_time(output: str) -> list[str]:
        return [
            line
            for line in output.splitlines()
            if not line.startswith(GENERATED_PREFIX)
            and not line.startswith(MACHINE_PREFIX)
        ]

    first = run_command("--all-libraries")
    second = run_command("--all-libraries")
    assert without_time(first) == without_time(second)


@pytest.mark.django_db
def test_a_row_no_mode_holds_does_not_fail_the_run(owned_library, owned_game):
    game = owned_game()
    play(game, START, end=START - timedelta(hours=1))
    output = run_command("--all-libraries")
    assert payload_of(output)["summary"]["negative_elapsed"] == 1
    assert "end earlier than start" in output


@pytest.mark.django_db
def test_an_unknown_username_is_refused():
    with pytest.raises(CommandError, match="No user is named"):
        run_command("--user", "nobody")


@pytest.mark.django_db
def test_a_user_owning_no_library_is_refused(django_user_model):
    user = django_user_model.objects.create_user(username="libraryless", password="p")
    UserLibrary.objects.filter(user=user).delete()
    with pytest.raises(CommandError, match="owns no library"):
        run_command("--user", "libraryless")


@pytest.mark.django_db
def test_library_text_that_is_no_uuid_is_refused():
    with pytest.raises(CommandError, match="is no UUID"):
        run_command("--library", "not-a-uuid")


@pytest.mark.django_db
def test_an_unknown_library_is_refused():
    with pytest.raises(CommandError, match="does not exist"):
        run_command("--library", str(uuid.uuid7()))


@pytest.mark.django_db
def test_a_negative_sample_size_is_refused():
    with pytest.raises(CommandError, match="not negative"):
        run_command("--all-libraries", "--sample-size", "-1")


@pytest.mark.django_db
def test_an_unknown_day_zone_is_refused():
    with pytest.raises(CommandError, match="Mars/Olympus"):
        run_command("--all-libraries", "--day-zone", "Mars/Olympus")
