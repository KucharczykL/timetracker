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
    total. A row has bounds only where #681 stated an endpoint, and one
    append stamps one recorded_at across every row it writes, so the
    first three fields still leave whole partitions as peers -- and
    RowNumber over peers follows the plan's input order, which a swap
    changes.
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


def display_name(playthrough: Playthrough, *, fallback: str | None = None) -> str:
    """What a screen calls this run.

    `fallback` is for a caller that means to render a row no number is
    counted across -- a removed one, or one whose kind is not ordinary.
    With none, the refusal stands, so a screen that simply forgot to
    number its rows still hears about it.
    """
    if playthrough.name:
        return playthrough.name
    number = getattr(playthrough, "display_number", None)
    if number is None:
        if fallback is not None:
            return fallback
        raise UnnumberedPlaythrough(
            f"Playthrough {playthrough.pk} has no name and no display "
            "number. A blank name is displayed as its number, which only "
            "with_display_number() states, and only over the live ordinary "
            "rows a number is counted across. A caller that means to render "
            "such a row states a fallback."
        )
    return f"Playthrough {number}"
