"""The run names a record row prints."""

from collections.abc import Iterable, Mapping

from games.events.dispatch import RowUnreadable
from games.ids import PlaythroughId
from games.models import HistoricalPlaytime, UserLibrary
from games.reads.playthrough_numbering import display_name, numbered_for

type RunLabel = str  # e.g. "Playthrough 2"
type RunLabels = Mapping[PlaythroughId, RunLabel]


def run_labels_for(
    library: UserLibrary, records: Iterable[HistoricalPlaytime]
) -> dict[PlaythroughId, RunLabel]:
    """Live ordinary runs' names, numbered per game."""
    return {
        run.pk: display_name(run)
        for run in numbered_for(library, {record.player_game_id for record in records})
    }


def record_run_labels(record: HistoricalPlaytime, labels: RunLabels) -> list[RunLabel]:
    """The record's run names; a missing one is a defect."""
    names = []
    for run in record.runs.all():
        name = labels.get(run.playthrough_id)
        if name is None:
            raise RowUnreadable(
                f"Historical playtime record {record.pk} in library "
                f"{record.library_id} names playthrough {run.playthrough_id}, "
                f"which is no live ordinary run of player game "
                f"{record.player_game_id}."
            )
        names.append(name)
    return names
