"""The run name a session row shows."""

import uuid
from collections.abc import Sequence

from games.models import PlayerSession, PlaythroughKind, UserLibrary
from games.reads.playthrough_numbering import display_name, numbered_for

type PlaythroughId = uuid.UUID
type RunLabel = str  # e.g. "Playthrough 2"
type RunLabels = dict[PlaythroughId, RunLabel]

#: What a name cell calls a session in the bucket.
IMPORTED_HISTORY_LABEL = "Imported history"


def _labelled_runs(
    library: UserLibrary, sessions: Sequence[PlayerSession]
) -> RunLabels:
    """One query for the page, none per row.

    `numbered_for` counts across live ordinary runs alone,
    so a bucket is stamped separately.
    """
    labels: RunLabels = {}
    player_game_ids = {session.playthrough.player_game_id for session in sessions}
    for run in numbered_for(library, player_game_ids):
        labels[run.pk] = display_name(run)
    for session in sessions:
        run = session.playthrough
        if run.kind == PlaythroughKind.IMPORTED_HISTORY:
            labels[run.pk] = IMPORTED_HISTORY_LABEL
    return labels


def every_run_label(
    library: UserLibrary, sessions: Sequence[PlayerSession]
) -> RunLabels:
    """Run names for these sessions' games.

    Wider than the runs the sessions sit on, and a game
    holding one run names it too. A caller reads the names
    it wants by key; it does not walk the mapping.
    """
    return _labelled_runs(library, sessions)
