"""The write path a person's statement about a run goes down."""

from datetime import date

import pytest

from games.models import Game, LibraryEvent, PlayerGame, Playthrough
from games.writes.answers import CommandFailed
from games.writes.playergame import new_correlation_id, track_game
from games.writes.playthrough import (
    RunDraft,
    record_run,
    remove_run,
    restate_run,
)
from timetracker.temporal import TemporalValue

#: Every test here wants the run #679 states, so none may start from
#: the bare row the autouse fixture writes.
pytestmark = pytest.mark.untracked_games


@pytest.fixture
def user(owned_user):
    return owned_user


@pytest.fixture
def game(owned_library):
    return Game.objects.create(library=owned_library, name="Outer Wilds")


def a_recorded_run(user, game, *, started, ended) -> Playthrough:
    """Track the game, state one run at it, and read the run back."""
    track_game(user, game, correlation_id=new_correlation_id())
    record_run(
        user,
        game,
        RunDraft(started=started, ended=ended, note=""),
        correlation_id=new_correlation_id(),
    )
    #: The run the tracked game was born with, now stating both acts.
    return Playthrough.objects.get(player_game__game=game)


class TestRecordRun:
    """#687: the first run is the one the tracked game already holds."""

    @pytest.mark.django_db(transaction=True)
    def test_the_first_run_states_its_acts_onto_the_run_born_with_the_game(
        self, user, game
    ):
        track_game(user, game, correlation_id=new_correlation_id())
        tracked = PlayerGame.objects.get(library=user.library, game=game)
        born = Playthrough.objects.get(player_game=tracked)

        record_run(
            user,
            game,
            RunDraft(started=date(2026, 1, 2), ended=date(2026, 2, 3), note="12h"),
            correlation_id=new_correlation_id(),
        )

        assert Playthrough.objects.filter(player_game=tracked).count() == 1
        born.refresh_from_db()
        assert born.started == TemporalValue.from_day(date(2026, 1, 2))
        assert born.completed == TemporalValue.from_day(date(2026, 2, 3))
        assert born.note == "12h"

    @pytest.mark.django_db(transaction=True)
    def test_the_second_run_is_a_new_one(self, user, game):
        track_game(user, game, correlation_id=new_correlation_id())
        for day in (date(2026, 1, 2), date(2026, 3, 4)):
            record_run(
                user,
                game,
                RunDraft(started=day, ended=day, note=""),
                correlation_id=new_correlation_id(),
            )

        tracked = PlayerGame.objects.get(library=user.library, game=game)
        assert Playthrough.objects.filter(player_game=tracked).count() == 2

    @pytest.mark.django_db(transaction=True)
    def test_an_untracked_game_is_tracked_once_and_left_with_one_run(self, user, game):
        #: No track_game here: the marker leaves the game with no
        #: PlayerGame row, which is what the retry branch is for.
        record_run(
            user,
            game,
            RunDraft(started=None, ended=None, note=""),
            correlation_id=new_correlation_id(),
        )

        tracked = PlayerGame.objects.get(library=user.library, game=game)
        assert Playthrough.objects.filter(player_game=tracked).count() == 1

    @pytest.mark.django_db(transaction=True)
    def test_neither_day_still_states_both_acts(self, user, game):
        track_game(user, game, correlation_id=new_correlation_id())

        record_run(
            user,
            game,
            RunDraft(started=None, ended=None, note=""),
            correlation_id=new_correlation_id(),
        )

        run = Playthrough.objects.get(player_game__game=game)
        assert run.start_recorded_at is not None
        assert run.completion_recorded_at is not None
        assert run.started is None and run.completed is None

    @pytest.mark.django_db(transaction=True)
    def test_a_reversed_pair_is_refused_before_anything_is_appended(self, user, game):
        track_game(user, game, correlation_id=new_correlation_id())
        before = LibraryEvent.objects.filter(library=user.library).count()

        with pytest.raises(CommandFailed):
            record_run(
                user,
                game,
                RunDraft(started=date(2026, 2, 3), ended=date(2026, 1, 2), note=""),
                correlation_id=new_correlation_id(),
            )

        assert LibraryEvent.objects.filter(library=user.library).count() == before


class TestRestateRun:
    """#687: an edit states differences, and states nothing twice."""

    @pytest.mark.django_db(transaction=True)
    def test_it_states_only_what_changed(self, user, game):
        run = a_recorded_run(user, game, started=date(2026, 1, 2), ended=None)
        before = LibraryEvent.objects.filter(library=user.library).count()

        restate_run(
            user,
            run,
            RunDraft(started=date(2026, 1, 3), ended=None, note=""),
            correlation_id=new_correlation_id(),
        )

        appended = LibraryEvent.objects.filter(library=user.library).count() - before
        assert appended == 1
        run.refresh_from_db()
        assert run.started == TemporalValue.from_day(date(2026, 1, 3))

    @pytest.mark.django_db(transaction=True)
    def test_a_resubmitted_edit_appends_nothing(self, user, game):
        run = a_recorded_run(user, game, started=date(2026, 1, 2), ended=None)
        draft = RunDraft(started=date(2026, 1, 2), ended=None, note="")
        restate_run(user, run, draft, correlation_id=new_correlation_id())
        before = LibraryEvent.objects.filter(library=user.library).count()

        restate_run(user, run, draft, correlation_id=new_correlation_id())

        assert LibraryEvent.objects.filter(library=user.library).count() == before

    @pytest.mark.django_db(transaction=True)
    def test_an_unstated_endpoint_is_a_first_statement(self, user, game):
        track_game(user, game, correlation_id=new_correlation_id())
        tracked = PlayerGame.objects.get(library=user.library, game=game)
        born = Playthrough.objects.get(player_game=tracked)

        restate_run(
            user,
            born,
            RunDraft(started=date(2026, 1, 2), ended=None, note=""),
            correlation_id=new_correlation_id(),
        )

        types = list(
            LibraryEvent.objects.filter(aggregate_id=born.pk)
            .order_by("sequence")
            .values_list("event_type", flat=True)
        )
        assert "library.playthrough.started" in types
        assert "library.playthrough.start_corrected" not in types

    @pytest.mark.django_db(transaction=True)
    def test_a_day_only_correction_leaves_the_endpoint_note_alone(self, user, game):
        run = a_recorded_run(user, game, started=date(2026, 1, 2), ended=None)
        Playthrough.objects.filter(pk=run.pk).update(start_note="from the box")
        run.refresh_from_db()

        restate_run(
            user,
            run,
            RunDraft(started=date(2026, 1, 5), ended=None, note=""),
            correlation_id=new_correlation_id(),
        )

        run.refresh_from_db()
        assert run.start_note == "from the box"


class TestRemoveRun:
    """#687: a tracked game keeps one run, and gives up any other."""

    @pytest.mark.django_db(transaction=True)
    def test_the_only_run_of_a_tracked_game_is_refused(self, user, game):
        run = a_recorded_run(user, game, started=date(2026, 1, 2), ended=None)

        with pytest.raises(CommandFailed) as refusal:
            remove_run(user, run, correlation_id=new_correlation_id())

        assert "only playthrough" in refusal.value.message
        run.refresh_from_db()
        assert run.removed_at is None

    @pytest.mark.django_db(transaction=True)
    def test_the_second_run_of_a_tracked_game_is_taken_out(self, user, game):
        a_recorded_run(user, game, started=date(2026, 1, 2), ended=None)
        record_run(
            user,
            game,
            RunDraft(started=date(2026, 3, 4), ended=None, note=""),
            correlation_id=new_correlation_id(),
        )
        second = Playthrough.objects.filter(player_game__game=game).latest("created_at")

        remove_run(user, second, correlation_id=new_correlation_id())

        second.refresh_from_db()
        assert second.removed_at is not None
        assert (
            Playthrough.objects.filter(
                player_game__game=game, removed_at__isnull=True
            ).count()
            == 1
        )
