"""Stating how many times a game was played through."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar

from games.commands.playergame import (
    HeldGame,
    status_change_event,
    with_implied_status,
)
from games.commands.playthrough import refuse_a_foreign_referrer
from games.commands.scope import Refusal, library_row
from games.events.dispatch import (
    Command,
    CommandContext,
    CommandName,
    CommandRejected,
    RowNotHeld,
    RowUnreadable,
)
from games.events.playergame import PLAYERGAME_STATUS_CHANGED
from games.events.playthrough import (
    PLAYTHROUGH_COMPLETED,
    PLAYTHROUGH_COMPLETION_VOIDED,
    PLAYTHROUGH_CREATED,
    PLAYTHROUGH_REMOVED,
    PLAYTHROUGH_START_VOIDED,
    PLAYTHROUGH_STARTED,
    playthrough_completed,
    playthrough_completion_voided,
    playthrough_created,
    playthrough_removed,
    playthrough_restored,
    playthrough_start_voided,
    playthrough_started,
)
from games.events.vocabulary import NewEvent, Unchanged
from games.models import LibraryEvent, PlayerGame, PlayerGameStatus, Playthrough
from games.reads.events import aggregate_events, batch_events
from games.reads.playergame_facts import status_change
from games.reads.playthrough_count import bare_runs, dateless_runs, unnamed_runs
from games.reads.playthrough_runs import completed_run_count, live_ordinary_runs

#: A raise appends three events a run.
MAX_TIMES_PLAYED = 100

CHANGED_SINCE = (
    "These playthroughs have changed since. Edit them in the Playthroughs "
    "table instead."
)


def _tracked(context: CommandContext, game_id: uuid.UUID) -> PlayerGame:
    """The tracked row, refused when absent or removed."""
    tracked = library_row(
        context,
        PlayerGame.objects.all(),
        Refusal(
            message=(
                f"This library tracks no game {game_id}, so it holds no "
                "playthroughs to count."
            ),
            sentence=(
                "That game is not in your library. Add it before stating how "
                "many times you played it."
            ),
            raises=CommandRejected,
        ),
        game_id=game_id,
    )
    #: Under dispatch's lock: the mark cannot move.
    if tracked.removed_at is not None:
        raise CommandRejected(
            f"This library removed game {game_id}, so it counts no runs at it.",
            sentence=(
                "That game was removed from your library. Restore it before "
                "stating how many times you played it."
            ),
        )
    return tracked


def _played_through(run_id: uuid.UUID) -> list[NewEvent]:
    """Both acts, no day, no note."""
    return [
        playthrough_started(run_id, when=None, note=""),
        playthrough_completed(run_id, when=None, note=""),
    ]


@dataclass(frozen=True, slots=True)
class StatePlaythroughCount(Command):
    """State how many runs were completed."""

    command_name: ClassVar[CommandName] = CommandName.PLAYTHROUGH_STATE_COUNT
    game_id: uuid.UUID
    count: int

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        tracked = _tracked(context, self.game_id)
        if self.count < 0:
            raise CommandRejected(
                f"A count of {self.count} runs was stated for game {self.game_id}.",
                sentence="Times played cannot be below zero.",
            )
        current = completed_run_count(context.library, tracked)
        if self.count == current:
            return Unchanged(f"Game {self.game_id} was played {current} times.")
        if self.count > current:
            return self._raise(context, tracked, self.count - current)
        return self._lower(context, tracked, current - self.count)

    def _raise(
        self, context: CommandContext, tracked: PlayerGame, added: int
    ) -> Sequence[NewEvent] | Unchanged:
        if self.count > MAX_TIMES_PLAYED:
            raise CommandRejected(
                f"A count of {self.count} runs exceeds {MAX_TIMES_PLAYED}.",
                sentence=f"State {MAX_TIMES_PLAYED} times or fewer.",
            )
        events: list[NewEvent] = []
        runs = list(live_ordinary_runs(context.library, tracked)[:2])
        bare = list(bare_runs(context.library, tracked)[:1])
        if len(runs) == 1 and bare == runs:
            events += _played_through(runs[0].pk)
            added -= 1
        for _ in range(added):
            #: The build reads no new row.
            run_id = uuid.uuid7()
            events.append(playthrough_created(tracked.pk, playthrough_id=run_id))
            events += _played_through(run_id)
        return with_implied_status(
            context, events, HeldGame(tracked), PlayerGameStatus.COMPLETED
        )

    def _lower(
        self, context: CommandContext, tracked: PlayerGame, dropped: int
    ) -> Sequence[NewEvent]:
        candidates = list(dateless_runs(context.library, tracked)[:dropped])
        if len(candidates) < dropped:
            raise CommandRejected(
                f"Game {self.game_id} holds {len(candidates)} dateless runs, "
                f"and lowering to {self.count} takes {dropped}.",
                sentence=(
                    f"Only {len(candidates)} of these playthroughs state no "
                    "days, name, note or play. Remove the others in the "
                    "Playthroughs table."
                ),
            )
        for run in candidates:
            refuse_a_foreign_referrer(run)
        live = live_ordinary_runs(context.library, tracked).count()
        events: list[NewEvent] = []
        if dropped == live:
            #: A tracked game keeps one run.
            kept = candidates.pop()
            events += [
                playthrough_completion_voided(kept.pk),
                playthrough_start_voided(kept.pk),
            ]
        events += [playthrough_removed(run.pk) for run in candidates]
        return events


@dataclass(frozen=True, slots=True)
class UndoPlaythroughCount(Command):
    """Take one count statement back whole."""

    command_name: ClassVar[CommandName] = CommandName.PLAYTHROUGH_UNDO_COUNT
    game_id: uuid.UUID
    #: The statement's correlation id.
    statement: uuid.UUID
    #: The total the statement left.
    stated: int

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        tracked = _tracked(context, self.game_id)
        events = list(batch_events(context.library, self.statement))
        run_ids = list(
            dict.fromkeys(
                event.aggregate_id
                for event in events
                if event.event_type != PLAYERGAME_STATUS_CHANGED.event_type
            )
        )
        self._refuse_another_statement(context, tracked, events, run_ids)
        self._refuse_runs_changed_since(context, events, run_ids)
        if completed_run_count(context.library, tracked) != self.stated:
            raise CommandRejected(
                f"Game {self.game_id} no longer counts the {self.stated} runs "
                f"statement {self.statement} left.",
                sentence=CHANGED_SINCE,
            )
        created = [
            event.aggregate_id
            for event in events
            if event.event_type == PLAYTHROUGH_CREATED.event_type
        ]
        self._refuse_named_runs(context, created)
        inverses = [
            inverse
            for event in reversed(events)
            if (inverse := _inverse(event, created)) is not None
        ]
        status = self._status_back(context, tracked)
        return inverses if status is None else [*inverses, status]

    def _refuse_another_statement(
        self,
        context: CommandContext,
        tracked: PlayerGame,
        events: list[LibraryEvent],
        run_ids: list[uuid.UUID],
    ) -> None:
        """A statement of this game, or absent."""
        held = Playthrough.objects.filter(
            library=context.library, player_game=tracked, pk__in=run_ids
        ).count()
        foreign = {
            event.aggregate_id
            for event in events
            if event.event_type == PLAYERGAME_STATUS_CHANGED.event_type
        } - {tracked.pk}
        if not events or held != len(run_ids) or foreign:
            raise RowNotHeld(
                f"Statement {self.statement} is no count this library stated "
                f"for game {self.game_id}."
            )

    def _refuse_runs_changed_since(
        self,
        context: CommandContext,
        events: list[LibraryEvent],
        run_ids: list[uuid.UUID],
    ) -> None:
        for run_id in run_ids:
            last = max(
                event.sequence for event in events if event.aggregate_id == run_id
            )
            if (
                aggregate_events(context.library, run_id)
                .filter(sequence__gt=last)
                .exists()
            ):
                raise CommandRejected(
                    f"Playthrough {run_id} states an event after statement "
                    f"{self.statement}.",
                    sentence=CHANGED_SINCE,
                )

    def _refuse_named_runs(
        self, context: CommandContext, created: list[uuid.UUID]
    ) -> None:
        runs = Playthrough.objects.filter(library=context.library, pk__in=created)
        if unnamed_runs(runs).count() != len(created):
            raise CommandRejected(
                f"A row names a run statement {self.statement} created.",
                sentence=CHANGED_SINCE,
            )
        for run in runs:
            refuse_a_foreign_referrer(run)

    def _status_back(
        self, context: CommandContext, tracked: PlayerGame
    ) -> NewEvent | None:
        """The word before, while still latest."""
        change = status_change(context.library, tracked.pk, self.statement)
        if change is None:
            return None
        latest = (
            aggregate_events(context.library, tracked.pk)
            .filter(event_type=PLAYERGAME_STATUS_CHANGED.event_type)
            .last()
        )
        if latest is None or latest.correlation_id != self.statement:
            return None
        return status_change_event(context, tracked.pk, change.before)


def _inverse(event: LibraryEvent, created: list[uuid.UUID]) -> NewEvent | None:
    """One event's inverse; None where removal covers."""
    run_id = event.aggregate_id
    match event.event_type:
        case PLAYTHROUGH_CREATED.event_type:
            return playthrough_removed(run_id)
        case PLAYTHROUGH_STARTED.event_type | PLAYTHROUGH_COMPLETED.event_type if (
            run_id in created
        ):
            return None
        case PLAYTHROUGH_STARTED.event_type:
            return playthrough_start_voided(run_id)
        case PLAYTHROUGH_COMPLETED.event_type:
            return playthrough_completion_voided(run_id)
        case PLAYTHROUGH_REMOVED.event_type:
            return playthrough_restored(run_id)
        case PLAYTHROUGH_START_VOIDED.event_type:
            return playthrough_started(run_id, when=None, note="")
        case PLAYTHROUGH_COMPLETION_VOIDED.event_type:
            return playthrough_completed(run_id, when=None, note="")
        case PLAYERGAME_STATUS_CHANGED.event_type:
            return None
    raise RowUnreadable(
        f"Event {event.pk} ({event.event_type}) of library {event.library_id} "
        "is no event a count states."
    )
