"""The write a Log a game press makes, step by step."""

import datetime
from decimal import Decimal

import pytest
from graphs import default_graph

from games.commands.endpoint import ActStatement
from games.commands.libraryentry import EntryStatement
from games.commands.purchase import StatedPrice
from games.models import (
    Game,
    HistoricalPlaytime,
    LibraryEntry,
    LibraryEvent,
    PlayerGame,
    PlayerGameStatus,
    PlayerSession,
    Purchase,
)
from games.writes.log_game import (
    HistoricalHours,
    LogPlaytime,
    LogRefused,
    LogSection,
    LogStatement,
    SessionTiming,
    log_game,
)
from games.writes.playergame import new_correlation_id, track_game, untrack_game
from games.writes.purchase import PurchaseDraft
from timetracker.temporal import TemporalValue

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.untracked_games]

DAY = datetime.date(2026, 9, 1)


@pytest.fixture
def user(owned_user):
    return owned_user


@pytest.fixture
def game(owned_library):
    return Game.objects.create(library=owned_library, name="Outer Wilds")


@pytest.fixture
def release(owned_library, game):
    return default_graph(game, owned_library).release


def _day(day: datetime.date) -> ActStatement:
    return ActStatement(TemporalValue.from_day(day), "")


def _copy(release) -> EntryStatement:
    return EntryStatement(
        release_id=release.pk,
        access="owned",
        format="digital",
        note="",
        acquired=_day(DAY),
    )


def _statement(
    game,
    *,
    sections: frozenset[LogSection] = frozenset(),
    copy: EntryStatement | None = None,
    purchase: PurchaseDraft | None = None,
    run_id=None,
    started: ActStatement | None = None,
    completed: ActStatement | None = None,
    note: str | None = None,
    playtime: LogPlaytime | None = None,
    mastered: bool | None = None,
    status: PlayerGameStatus | None = None,
) -> LogStatement:
    """A press that ticks `sections` and states what it is given."""
    return LogStatement(
        game=game,
        sections=sections,
        copy=copy,
        purchase=purchase,
        run_id=run_id,
        started=started,
        completed=completed,
        note=note,
        playtime=playtime,
        mastered=mastered,
        status=status,
    )


def _press(user, statement, token=None, correlation_id=None):
    return log_game(
        user,
        statement,
        correlation_id=correlation_id or new_correlation_id(),
        token=token or new_correlation_id(),
    )


def _player_game(user, game) -> PlayerGame:
    return PlayerGame.objects.get(library=user.library, game=game)


def test_a_copy_alone_records_one_entry(user, game, release):
    statement = _statement(game, sections=frozenset({"copy"}), copy=_copy(release))

    logged = _press(user, statement)

    assert logged.written == frozenset({"copy"})
    assert logged.tracked_the_game is True
    assert LibraryEntry.objects.filter(library=user.library).count() == 1


def test_a_priced_copy_records_its_purchase(user, game, release):
    purchase = PurchaseDraft(
        copy=_copy(release),
        kind="game",
        name="",
        price=StatedPrice(Decimal("9.99"), "EUR"),
        note="",
        purchased=_day(DAY),
    )
    statement = _statement(
        game,
        sections=frozenset({"copy"}),
        copy=purchase.copy,
        purchase=purchase,
    )

    _press(user, statement)

    assert Purchase.objects.filter(entry__library=user.library).count() == 1
    assert LibraryEntry.objects.filter(library=user.library).count() == 1


def test_a_session_alone_records_one_sitting_on_a_run(user, game):
    statement = _statement(
        game,
        sections=frozenset({"playtime"}),
        playtime=SessionTiming(
            day=DAY, duration=datetime.timedelta(hours=2), device_id=None
        ),
    )

    logged = _press(user, statement)

    assert logged.written == frozenset({"playtime"})
    session = PlayerSession.objects.get(library=user.library)
    assert session.effective_duration == datetime.timedelta(hours=2)
    assert session.playthrough.player_game.game == game


def test_a_historical_record_alone_states_no_day(user, game):
    statement = _statement(
        game,
        sections=frozenset({"playtime"}),
        playtime=HistoricalHours(
            duration=datetime.timedelta(minutes=45), device_id=None
        ),
    )

    _press(user, statement)

    record = HistoricalPlaytime.objects.get(library=user.library)
    assert record.duration == datetime.timedelta(minutes=45)
    assert record.when_lower is None


def test_mastered_alone_states_the_fact(user, game):
    track_game(user, game, correlation_id=new_correlation_id())
    statement = _statement(game, sections=frozenset({"more"}), mastered=True)

    logged = _press(user, statement)

    assert logged.written == frozenset({"more"})
    assert _player_game(user, game).mastered is True


def test_dates_state_the_run_and_the_completion_implies_completed(user, game):
    statement = _statement(
        game,
        sections=frozenset({"dates"}),
        started=_day(DAY),
        completed=_day(DAY + datetime.timedelta(days=3)),
    )

    logged = _press(user, statement)

    assert logged.written == frozenset({"dates"})
    assert _player_game(user, game).status == PlayerGameStatus.COMPLETED


def test_all_sections_on_an_untracked_game_track_it_once(user, game, release):
    correlation_id = new_correlation_id()
    purchase = PurchaseDraft(
        copy=_copy(release),
        kind="game",
        name="",
        price=StatedPrice(Decimal("5.00"), "EUR"),
        note="",
        purchased=_day(DAY),
    )
    statement = _statement(
        game,
        sections=frozenset({"copy", "dates", "playtime", "more"}),
        copy=purchase.copy,
        purchase=purchase,
        started=_day(DAY),
        completed=_day(DAY),
        note="Good run",
        playtime=SessionTiming(
            day=DAY, duration=datetime.timedelta(hours=1), device_id=None
        ),
        mastered=True,
        status=PlayerGameStatus.ABANDONED,
    )

    logged = _press(user, statement, correlation_id=correlation_id)

    assert logged.written == frozenset({"copy", "dates", "playtime", "more"})
    assert logged.tracked_the_game is True
    assert PlayerGame.objects.filter(library=user.library, game=game).count() == 1
    events = LibraryEvent.objects.filter(library=user.library)
    assert set(events.values_list("correlation_id", flat=True)) == {correlation_id}
    player_game = _player_game(user, game)
    assert player_game.status == PlayerGameStatus.ABANDONED
    assert player_game.mastered is True


def test_a_picked_status_stands_over_an_implied_one(user, game):
    statement = _statement(
        game,
        sections=frozenset({"dates"}),
        completed=_day(DAY),
        status=PlayerGameStatus.SHELVED,
    )

    _press(user, statement)

    assert _player_game(user, game).status == PlayerGameStatus.SHELVED


def test_an_unpicked_status_leaves_the_implied_one(user, game):
    statement = _statement(game, sections=frozenset({"dates"}), completed=_day(DAY))

    _press(user, statement)

    assert _player_game(user, game).status == PlayerGameStatus.COMPLETED


def test_a_refused_run_after_a_saved_copy_keeps_the_copy(user, game, release):
    reversed_run = _statement(
        game,
        sections=frozenset({"copy", "dates"}),
        copy=_copy(release),
        started=_day(DAY),
        completed=_day(DAY - datetime.timedelta(days=30)),
    )
    token = new_correlation_id()

    with pytest.raises(LogRefused) as refused:
        _press(user, reversed_run, token=token)

    assert refused.value.step == "dates"
    assert refused.value.written == frozenset({"copy"})
    assert LibraryEntry.objects.filter(library=user.library).count() == 1

    #: The page drops the saved copy and finishes the rest.
    finished = _statement(
        game,
        sections=frozenset({"dates"}),
        started=_day(DAY),
        completed=_day(DAY + datetime.timedelta(days=1)),
    )
    logged = _press(user, finished, token=token)

    assert logged.written == frozenset({"dates"})
    assert LibraryEntry.objects.filter(library=user.library).count() == 1


def test_a_double_press_writes_once(user, game, release):
    statement = _statement(
        game,
        sections=frozenset({"copy", "playtime"}),
        copy=_copy(release),
        playtime=SessionTiming(
            day=DAY, duration=datetime.timedelta(hours=1), device_id=None
        ),
        status=PlayerGameStatus.PLAYED,
    )
    token = new_correlation_id()

    _press(user, statement, token=token)
    _press(user, statement, token=token)

    assert LibraryEntry.objects.filter(library=user.library).count() == 1
    assert PlayerSession.objects.filter(library=user.library).count() == 1


def test_a_removed_game_is_refused_on_the_game(user, game):
    track_game(user, game, correlation_id=new_correlation_id())
    untrack_game(user, game, correlation_id=new_correlation_id())
    statement = _statement(game, sections=frozenset({"more"}), mastered=True)

    with pytest.raises(LogRefused) as refused:
        _press(user, statement)

    assert refused.value.step == "game"
    assert refused.value.written == frozenset()
    assert not HistoricalPlaytime.objects.filter(library=user.library).exists()
