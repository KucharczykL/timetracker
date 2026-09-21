"""The run name a session row shows."""

import uuid
from collections.abc import Sequence
from typing import NamedTuple

from games.models import PlayerSession, PlaythroughKind, UserLibrary
from games.reads.playthrough_numbering import display_name, numbered_for

type PlaythroughId = uuid.UUID
type PlayerGameId = uuid.UUID
type RunLabel = str  # e.g. "Playthrough 2"
type RunLabels = dict[PlaythroughId, RunLabel]

#: What a name cell calls a session in the bucket.
IMPORTED_HISTORY_LABEL = "Imported history"


class _LabelledRuns(NamedTuple):
    """Run names, and the runs each game holds."""

    labels: RunLabels
    by_game: dict[PlayerGameId, list[PlaythroughId]]


def _labelled_runs(
    library: UserLibrary, sessions: Sequence[PlayerSession]
) -> _LabelledRuns:
    """One query for the page, none per row.

    `numbered_for` counts across live ordinary runs alone,
    so a bucket is stamped separately.
    """
    by_game: dict[PlayerGameId, list[PlaythroughId]] = {}
    labels: RunLabels = {}
    player_game_ids = {session.playthrough.player_game_id for session in sessions}
    for run in numbered_for(library, player_game_ids):
        by_game.setdefault(run.player_game_id, []).append(run.pk)
        labels[run.pk] = display_name(run)
    for session in sessions:
        run = session.playthrough
        if run.kind == PlaythroughKind.IMPORTED_HISTORY:
            by_game.setdefault(run.player_game_id, []).append(run.pk)
            labels[run.pk] = IMPORTED_HISTORY_LABEL
    return _LabelledRuns(labels, by_game)


def every_run_label(
    library: UserLibrary, sessions: Sequence[PlayerSession]
) -> RunLabels:
    """Names for the runs of these sessions' games.

    Wider than the runs the sessions sit on, and a game
    holding one run names it too. A caller reads the names
    it wants by key; it does not walk the mapping.
    """
    return _labelled_runs(library, sessions).labels


def ambiguous_run_labels(
    library: UserLibrary, sessions: Sequence[PlayerSession]
) -> RunLabels:
    """Only the names that tell runs apart."""
    labels, by_game = _labelled_runs(library, sessions)
    return {
        run_id: label
        for run_id, label in labels.items()
        if any(len(runs) > 1 and run_id in runs for runs in by_game.values())
    }
