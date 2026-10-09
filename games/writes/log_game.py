"""Log a game: what one press states, and the writes that state it.

The form builds a `LogStatement`; `log_game` writes it, one dispatch
per step. A step that is refused stops the press, and the sections
written before it stay written.
"""

import datetime
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Final, Literal, NamedTuple

from django.contrib.auth.models import User

from games.commands.endpoint import ActStatement
from games.commands.historical_playtime import HistoricalPlaytimeStatement
from games.commands.libraryentry import EntryStatement
from games.commands.playersession import DurationOnlyTiming
from games.ids import PlaythroughId
from games.models import (
    Game,
    HistoricalPlaytimeProvenance,
    PlayerGameStatus,
    Playthrough,
    UserLibrary,
)
from games.reads.playthrough_runs import library_runs, sole_ordinary_run, tracked_game
from games.writes.answers import CONFLICT_STATUS, CommandFailed
from games.writes.historical_playtime import record_historical_playtime
from games.writes.libraryentry import record_entry
from games.writes.playergame import record_facts, track_game
from games.writes.playersession import SessionDraft, record_session
from games.writes.playthrough import RunDraft, record_run, restate_run
from games.writes.purchase import PurchaseDraft, record_purchase

type LogSection = Literal["copy", "dates", "playtime", "more"]

#: The order the page lists its sections in.
SECTIONS: Final[tuple[LogSection, ...]] = ("copy", "dates", "playtime", "more")
#: Sections whose writes name a run.
RUN_SECTIONS: Final[frozenset[LogSection]] = frozenset({"dates", "playtime", "more"})
#: Sections the run step states.
RUN_STEP_SECTIONS: Final[frozenset[LogSection]] = frozenset({"dates", "more"})

#: A refused step: a section, or the game and the status, which are none.
type LogStep = LogSection | Literal["game", "status"]

PICKED_RUN_GONE = "That playthrough is no longer held. Reload the page and try again."


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

    None states nothing for that part. A section that is not ticked
    arrives as None, so `log_game` never reads it.
    """

    game: Game
    sections: frozenset[LogSection]
    copy: EntryStatement | None
    #: The copy's price, where one is stated; the copy is then bought.
    purchase: PurchaseDraft | None
    #: The run the person picked, if any.
    run_id: PlaythroughId | None
    started: ActStatement | None
    completed: ActStatement | None
    #: The run's note, where More is ticked.
    note: str | None
    playtime: LogPlaytime | None
    mastered: bool | None
    status: PlayerGameStatus | None


class LoggedGame(NamedTuple):
    """What a press wrote."""

    written: frozenset[LogSection]
    #: The press tracked an untracked game.
    tracked_the_game: bool


class LogRefused(Exception):
    """A step refused the press; `written` names what came before it."""

    def __init__(
        self,
        step: LogStep,
        failure: CommandFailed,
        written: frozenset[LogSection],
    ) -> None:
        super().__init__(failure.message)
        self.step = step
        self.failure = failure
        self.written = written


@contextmanager
def _answering(step: LogStep, written: set[LogSection]) -> Iterator[None]:
    """Turn a step's refusal into one that names the step."""
    try:
        yield
    except CommandFailed as failure:
        raise LogRefused(step, failure, frozenset(written)) from failure


def _held_run(library: UserLibrary, statement: LogStatement) -> Playthrough | None:
    """The run the person picked, else the sole live ordinary one."""
    if statement.run_id is None:
        return sole_ordinary_run(library, statement.game)
    run = library_runs(library).filter(pk=statement.run_id).first()
    if run is None:
        raise CommandFailed(PICKED_RUN_GONE, CONFLICT_STATUS)
    return run


def _run_draft(statement: LogStatement, run: Playthrough | None) -> RunDraft:
    """What the run step states; a section not ticked states nothing.

    A note outside More is the run's own, so `restate_run` keeps it.
    """
    sections = statement.sections
    if statement.note is not None:
        note = statement.note
    else:
        note = "" if run is None else run.note
    return RunDraft(
        started=statement.started if "dates" in sections else None,
        completed=statement.completed if "dates" in sections else None,
        note=note,
        implies_played=True,
        implies_completed=True,
    )


def _write_run(
    actor: User,
    statement: LogStatement,
    *,
    correlation_id: uuid.UUID,
    written: set[LogSection],
) -> tuple[PlaythroughId, bool]:
    """The run step: state the run, creating it if none exists.

    Answers the run's id and whether the step tracked the game.
    """
    step: LogStep = "dates" if "dates" in statement.sections else "more"
    library = actor.library
    with _answering(step, written):
        run = _held_run(library, statement)
        draft = _run_draft(statement, run)
        if run is None:
            recorded = record_run(
                actor, statement.game, draft, correlation_id=correlation_id
            )
            return recorded.playthrough_id, recorded.tracked_the_game
        restate_run(actor, run, draft, correlation_id=correlation_id)
        return run.pk, False


def _write_playtime(
    actor: User,
    playtime: LogPlaytime,
    playthrough_id: PlaythroughId,
    *,
    correlation_id: uuid.UUID,
    token: uuid.UUID,
    written: set[LogSection],
) -> None:
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
                        release_id=None,
                    ),
                    implies_played=True,
                    correlation_id=correlation_id,
                    idempotency_key=f"log-session-{token}",
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
                        release_id=None,
                        emulated=False,
                        note="",
                    ),
                    idempotency_key=f"log-historical-{token}",
                    correlation_id=correlation_id,
                )


def log_game(
    actor: User,
    statement: LogStatement,
    *,
    correlation_id: uuid.UUID,
    token: uuid.UUID,
) -> LoggedGame:
    """Write the statement's sections, in the order the page states them.

    Track, copy, run, playtime, mastered, status. Each key carries
    `token`, so a resubmit of the same press replays what it wrote.
    One correlation id covers every dispatch.
    """
    library = actor.library
    game = statement.game
    written: set[LogSection] = set()
    tracked = False

    if tracked_game(library, game) is None:
        with _answering("game", written):
            track_game(actor, game, correlation_id=correlation_id)
        tracked = True

    copy = statement.copy
    if copy is not None:
        with _answering("copy", written):
            if statement.purchase is not None:
                record_purchase(
                    actor,
                    statement.purchase,
                    correlation_id=correlation_id,
                    idempotency_key=f"log-copy-{token}",
                )
            else:
                record_entry(
                    actor,
                    copy,
                    correlation_id=correlation_id,
                    idempotency_key=f"log-copy-{token}",
                )
        written.add("copy")

    run_sections = statement.sections & RUN_STEP_SECTIONS
    playthrough_id: PlaythroughId | None = None
    if run_sections:
        playthrough_id, created_tracked = _write_run(
            actor, statement, correlation_id=correlation_id, written=written
        )
        tracked = tracked or created_tracked
        #: More is written once its mastered step has also answered.
        if "dates" in run_sections:
            written.add("dates")

    if statement.playtime is not None:
        if playthrough_id is None:
            playthrough_id = _playtime_run(actor, statement, correlation_id, written)
        _write_playtime(
            actor,
            statement.playtime,
            playthrough_id,
            correlation_id=correlation_id,
            token=token,
            written=written,
        )
        written.add("playtime")

    if statement.mastered is not None:
        with _answering("more", written):
            record_facts(
                actor,
                game,
                mastered=statement.mastered,
                correlation_id=correlation_id,
                idempotency_key=f"log-mastered-{token}",
            )
    if "more" in statement.sections:
        written.add("more")

    if statement.status is not None:
        with _answering("status", written):
            record_facts(
                actor,
                game,
                status=statement.status,
                correlation_id=correlation_id,
                idempotency_key=f"log-status-{token}",
            )

    return LoggedGame(written=frozenset(written), tracked_the_game=tracked)


def _playtime_run(
    actor: User,
    statement: LogStatement,
    correlation_id: uuid.UUID,
    written: set[LogSection],
) -> PlaythroughId:
    """The run playtime names, where no run step answered.

    The picked run, else the sole one, else a run made with nothing
    stated. A session and a record each name a run, so one must exist.
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
