"""Playthrough N, derived at read time."""

from django.db.models import F, QuerySet, Window
from django.db.models.functions import RowNumber

from games.models import Playthrough, PlaythroughKind


class UnnumberedPlaythrough(ValueError):
    """A blank-named row with no display number."""


def with_display_number(
    queryset: QuerySet[Playthrough],
) -> QuerySet[Playthrough]:
    """Live ordinary rows, each with its number.

    The key is the fourth sort field, and it is what makes the order
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
    """What a screen calls this run."""
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
