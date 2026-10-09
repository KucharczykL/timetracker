"""One press writes its steps in page order.

The form builds a `LogStatement`; `log_game` writes it, one or more
dispatches per step. A step that is refused stops the press, and the
steps written before it stay written. A named run or platform is
checked before the first write.
"""

import datetime
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Final, Literal, NamedTuple

from django.contrib.auth.models import User
from django.http import Http404

from games.api_creation import RowRefused
from games.catalog_release import SHARED_GAME_RELEASE, release_on, standing_release_on
from games.commands.endpoint import ActStatement
from games.commands.historical_playtime import HistoricalPlaytimeStatement
from games.commands.libraryentry import EntryStatement
from games.commands.playersession import DurationOnlyTiming
from games.events.dispatch import RowNotHeld
from games.ids import DeviceId, PlatformId, PlaythroughId
from games.models import (
    Game,
    HistoricalPlaytimeProvenance,
    Platform,
    PlayerGameStatus,
    Playthrough,
    Release,
    UserLibrary,
    status_implied_over,
)
from games.reads.log_game import copy_release_for, held_facts
from games.reads.playthrough_runs import (
    library_runs,
    live_ordinary_runs,
    tracked_game,
)
from games.writes.answers import CONFLICT_STATUS, CommandFailed
from games.writes.endpoint import KEEP, Keep, Restated
from games.writes.historical_playtime import record_historical_playtime
from games.writes.libraryentry import record_entry
from games.writes.playergame import record_facts, track_game
from games.writes.playersession import SessionDraft, record_session
from games.writes.playthrough import (
    RunDraft,
    RunEndpoint,
    record_run,
    restate_run,
    void_run_endpoint,
)

#: Steps a refusal can name.
type LogStep = Literal[
    "track",
    "copy",
    "dates",
    "note",
    "playtime",
    "mastered",
    "status",
    "platform",
]

#: Keys a retried playtime write apart.
type PlaytimeAttempt = int

PICKED_RUN_GONE = "That playthrough is no longer held. Reload the page and try again."
UNHELD_PLATFORM = "That platform is not held. Reload the page and try again."
GAME_GONE = "That game is gone. Reload the page."
#: Copy's default record when unstated.
UNKNOWN_WORD: Final = "unknown"


@dataclass(frozen=True, slots=True)
class SessionTiming:
    """One sitting: its day and duration."""

    day: datetime.date
    duration: datetime.timedelta
    device_id: DeviceId | None


@dataclass(frozen=True, slots=True)
class HistoricalHours:
    """Playtime stated without a sitting."""

    duration: datetime.timedelta
    device_id: DeviceId | None


type LogPlaytime = SessionTiming | HistoricalHours


@dataclass(frozen=True, slots=True)
class LogStatement:
    """What one press states; KEEP where unchanged."""

    game: Game
    #: Picked platform; None for none.
    platform: PlatformId | None | Keep
    #: Run given, else newest live run.
    run_id: PlaythroughId | None
    started: Restated[ActStatement]
    completed: Restated[ActStatement]
    #: Note; KEEP where untouched.
    note: str | Keep
    playtime: LogPlaytime | None
    attempt: PlaytimeAttempt
    mastered: bool | Keep
    status: PlayerGameStatus | Keep


class LoggedGame(NamedTuple):
    """What a press wrote."""

    written: frozenset[LogStep]
    #: The press tracked an untracked game.
    tracked_the_game: bool


class LogRefused(Exception):
    """Refused press; `written` holds earlier steps."""

    def __init__(
        self,
        step: LogStep,
        failure: CommandFailed,
        written: frozenset[LogStep],
        *,
        tracked_the_game: bool = False,
    ) -> None:
        super().__init__(failure.message)
        self.step = step
        self.failure = failure
        self.written = written
        self.tracked_the_game = tracked_the_game


@contextmanager
def _answering(step: LogStep, written: set[LogStep]) -> Iterator[None]:
    """Name the step in its refusal."""
    try:
        yield
    except CommandFailed as failure:
        raise LogRefused(step, failure, frozenset(written)) from failure


def _draft_act(restated: Restated[ActStatement]) -> ActStatement | None:
    """Act restated; KEEP and void state none."""
    return restated if isinstance(restated, ActStatement) else None


def _dates_changed(statement: LogStatement) -> bool:
    return statement.started is not KEEP or statement.completed is not KEEP


def _run_step(statement: LogStatement) -> LogStep:
    """The step a refusal of the press's run names."""
    if _dates_changed(statement):
        return "dates"
    return "playtime" if statement.playtime is not None else "note"


def _held_run(library: UserLibrary, statement: LogStatement) -> Playthrough | None:
    """Run named, else newest live ordinary."""
    if statement.run_id is not None:
        run = (
            library_runs(library)
            .filter(pk=statement.run_id, player_game__game=statement.game)
            .first()
        )
        if run is None:
            raise CommandFailed(PICKED_RUN_GONE, CONFLICT_STATUS)
        return run
    tracked = tracked_game(library, statement.game)
    return None if tracked is None else live_ordinary_runs(library, tracked).last()


def _named_platform(library: UserLibrary, platform_id: PlatformId) -> Platform:
    """Platform named and held by library."""
    platform = Platform.objects.visible_to(library).filter(pk=platform_id).first()
    if platform is None:
        raise CommandFailed(UNHELD_PLATFORM, CONFLICT_STATUS)
    return platform


def _check_named(library: UserLibrary, statement: LogStatement) -> None:
    """Refuse a named platform or run before any write."""
    if statement.platform is not KEEP and statement.platform is not None:
        with _answering("platform", set()):
            _named_platform(library, statement.platform)
    if statement.run_id is not None:
        with _answering(_run_step(statement), set()):
            _held_run(library, statement)


def _release_for_copy(
    actor: User, statement: LogStatement, platform: Platform
) -> Release:
    """Standing Release a new copy names."""
    game = statement.game
    try:
        if game.library_id is not None:
            return release_on(actor.library, game, platform).release
        standing = standing_release_on(game, platform)
    except RowRefused as refusal:
        raise CommandFailed(refusal.sentence, CONFLICT_STATUS) from refusal
    except (Http404, RowNotHeld) as gone:
        raise CommandFailed(GAME_GONE, CONFLICT_STATUS) from gone
    if standing is None:
        raise CommandFailed(SHARED_GAME_RELEASE, CONFLICT_STATUS)
    return standing


def _copy_step(
    actor: User,
    statement: LogStatement,
    *,
    token: uuid.UUID,
    correlation_id: uuid.UUID,
    written: set[LogStep],
) -> Release | None:
    """Release a press's playtime names."""
    library = actor.library
    game = statement.game
    if statement.platform is KEEP:
        platform = held_facts(library, game).platform
        return None if platform is None else copy_release_for(library, game, platform)
    # Held copy, no platform, or unchanged: none.
    if statement.platform is None:
        return None
    with _answering("platform", written):
        named = _named_platform(library, statement.platform)
        held = copy_release_for(library, game, named)
        if held is not None:
            return held
        release = _release_for_copy(actor, statement, named)
    with _answering("copy", written):
        record_entry(
            actor,
            EntryStatement(
                release_id=release.pk,
                access=UNKNOWN_WORD,
                format=UNKNOWN_WORD,
            ),
            correlation_id=correlation_id,
            idempotency_key=f"log-copy-{token}",
        )
    written.add("copy")
    return release


def _write_run(
    actor: User,
    statement: LogStatement,
    *,
    token: uuid.UUID,
    correlation_id: uuid.UUID,
    written: set[LogStep],
) -> tuple[PlaythroughId, bool]:
    """State a run's dates and note."""
    library = actor.library
    step: LogStep = "dates" if _dates_changed(statement) else "note"
    implies = statement.status is KEEP
    with _answering(step, written):
        run = _held_run(library, statement)
        note = (
            ("" if run is None else run.note)
            if statement.note is KEEP
            else statement.note
        )
        draft = RunDraft(
            started=_draft_act(statement.started),
            completed=_draft_act(statement.completed),
            note=note,
            implies_played=implies,
            implies_completed=implies,
        )
        if run is None:
            recorded = record_run(
                actor,
                statement.game,
                draft,
                correlation_id=correlation_id,
                idempotency_key=f"log-run-{token}",
            )
            written.add(step)
            return recorded.playthrough_id, recorded.tracked_the_game
    _void_endpoints(
        actor,
        run,
        statement,
        step=step,
        written=written,
        correlation_id=correlation_id,
    )
    with _answering(step, written):
        restate_run(actor, run, draft, correlation_id=correlation_id)
    written.add(step)
    return run.pk, False


def _void_endpoints(
    actor: User,
    run: Playthrough,
    statement: LogStatement,
    *,
    step: LogStep,
    written: set[LogStep],
    correlation_id: uuid.UUID,
) -> None:
    """Void each endpoint the person cleared, before any restatement."""
    cleared: tuple[tuple[RunEndpoint, bool], ...] = (
        ("start", statement.started is None),
        ("completion", statement.completed is None),
    )
    for endpoint, is_cleared in cleared:
        if not is_cleared:
            continue
        with _answering(step, written):
            result = void_run_endpoint(
                actor, run, endpoint, correlation_id=correlation_id
            )
        if result.sequences is not None:
            written.add(step)
    run.refresh_from_db()


def _write_playtime(
    actor: User,
    statement: LogStatement,
    playtime: LogPlaytime,
    playthrough_id: PlaythroughId,
    release: Release | None,
    *,
    token: uuid.UUID,
    correlation_id: uuid.UUID,
    written: set[LogStep],
) -> None:
    release_id = None if release is None else release.pk
    key_suffix = f"{token}-{statement.attempt}"
    with _answering("playtime", written):
        match playtime:
            case SessionTiming(day=day, duration=duration, device_id=device_id):
                record_session(
                    actor,
                    SessionDraft(
                        playthrough_id=playthrough_id,
                        timing=DurationOnlyTiming(day=day, duration=duration),
                        device_id=device_id,
                        note="",
                        emulated=False,
                        release_id=release_id,
                    ),
                    implies_played=statement.status is KEEP,
                    correlation_id=correlation_id,
                    idempotency_key=f"log-session-{key_suffix}",
                )
            case HistoricalHours(duration=duration, device_id=device_id):
                record_historical_playtime(
                    actor,
                    HistoricalPlaytimeStatement(
                        duration=duration,
                        when=None,
                        provenance=HistoricalPlaytimeProvenance.MANUALLY_ENTERED,
                        playthrough_ids=(playthrough_id,),
                        device_id=device_id,
                        release_id=release_id,
                        emulated=False,
                        note="",
                    ),
                    idempotency_key=f"log-historical-{key_suffix}",
                    correlation_id=correlation_id,
                )
    written.add("playtime")


def _playtime_run(
    actor: User,
    statement: LogStatement,
    *,
    token: uuid.UUID,
    correlation_id: uuid.UUID,
    written: set[LogStep],
) -> PlaythroughId:
    """Newest run, else a new bare run."""
    with _answering("playtime", written):
        run = _held_run(actor.library, statement)
        if run is not None:
            return run.pk
        recorded = record_run(
            actor,
            statement.game,
            RunDraft(
                started=None,
                completed=None,
                note="",
                implies_played=False,
                implies_completed=False,
            ),
            correlation_id=correlation_id,
            idempotency_key=f"log-run-{token}",
        )
        return recorded.playthrough_id


def _status_to_write(
    statement: LogStatement, live_status: PlayerGameStatus | None
) -> PlayerGameStatus | None:
    """Status stated, else Played a record implies over the live one."""
    if statement.status is not KEEP:
        return statement.status
    if (
        isinstance(statement.playtime, HistoricalHours)
        and live_status is not None
        and status_implied_over(live_status, PlayerGameStatus.PLAYED)
    ):
        return PlayerGameStatus.PLAYED
    return None


def log_game(
    actor: User,
    statement: LogStatement,
    *,
    correlation_id: uuid.UUID,
    token: uuid.UUID,
) -> LoggedGame:
    """Write the press's steps; status last."""
    library = actor.library
    game = statement.game
    written: set[LogStep] = set()
    tracked = False
    _check_named(library, statement)
    try:
        if tracked_game(library, game) is None:
            with _answering("track", written):
                track_game(actor, game, correlation_id=correlation_id)
            tracked = True

        release = _copy_step(
            actor,
            statement,
            token=token,
            correlation_id=correlation_id,
            written=written,
        )

        playthrough_id: PlaythroughId | None = None
        if _dates_changed(statement) or statement.note is not KEEP:
            playthrough_id, created_tracked = _write_run(
                actor,
                statement,
                token=token,
                correlation_id=correlation_id,
                written=written,
            )
            tracked = tracked or created_tracked

        if statement.playtime is not None:
            if playthrough_id is None:
                playthrough_id = _playtime_run(
                    actor,
                    statement,
                    token=token,
                    correlation_id=correlation_id,
                    written=written,
                )
            _write_playtime(
                actor,
                statement,
                statement.playtime,
                playthrough_id,
                release,
                token=token,
                correlation_id=correlation_id,
                written=written,
            )

        if statement.mastered is not KEEP:
            with _answering("mastered", written):
                record_facts(
                    actor,
                    game,
                    mastered=statement.mastered,
                    correlation_id=correlation_id,
                    idempotency_key=f"log-mastered-{token}",
                )
            written.add("mastered")

        # Read after the run's writes: a completion has already stated Completed.
        live = tracked_game(library, game)
        status = _status_to_write(
            statement, None if live is None else PlayerGameStatus(live.status)
        )
        if status is not None:
            with _answering("status", written):
                record_facts(
                    actor,
                    game,
                    status=status,
                    correlation_id=correlation_id,
                    idempotency_key=f"log-status-{token}",
                )
            written.add("status")
    except LogRefused as refused:
        refused.tracked_the_game = tracked
        raise

    return LoggedGame(written=frozenset(written), tracked_the_game=tracked)
