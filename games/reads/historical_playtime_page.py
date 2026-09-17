"""The Historical tab's rows and run names."""

import uuid
from collections.abc import Iterable, Mapping

from django.db.models import Prefetch

from games.events.dispatch import RowUnreadable
from games.models import (
    HistoricalPlaytime,
    HistoricalPlaytimeQuerySet,
    HistoricalPlaytimeRun,
    UserLibrary,
)
from games.reads.historical_playtime_records import readable_records
from games.reads.playthrough_numbering import display_name, numbered_for

type PlaythroughId = uuid.UUID
type RunLabel = str  # e.g. "Playthrough 2"
type RunLabels = Mapping[PlaythroughId, RunLabel]


def listed_records(library: UserLibrary) -> HistoricalPlaytimeQuerySet:
    """The row path; this library's runs, one query."""
    return readable_records(library).prefetch_related(
        Prefetch(
            "runs",
            queryset=HistoricalPlaytimeRun.objects.filter(library=library).order_by(
                "playthrough_id"
            ),
        )
    )


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
