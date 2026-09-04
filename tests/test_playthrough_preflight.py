"""What the legacy rows hold, before #684."""

import json
import uuid
from datetime import date, datetime
from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from django.utils import timezone

from games.backfill.playergame import backfill_library
from games.management.commands.preflight_playthroughs import MACHINE_PREFIX
from games.models import Game, GameStatusChange, LibraryEvent, PlayerGame, PlayEvent
from games.preflight.playthrough import (
    NO_COUNTS,
    CandidateEvent,
    CandidateKey,
    Endpoint,
    EndpointKind,
    LegacyOrderKey,
    LibraryPreflight,
    OrderingVerdict,
    PairingVerdict,
    PreflightCounts,
    RowVerdict,
    SharedCatalogCounts,
    classify_row,
    legacy_order_key,
    ordering_counts,
    pair_endpoints,
    preflight_library,
    shared_catalog_counts,
)
from games.removal import remove
from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.django_db


def _row(started=None, ended=None, game=None):
    """Never saved; the classifiers read fields."""
    return PlayEvent(id=uuid.uuid7(), game=game, started=started, ended=ended)


def test_both_endpoints_convert_without_a_question():
    row = _row(started=date(2024, 1, 1), ended=date(2024, 1, 9))
    assert classify_row(row) is RowVerdict.CLEAN_BOTH


def test_one_day_is_not_a_reversal():
    #: #681 refuses only completion before start.
    row = _row(started=date(2024, 1, 1), ended=date(2024, 1, 1))
    assert classify_row(row) is RowVerdict.CLEAN_BOTH


def test_a_start_with_no_completion():
    row = _row(started=date(2024, 1, 1))
    assert classify_row(row) is RowVerdict.CLEAN_START_ONLY


def test_a_completion_with_no_start():
    row = _row(ended=date(2024, 1, 9))
    assert classify_row(row) is RowVerdict.CLEAN_END_ONLY


def test_neither_endpoint_is_known():
    assert classify_row(_row()) is RowVerdict.NO_KNOWN_ENDPOINT


def test_a_completion_before_its_start_is_named():
    row = _row(started=date(2024, 1, 9), ended=date(2024, 1, 1))
    assert classify_row(row) is RowVerdict.REVERSED_ENDPOINTS


def test_a_known_start_sorts_before_an_unknown_one():
    known = _row(started=date(2024, 1, 1))
    unknown = _row()
    assert legacy_order_key(known) < legacy_order_key(unknown)


def test_an_unknown_completion_sorts_last_among_equal_starts():
    start = date(2024, 1, 1)
    dated = _row(started=start, ended=date(2024, 2, 1))
    open_ended = _row(started=start)
    assert legacy_order_key(dated) < legacy_order_key(open_ended)


def test_the_last_resort_is_the_primary_key():
    #: loaddata rewrites created_at; the pk survives.
    first = _row()
    second = _row()
    first.id, second.id = uuid.UUID(int=1), uuid.UUID(int=2)
    assert legacy_order_key(first) < legacy_order_key(second)


def test_the_key_names_its_parts():
    row = _row(started=date(2024, 1, 1))
    key = legacy_order_key(row)
    assert isinstance(key, LegacyOrderKey)
    assert key.start_unknown is False
    assert key.completion_unknown is True


def test_counts_sum_field_by_field():
    left = PreflightCounts(live_rows=2, clean_both=1)
    right = PreflightCounts(live_rows=3, tie_broken=1)
    total = left + right
    assert total.live_rows == 5
    assert total.clean_both == 1
    assert total.tie_broken == 1


def test_the_empty_counts_are_an_identity():
    counts = PreflightCounts(live_rows=4)
    assert NO_COUNTS + counts == counts


def test_counts_render_every_field():
    rendered = PreflightCounts(live_rows=1).as_dict()
    assert rendered["live_rows"] == 1
    assert rendered["tie_broken"] == 0


def test_distinct_dates_order_a_game_on_their_own():
    rows = [
        _row(started=date(2024, 1, 1)),
        _row(started=date(2024, 3, 1)),
    ]
    assert ordering_counts(rows) == OrderingVerdict(
        ordered_by_date=True, tie_broken=False, date_order_differs=False
    )


def test_two_rows_sharing_a_date_pair_fall_to_insertion_order():
    rows = [
        _row(started=date(2024, 1, 1), ended=date(2024, 2, 1)),
        _row(started=date(2024, 1, 1), ended=date(2024, 2, 1)),
    ]
    verdict = ordering_counts(rows)
    assert verdict.tie_broken is True
    assert verdict.ordered_by_date is False


def test_two_undated_rows_tie_as_well():
    verdict = ordering_counts([_row(), _row()])
    assert verdict.tie_broken is True


def test_a_single_row_ties_with_nothing():
    verdict = ordering_counts([_row()])
    assert verdict.tie_broken is False
    assert verdict.ordered_by_date is True


def test_a_date_order_against_the_insertion_order_is_reported():
    #: Written second, played first: numbers move.
    first_written = _row(started=date(2024, 3, 1))
    second_written = _row(started=date(2024, 1, 1))
    first_written.id, second_written.id = uuid.UUID(int=1), uuid.UUID(int=2)
    verdict = ordering_counts([first_written, second_written])
    assert verdict.date_order_differs is True
    assert verdict.tie_broken is False


AGGREGATE = uuid.UUID(int=100)


def _endpoint(row_id, kind=EndpointKind.COMPLETION, day=date(2024, 1, 9)):
    return Endpoint(
        row_id=uuid.UUID(int=row_id), kind=kind, day=day, aggregate_id=AGGREGATE
    )


def _candidate(correlation, kind=EndpointKind.COMPLETION, day=date(2024, 1, 9)):
    return CandidateEvent(
        key=CandidateKey(aggregate_id=AGGREGATE, kind=kind, day=day),
        correlation_id=uuid.UUID(int=correlation),
    )


def test_one_endpoint_and_one_event_pair_unambiguously():
    endpoint = _endpoint(1)
    candidate = _candidate(900)
    result = pair_endpoints([endpoint], [candidate])
    assert result.pairings[endpoint].verdict is PairingVerdict.UNAMBIGUOUS
    assert result.pairings[endpoint].correlation_id == candidate.correlation_id
    assert result.unclaimed_events == 0


def test_an_endpoint_with_no_event_is_absent():
    endpoint = _endpoint(1)
    result = pair_endpoints([endpoint], [])
    assert result.pairings[endpoint].verdict is PairingVerdict.ABSENT
    assert result.pairings[endpoint].correlation_id is None


def test_two_endpoints_of_one_day_are_both_ambiguous():
    #: Neither may take the shared id.
    first, second = _endpoint(1), _endpoint(2)
    result = pair_endpoints([first, second], [_candidate(900)])
    assert result.pairings[first].verdict is PairingVerdict.AMBIGUOUS
    assert result.pairings[second].verdict is PairingVerdict.AMBIGUOUS
    assert result.pairings[first].correlation_id is None


def test_one_endpoint_with_two_events_is_ambiguous():
    endpoint = _endpoint(1)
    result = pair_endpoints([endpoint], [_candidate(900), _candidate(901)])
    assert result.pairings[endpoint].verdict is PairingVerdict.AMBIGUOUS


def test_the_answer_does_not_depend_on_the_order_read():
    first, second = _endpoint(1), _endpoint(2)
    candidates = [_candidate(900), _candidate(901)]
    forward = pair_endpoints([first, second], candidates)
    backward = pair_endpoints([second, first], list(reversed(candidates)))
    assert forward.pairings == backward.pairings


def test_a_start_does_not_pair_with_a_completion_event():
    endpoint = _endpoint(1, kind=EndpointKind.START)
    result = pair_endpoints([endpoint], [_candidate(900)])
    assert result.pairings[endpoint].verdict is PairingVerdict.ABSENT


def test_a_different_day_does_not_pair():
    endpoint = _endpoint(1, day=date(2024, 1, 8))
    result = pair_endpoints([endpoint], [_candidate(900)])
    assert result.pairings[endpoint].verdict is PairingVerdict.ABSENT


def test_an_event_no_endpoint_matched_is_counted_unclaimed():
    result = pair_endpoints([], [_candidate(900), _candidate(901)])
    assert result.unclaimed_events == 2


def _game(library, name="Chrono Trigger"):
    return Game.objects.create(library=library, name=name)


def _saved_row(game, started=None, ended=None):
    return PlayEvent.objects.create(game=game, started=started, ended=ended)


def test_a_tracked_game_with_no_rows_receives_the_default(owned_library):
    _game(owned_library)
    counts = preflight_library(owned_library).counts
    assert counts.tracked == 1
    assert counts.tracked_without_rows == 1
    assert counts.live_rows == 0


def test_each_verdict_is_counted(owned_library):
    game = _game(owned_library)
    _saved_row(game, started=date(2024, 1, 1), ended=date(2024, 1, 9))
    _saved_row(game, started=date(2024, 2, 1))
    _saved_row(game, ended=date(2024, 3, 9))
    _saved_row(game)
    _saved_row(game, started=date(2024, 5, 9), ended=date(2024, 5, 1))
    counts = preflight_library(owned_library).counts
    assert counts.live_rows == 5
    assert counts.clean_both == 1
    assert counts.clean_start_only == 1
    assert counts.clean_end_only == 1
    assert counts.no_known_endpoint == 1
    assert counts.reversed_endpoints == 1


def test_a_removed_row_leaves_the_live_count(owned_library):
    game = _game(owned_library)
    remove(_saved_row(game, started=date(2024, 1, 1)))
    counts = preflight_library(owned_library).counts
    assert counts.live_rows == 0
    assert counts.rows_removed == 1


def test_a_row_on_a_removed_game_is_counted_once(owned_library):
    game = _game(owned_library)
    row = _saved_row(game, started=date(2024, 1, 1))
    remove(row)
    remove(game)
    counts = preflight_library(owned_library).counts
    assert counts.rows_on_removed_game == 1
    assert counts.rows_removed == 0


def test_an_untracked_game_is_not_a_backfill_failure(owned_library):
    #: remove_game_for_request untracks, then removes, without transaction.
    game = _game(owned_library)
    _saved_row(game, started=date(2024, 1, 1))
    PlayerGame.objects.filter(game=game).update(removed_at=timezone.now())
    counts = preflight_library(owned_library).counts
    assert counts.rows_untracked == 1
    assert counts.rows_without_projection == 0


@pytest.mark.untracked_games
def test_a_row_with_no_projection_row_is_the_backfill_signal(owned_library):
    game = _game(owned_library)
    _saved_row(game, started=date(2024, 1, 1))
    counts = preflight_library(owned_library).counts
    assert counts.rows_without_projection == 1
    assert counts.tracked == 0


def test_the_ordering_axis_is_counted_per_game(owned_library):
    tied = _game(owned_library, name="Tied")
    _saved_row(tied, started=date(2024, 1, 1))
    _saved_row(tied, started=date(2024, 1, 1))
    dated = _game(owned_library, name="Dated")
    _saved_row(dated, started=date(2024, 1, 1))
    _saved_row(dated, started=date(2024, 2, 1))
    counts = preflight_library(owned_library).counts
    assert counts.tie_broken == 1
    assert counts.ordered_by_date == 1


def test_samples_are_capped_and_keep_their_count(owned_library):
    game = _game(owned_library)
    for day in (1, 2, 3):
        _saved_row(game, started=date(2024, 5, day + 8), ended=date(2024, 5, day))
    result = preflight_library(owned_library, sample_size=2)
    assert result.counts.reversed_endpoints == 3
    assert len(result.samples.reversed_endpoints) == 2


def test_a_sample_size_of_zero_keeps_only_the_counts(owned_library):
    game = _game(owned_library)
    _saved_row(game, started=date(2024, 5, 9), ended=date(2024, 5, 1))
    result = preflight_library(owned_library, sample_size=0)
    assert result.counts.reversed_endpoints == 1
    assert result.samples.reversed_endpoints == ()


def test_one_library_never_counts_another(owned_library, django_user_model):
    stranger = django_user_model.objects.create_user(username="stranger", password="p")
    _saved_row(_game(stranger.library), started=date(2024, 1, 1))
    counts = preflight_library(owned_library).counts
    assert counts.tracked == 0
    assert counts.live_rows == 0


def test_the_walk_writes_nothing(owned_library):
    game = _game(owned_library)
    _saved_row(game, started=date(2024, 1, 1))
    before = (LibraryEvent.objects.count(), PlayEvent.objects.count())
    preflight_library(owned_library)
    assert (LibraryEvent.objects.count(), PlayEvent.objects.count()) == before


def test_the_result_renders_itself(owned_library):
    rendered = preflight_library(owned_library).as_dict()
    assert rendered["library_id"] == str(owned_library.pk)
    assert rendered["counts"]["tracked"] == 0
    assert rendered["samples"]["reversed_endpoints"] == []
    assert isinstance(preflight_library(owned_library), LibraryPreflight)


def _recorded_completion(game, day):
    """#676 turns this into a dated event."""
    return GameStatusChange.objects.create(
        game=game,
        old_status=Game.Status.PLAYED,
        new_status=Game.Status.FINISHED,
        #: Local noon: backfill reads localtime().
        timestamp=datetime(
            day.year, day.month, day.day, 12, tzinfo=timezone.get_current_timezone()
        ),
    )


@pytest.mark.untracked_games
@pytest.mark.django_db(transaction=True)
def test_an_endpoint_pairs_with_the_status_event_of_its_day(owned_library):
    completed = date(2024, 1, 9)
    game = _game(owned_library)
    game.status = Game.Status.FINISHED
    game.save()
    _recorded_completion(game, completed)
    _saved_row(game, started=date(2024, 1, 1), ended=completed)
    backfill_library(owned_library)
    counts = preflight_library(owned_library).counts
    assert counts.pairs_unambiguous == 1
    #: No `played` transition behind the start.
    assert counts.pairs_absent == 1


@pytest.mark.untracked_games
@pytest.mark.django_db(transaction=True)
def test_two_rows_completing_on_one_day_are_both_ambiguous(owned_library):
    completed = date(2024, 1, 9)
    game = _game(owned_library)
    game.status = Game.Status.FINISHED
    game.save()
    _recorded_completion(game, completed)
    _saved_row(game, started=date(2024, 1, 1), ended=completed)
    _saved_row(game, started=date(2023, 1, 1), ended=completed)
    backfill_library(owned_library)
    result = preflight_library(owned_library)
    assert result.counts.pairs_ambiguous == 2
    assert result.counts.pairs_unambiguous == 0
    assert len(result.samples.ambiguous_endpoints) == 2


@pytest.mark.untracked_games
@pytest.mark.django_db(transaction=True)
def test_a_status_event_no_endpoint_matched_is_unclaimed(owned_library):
    game = _game(owned_library)
    game.status = Game.Status.FINISHED
    game.save()
    _recorded_completion(game, date(2024, 1, 9))
    backfill_library(owned_library)
    counts = preflight_library(owned_library).counts
    assert counts.status_events_676 == 1
    assert counts.unclaimed_events == 1


@pytest.mark.untracked_games
@pytest.mark.django_db(transaction=True)
def test_an_undated_status_event_is_no_candidate(owned_library):
    #: #676's corrective event carries no day.
    game = _game(owned_library)
    game.status = Game.Status.FINISHED
    game.save()
    _saved_row(game, ended=date(2024, 1, 9))
    backfill_library(owned_library)
    counts = preflight_library(owned_library).counts
    assert counts.status_events_676 == 0
    assert counts.pairs_absent == 1


def test_a_removed_game_keeps_its_rows_out_of_the_no_rows_count(owned_library):
    #: remove() stamps the game; the projection row stays live.
    game = _game(owned_library)
    _saved_row(game, started=date(2024, 1, 1))
    remove(game)
    counts = preflight_library(owned_library).counts
    assert counts.tracked == 1
    assert counts.tracked_on_removed_game == 1
    assert counts.tracked_without_rows == 0
    assert counts.rows_on_removed_game == 1


def test_a_shared_game_a_library_tracks_is_walked(owned_library):
    shared = Game.objects.create(library=None, name="Shared")
    _saved_row(shared, started=date(2024, 1, 1))
    PlayerGame.objects.create(
        pk=uuid.uuid7(), library=owned_library, game=shared, tracked_at=timezone.now()
    )
    counts = preflight_library(owned_library).counts
    assert counts.tracked == 1
    assert counts.rows_total == 1
    assert counts.live_rows == 1
    assert counts.rows_unaccounted == 0


def test_every_row_lands_in_exactly_one_bucket(owned_library):
    walked = _game(owned_library, name="Walked")
    _saved_row(walked, started=date(2024, 1, 1))

    stamped = _game(owned_library, name="Stamped")
    remove(_saved_row(stamped, started=date(2024, 1, 1)))

    gone = _game(owned_library, name="Gone")
    _saved_row(gone, started=date(2024, 1, 1))
    remove(gone)

    untracked = _game(owned_library, name="Untracked")
    _saved_row(untracked, started=date(2024, 1, 1))
    PlayerGame.objects.filter(game=untracked).update(removed_at=timezone.now())

    shared = Game.objects.create(library=None, name="Shared")
    _saved_row(shared, started=date(2024, 1, 1))
    PlayerGame.objects.create(
        pk=uuid.uuid7(), library=owned_library, game=shared, tracked_at=timezone.now()
    )

    counts = preflight_library(owned_library).counts
    assert counts.rows_total == 5
    assert counts.rows_unaccounted == 0
    assert (
        counts.live_rows
        + counts.rows_removed
        + counts.rows_on_removed_game
        + counts.rows_untracked
        + counts.rows_without_projection
        == counts.rows_total
    )


@pytest.mark.untracked_games
@pytest.mark.django_db(transaction=True)
def test_an_abandoned_game_still_pairs_its_completion(owned_library):
    #: The legacy row's ended date is the day it was dropped.
    dropped = date(2024, 1, 9)
    game = _game(owned_library)
    game.status = Game.Status.ABANDONED
    game.save()
    GameStatusChange.objects.create(
        game=game,
        old_status=Game.Status.PLAYED,
        new_status=Game.Status.ABANDONED,
        timestamp=datetime(
            dropped.year,
            dropped.month,
            dropped.day,
            12,
            tzinfo=timezone.get_current_timezone(),
        ),
    )
    _saved_row(game, ended=dropped)
    backfill_library(owned_library)
    counts = preflight_library(owned_library).counts
    assert counts.pairs_unambiguous == 1
    assert counts.pairs_retired_or_abandoned == 1
    assert counts.pairs_absent == 0


@pytest.mark.untracked_games
@pytest.mark.django_db(transaction=True)
def test_a_completed_pair_is_not_counted_as_an_ending_status(owned_library):
    completed = date(2024, 1, 9)
    game = _game(owned_library)
    game.status = Game.Status.FINISHED
    game.save()
    _recorded_completion(game, completed)
    _saved_row(game, ended=completed)
    backfill_library(owned_library)
    counts = preflight_library(owned_library).counts
    assert counts.pairs_unambiguous == 1
    assert counts.pairs_retired_or_abandoned == 0


@pytest.mark.untracked_games
@pytest.mark.django_db(transaction=True)
def test_a_month_is_no_known_day(owned_library):
    game = _game(owned_library)
    game.status = Game.Status.FINISHED
    game.save()
    _recorded_completion(game, date(2024, 1, 9))
    _saved_row(game, ended=date(2024, 1, 9))
    backfill_library(owned_library)
    #: An UPDATE, so the projection is left where it stands.
    LibraryEvent.objects.filter(effective_time__isnull=False).update(
        effective_time=TemporalValue.from_month(2024, 1)
    )
    counts = preflight_library(owned_library).counts
    assert counts.status_events_676 == 0
    assert counts.status_events_undated == 1
    assert counts.pairs_absent == 1


@pytest.mark.untracked_games
@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "metadata", [{"origin": "request"}, {"origin": "backfill", "issue": 999}]
)
def test_only_a_676_backfill_event_is_a_candidate(owned_library, metadata):
    completed = date(2024, 1, 9)
    game = _game(owned_library)
    game.status = Game.Status.FINISHED
    game.save()
    _recorded_completion(game, completed)
    _saved_row(game, ended=completed)
    backfill_library(owned_library)
    #: An UPDATE, so the projection is left where it stands.
    LibraryEvent.objects.filter(effective_time__isnull=False).update(
        source_metadata=metadata
    )
    counts = preflight_library(owned_library).counts
    assert counts.status_events_676 == 0
    assert counts.status_events_undated == 0
    assert counts.pairs_absent == 1


def test_an_event_of_another_game_does_not_pair():
    endpoint = _endpoint(1)
    stranger = CandidateEvent(
        key=CandidateKey(
            aggregate_id=uuid.UUID(int=101),
            kind=EndpointKind.COMPLETION,
            day=date(2024, 1, 9),
        ),
        correlation_id=uuid.UUID(int=900),
    )
    result = pair_endpoints([endpoint], [stranger])
    assert result.pairings[endpoint].verdict is PairingVerdict.ABSENT
    assert result.unclaimed_events == 1


def test_a_shared_game_is_counted_outside_every_library(owned_library):
    shared = Game.objects.create(library=None, name="Shared")
    _saved_row(shared, started=date(2024, 1, 1))
    counts = shared_catalog_counts()
    assert counts == SharedCatalogCounts(
        shared_games=1, shared_game_rows=1, contested_rows=0
    )


def test_a_shared_game_two_libraries_track_holds_contested_rows(
    owned_library, django_user_model
):
    shared = Game.objects.create(library=None, name="Shared")
    _saved_row(shared, started=date(2024, 1, 1))
    stranger = django_user_model.objects.create_user(username="stranger", password="p")
    for library in (owned_library, stranger.library):
        PlayerGame.objects.create(
            pk=uuid.uuid7(),
            library=library,
            game=shared,
            tracked_at=timezone.now(),
        )
    assert shared_catalog_counts().contested_rows == 1


def _run(*args):
    output = StringIO()
    call_command("preflight_playthroughs", *args, stdout=output)
    return output.getvalue()


def _machine_line(text):
    line = next(line for line in text.splitlines() if line.startswith(MACHINE_PREFIX))
    return json.loads(line[len(MACHINE_PREFIX) :])


def test_a_scope_is_named_rather_than_defaulted(owned_library):
    with pytest.raises(CommandError):
        _run()


def test_the_machine_line_comes_first(owned_library):
    text = _run("--all-libraries")
    assert text.splitlines()[0].startswith(MACHINE_PREFIX)


def test_the_machine_line_carries_every_count(owned_library):
    game = _game(owned_library)
    _saved_row(game, started=date(2024, 5, 9), ended=date(2024, 5, 1))
    payload = _machine_line(_run("--user", owned_library.user.username))
    assert payload["schema_version"] == 1
    assert payload["summary"]["reversed_endpoints"] == 1
    assert payload["libraries"][0]["counts"]["reversed_endpoints"] == 1
    assert payload["shared_catalog"]["shared_games"] == 0


def test_the_summary_is_the_sum_of_the_libraries(owned_library, django_user_model):
    stranger = django_user_model.objects.create_user(username="stranger", password="p")
    for library in (owned_library, stranger.library):
        _saved_row(_game(library), started=date(2024, 1, 1))
    payload = _machine_line(_run("--all-libraries"))
    assert payload["summary"]["live_rows"] == 2
    assert (
        sum(entry["counts"]["live_rows"] for entry in payload["libraries"])
        == payload["summary"]["live_rows"]
    )


def test_the_machine_line_sorts_its_keys(owned_library):
    line = next(
        line
        for line in _run("--all-libraries").splitlines()
        if line.startswith(MACHINE_PREFIX)
    )
    body = line[len(MACHINE_PREFIX) :]
    assert body == json.dumps(json.loads(body), sort_keys=True, separators=(",", ":"))


def test_the_human_section_names_the_library(owned_library):
    text = _run("--user", owned_library.user.username)
    assert f"library {owned_library.pk}" in text
    assert "tracked games: 0" in text


def test_a_run_over_every_anomaly_still_exits_zero(owned_library):
    game = _game(owned_library)
    _saved_row(game, started=date(2024, 5, 9), ended=date(2024, 5, 1))
    _saved_row(game)
    #: A CommandError would rise out of call_command.
    _run("--all-libraries")


def test_two_runs_print_the_same_bytes(owned_library):
    game = _game(owned_library)
    _saved_row(game, started=date(2024, 1, 1))
    _saved_row(game, started=date(2024, 1, 1))
    assert _run("--all-libraries") == _run("--all-libraries")


def test_the_sample_cap_reaches_the_output(owned_library):
    game = _game(owned_library)
    for day in (1, 2, 3):
        _saved_row(game, started=date(2024, 5, day + 8), ended=date(2024, 5, day))
    payload = _machine_line(_run("--all-libraries", "--sample-size", "1"))
    entry = payload["libraries"][0]
    assert entry["counts"]["reversed_endpoints"] == 3
    assert len(entry["samples"]["reversed_endpoints"]) == 1


def test_an_unknown_user_is_refused_by_name(owned_library):
    with pytest.raises(CommandError, match="nobody"):
        _run("--user", "nobody")


def test_one_library_is_reported_by_its_uuid(owned_library, django_user_model):
    stranger = django_user_model.objects.create_user(username="stranger", password="p")
    _saved_row(_game(owned_library), started=date(2024, 1, 1))
    _saved_row(_game(stranger.library), started=date(2024, 1, 1))
    payload = _machine_line(_run("--library", str(owned_library.pk)))
    assert len(payload["libraries"]) == 1
    assert payload["libraries"][0]["library_id"] == str(owned_library.pk)
    assert payload["summary"]["live_rows"] == 1


def test_an_unknown_library_is_refused_by_uuid(owned_library):
    absent = uuid.uuid7()
    with pytest.raises(CommandError, match=str(absent)):
        _run("--library", str(absent))


def test_a_library_that_is_no_uuid_is_refused_rather_than_raised(owned_library):
    #: ValidationError from the field, not a CommandError of ours.
    with pytest.raises(CommandError, match="not-a-uuid"):
        _run("--library", "not-a-uuid")


def test_a_negative_sample_size_is_refused(owned_library):
    with pytest.raises(CommandError, match="negative"):
        _run("--all-libraries", "--sample-size", "-1")


def test_the_report_names_its_denominator(owned_library):
    game = _game(owned_library)
    _saved_row(game, started=date(2024, 1, 1))
    text = _run("--all-libraries")
    assert "play events in scope: 1" in text
    assert "in no bucket above: 0" in text


@pytest.mark.untracked_games
@pytest.mark.django_db(transaction=True)
def test_the_sample_fixture_walks_and_states_why_it_cannot_pair(django_user_model):
    """No legacy status rows, so nothing pairs."""
    owner = django_user_model.objects.create_user(username="sample-owner", password="p")
    call_command("load_sample_data", "--user", owner.username, verbosity=0)

    report = preflight_library(owner.library)
    counts = report.counts
    assert counts.tracked > 0
    assert counts.live_rows > 0
    assert (
        counts.clean_both
        + counts.clean_start_only
        + counts.clean_end_only
        + counts.no_known_endpoint
        + counts.reversed_endpoints
        == counts.live_rows
    )
    #: anonymize_sample omits GameStatusChange, so nothing dates.
    assert GameStatusChange.objects.count() == 0
    assert counts.status_events_676 == 0
    assert counts.pairs_unambiguous == 0
    assert counts.pairs_ambiguous == 0
    assert counts.unclaimed_events == 0
    assert counts.pairs_absent > 0
