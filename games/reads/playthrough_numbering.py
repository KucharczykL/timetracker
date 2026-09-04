"""Playthrough N, derived at read time.

The number is stored nowhere. Its order depends on sibling rows, so a
stored column would make every endpoint change, every removal and every
creation rewrite every sibling of one tracked game -- and a rebuild would
have to reproduce that order of writes exactly.
"""

from django.db.models import F, QuerySet, Window
from django.db.models.functions import RowNumber

from games.models import Playthrough, PlaythroughKind


class UnnumberedPlaythrough(ValueError):
    """A blank-named row that carries no display number."""


def with_display_number(
    queryset: QuerySet[Playthrough],
) -> QuerySet[Playthrough]:
    """The live ordinary rows, each carrying its number.

    WHERE runs before a window function, so the filter is what keeps a
    removed row and a system row from shifting the number a player
    learned.

    The key is the fourth sort field and it is what makes the order
    total. Until #681 every row has two null bounds, and one append
    stamps one recorded_at across every row it writes, so the first
    three fields leave whole partitions as peers -- and RowNumber over
    peers follows the plan's input order, which a swap changes.
    """
    return queryset.filter(
        removed_at__isnull=True, kind=PlaythroughKind.ORDINARY
    ).annotate(
        display_number=Window(
            RowNumber(),
            partition_by="player_game",
            order_by=(
                F("started_lower").asc(nulls_last=True),
                F("completed_lower").asc(nulls_last=True),
                "created_at",
                "id",
            ),
        )
    )


def display_name(playthrough: Playthrough) -> str:
    """What a screen calls this run.

    Total: a named row needs no number, and a blank-named row without
    one is refused rather than left to raise from a missing annotation.
    """
    if playthrough.name:
        return playthrough.name
    number = getattr(playthrough, "display_number", None)
    if number is None:
        raise UnnumberedPlaythrough(
            f"Playthrough {playthrough.pk} has no name and no display "
            "number. A blank name is displayed as its number, which only "
            "with_display_number() states, and only over the live ordinary "
            "rows a number is counted across."
        )
    return f"Playthrough {number}"
