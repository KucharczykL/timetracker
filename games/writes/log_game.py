"""Log a game: what one press states, and the writes that state it.

The form builds a `LogStatement`; `log_game` writes it, one dispatch
per step. A step that is refused stops the press, and the steps
written before it stay written.
"""

import datetime
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Final, Literal, NamedTuple

from django.contrib.auth.models import User

from games.api_creation import RowRefused
from games.catalog_release import SHARED_GAME_RELEASE, release_on, standing_release_on
from games.commands.endpoint import ActStatement
from games.commands.historical_playtime import HistoricalPlaytimeStatement
from games.commands.libraryentry import EntryStatement
from games.commands.playersession import DurationOnlyTiming
from games.ids import PlatformId, PlaythroughId
from games.models import (
    Game,
    HistoricalPlaytimeProvenance,
    Platform,
    PlayerGameStatus,
    Playthrough,
    Release,
    UserLibrary,
)
from games.reads.log_game import copy_release_for
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
    record_run,
    restate_run,
    void_run_endpoint,
)

type LogSection = Literal["copy", "dates", "playtime", "more"]

#: The order the page lists its sections in.
SECTIONS: Final[tuple[LogSection, ...]] = ("copy", "dates", "playtime", "more")
#: Sections whose writes name a run.
RUN_SECTIONS: Final[frozenset[LogSection]] = frozenset({"dates", "playtime", "more"})

#: A refused step: a section, or the game's tracking, its status or its platform.
type LogStep = LogSection | Literal["track", "status", "platform"]

PICKED_RUN_GONE = "That playthrough is no longer held. Reload the page and try again."
UNHELD_PLATFORM = "That platform is not held. Reload the page and try again."
#: What a copy records about itself when the person states nothing.
UNKNOWN_WORD: Final = "unknown"


class SessionTiming(NamedTuple):
    """One sitting on a day, the duration it lasted."""

    day: datetime.date
    duration: datetime.timedelta
    device_id: uuid.UUID | None


class HistoricalHours(NamedTuple):
    """Playtime a library states without a sitting."""

    duration: datetime.timedelta
    device_id: uuid.UUID | None


type LogPlaytime = SessionTiming | HistoricalHours


@dataclass(frozen=True, slots=True)
class LogStatement:
    """What one press of Log a game states.

    A field the person did not change arrives as KEEP, so `log_game`
    never writes it. A dated act arrives as its statement, and None
    where a seen day was cleared, which voids the act.
    """

    game: Game
    #: The platform the person picked; None for none.
    platform_id: PlatformId | None
    #: Whether the platform differs from the one the form showed.
    platform_changed: bool
    #: The run the form was given, else the newest live run.
    run_id: PlaythroughId | None
    started: Restated[ActStatement]
    completed: Restated[ActStatement]
    #: The run's note; KEEP where the person left it alone.
    note: str | Keep
    playtime: LogPlaytime | None
    #: The form's count of written playtimes, which keys each one.
    attempt: int
    mastered: bool | Keep
    status: PlayerGameStatus | Keep
    #: The status the form showed, for the implied Played after a record.
    seen_status: PlayerGameStatus | None


class LoggedGame(NamedTuple):
    """What a press wrote."""

    written: frozenset[LogStep]
    #: The press tracked an untracked game.
    tracked_the_game: bool


class LogRefused(Exception):
    """A step refused the press; `written` names what came before it."""

    def __init__(
        self,
        step: LogStep,
        failure: CommandFailed,
        written: frozenset[LogStep],
    ) -> None:
        super().__init__(failure.message)
        self.step = step
        self.failure = failure
        self.written = written


@contextmanager
def _answering(step: LogStep, written: set[LogStep]) -> Iterator[None]:
    """Turn a step's refusal into one that names the step."""
    try:
        yield
    except CommandFailed as failure:
        raise LogRefused(step, failure, frozenset(written)) from failure


def _draft_act(restated: Restated[ActStatement]) -> ActStatement | None:
    """The act a restatement states; KEEP and a void state none."""
    return restated if isinstance(restated, ActStatement) else None


def _dates_changed(statement: LogStatement) -> bool:
    return statement.started is not KEEP or statement.completed is not KEEP


def _held_run(library: UserLibrary, statement: LogStatement) -> Playthrough | None:
    """The run the form named, else the newest live ordinary one."""
    if statement.run_id is not None:
        run = library_runs(library).filter(pk=statement.run_id).first()
        if run is None:
            raise CommandFailed(PICKED_RUN_GONE, CONFLICT_STATUS)
        return run
    tracked = tracked_game(library, statement.game)
    return None if tracked is None else live_ordinary_runs(library, tracked).last()


def _held_platform(
    library: UserLibrary, platform_id: PlatformId | None
) -> Platform | None:
    """The platform the person named, held by this library."""
    if platform_id is None:
        return None
    platform = Platform.objects.visible_to(library).filter(pk=platform_id).first()
    if platform is None:
        raise CommandFailed(UNHELD_PLATFORM, CONFLICT_STATUS)
    return platform


def _release_for_copy(
    actor: User, statement: LogStatement, platform: Platform | None
) -> Release:
    """The standing Release a new copy names.

    An owned game states one where absent; a shared game only reads
    its standing one.
    """
    game = statement.game
    if game.library_id is None:
        standing = standing_release_on(game, platform)
        if standing is None:
            raise CommandFailed(SHARED_GAME_RELEASE, CONFLICT_STATUS)
        return standing
    try:
        return release_on(actor.library, game, platform).release
    except RowRefused as refusal:
        raise CommandFailed(refusal.sentence, CONFLICT_STATUS) from refusal


def _copy_step(
    actor: User,
    statement: LogStatement,
    *,
    token: uuid.UUID,
    correlation_id: uuid.UUID,
    written: set[LogStep],
) -> Release | None:
    """The Release the press's playtime names, recording a copy if need be.

    A live copy on the platform is read first and wins. A changed
    platform with no copy records an Unknown one on its standing
    Release. An unchanged one with no copy names none.
    """
    library = actor.library
    with _answering("platform", written):
        platform = _held_platform(library, statement.platform_id)
        held = copy_release_for(library, statement.game, platform)
    if held is not None or not statement.platform_changed:
        return held
    with _answering("platform", written):
        release = _release_for_copy(actor, statement, platform)
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
    """The run step: state the dates and note, creating a run if none exists.

    Answers the run's id and whether the step tracked the game. An act
    implies its status unless the person changed Status.
    """
    library = actor.library
    step: LogStep = "dates" if _dates_changed(statement) else "more"
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
            result = (recorded.playthrough_id, recorded.tracked_the_game)
        else:
            restate_run(actor, run, draft, correlation_id=correlation_id)
            _void_endpoints(actor, run, statement, correlation_id=correlation_id)
            result = (run.pk, False)
    written.add(step)
    return result


def _void_endpoints(
    actor: User,
    run: Playthrough,
    statement: LogStatement,
    *,
    correlation_id: uuid.UUID,
) -> None:
    """Take back each endpoint whose seen day the person cleared."""
    if statement.started is None:
        void_run_endpoint(actor, run, "start", correlation_id=correlation_id)
    if statement.completed is None:
        void_run_endpoint(actor, run, "completion", correlation_id=correlation_id)


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
    correlation_id: uuid.UUID,
    written: set[LogStep],
) -> PlaythroughId:
    """The run playtime names, where no run step answered.

    The newest run, which Track made when the game was untracked; else
    a run made with nothing stated, since a session and a record each
    name a run.
    """
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
        )
        return recorded.playthrough_id


def _status_to_write(statement: LogStatement) -> PlayerGameStatus | None:
    """The status the press states, else the Played a historical record implies.

    A record implies nothing in its command, so the Status step states
    Played over an Unplayed game the form showed.
    """
    if statement.status is not KEEP:
        return statement.status
    if (
        isinstance(statement.playtime, HistoricalHours)
        and statement.seen_status == PlayerGameStatus.UNPLAYED
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
    """Write the statement's steps, in the order the page states them.

    Track, copy, run, playtime, mastered, status. Each key carries
    `token`, so a resubmit of the same press replays what it wrote.
    One correlation id covers every dispatch.
    """
    library = actor.library
    game = statement.game
    written: set[LogStep] = set()
    tracked = False

    if tracked_game(library, game) is None:
        with _answering("track", written):
            track_game(actor, game, correlation_id=correlation_id)
        tracked = True

    release = _copy_step(
        actor, statement, token=token, correlation_id=correlation_id, written=written
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
            playthrough_id = _playtime_run(actor, statement, correlation_id, written)
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
        with _answering("more", written):
            record_facts(
                actor,
                statement.game,
                mastered=statement.mastered,
                correlation_id=correlation_id,
                idempotency_key=f"log-mastered-{token}",
            )
        written.add("more")

    status = _status_to_write(statement)
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

    return LoggedGame(written=frozenset(written), tracked_the_game=tracked)
