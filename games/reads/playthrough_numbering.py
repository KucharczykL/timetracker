"""Playthrough N, derived at read time."""

import uuid
from collections.abc import Iterable

from django.db.models import F, OrderBy, QuerySet, Window
from django.db.models.functions import RowNumber

from games.models import Playthrough, PlaythroughKind, UserLibrary
from games.reads.playthrough_activity import activity_clock

#: A tracked game's key, as a caller holds it.
type PlayerGameId = uuid.UUID

#: The window's order, and the screen's.
#: Another order prints 2 above 1.
DISPLAY_ORDER: tuple[OrderBy | str, ...] = (
    F("started_lower").asc(nulls_last=True),
    F("completed_lower").asc(nulls_last=True),
    "created_at",
    "id",
)


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
            order_by=DISPLAY_ORDER,
        )
    )


def numbered_for(
    library: UserLibrary, player_game_ids: Iterable[PlayerGameId]
) -> QuerySet[Playthrough]:
    """Every live ordinary run of these tracked games, numbered.

    Takes games, not a queryset: the partition is whatever
    the caller selected, so a narrowed one numbers its row 1
    and nothing marks it. Scoped on the row and its parent
    alike, so the partition matches `live_ordinary_runs`,
    which a removal counts across. Carries the condition
    aliases, which Game detail reads.
    """
    return with_display_number(
        Playthrough.objects.filter(
            library=library,
            player_game__library=library,
            player_game_id__in=list(player_game_ids),
        ).annotated_for_filtering(activity_clock(library))
    ).order_by(*DISPLAY_ORDER)


def is_numbered(playthrough: Playthrough) -> bool:
    """Whether a number is counted across this row."""
    return (
        playthrough.removed_at is None and playthrough.kind == PlaythroughKind.ORDINARY
    )


def display_name(playthrough: Playthrough, *, fallback: str | None = None) -> str:
    """What a screen calls this run.

    `fallback` renders a row no number is counted across.
    """
    if playthrough.name:
        return playthrough.name
    number = getattr(playthrough, "display_number", None)
    if number is None:
        #: The row says which of the two it is, so a
        #: fallback excuses only the row it was written
        #: for. A numbered row reaching here is a caller
        #: that skipped with_display_number(), which is
        #: the error the fallback must not swallow.
        if fallback is not None and not is_numbered(playthrough):
            return fallback
        raise UnnumberedPlaythrough(
            f"Playthrough {playthrough.pk} has no name and no display "
            "number. A blank name is displayed as its number, which only "
            "with_display_number() states, and only over the live ordinary "
            "rows a number is counted across. A caller that means to render "
            "a removed row or a bucket states a fallback; over the rows a "
            "number is counted across, annotate the queryset."
        )
    return f"Playthrough {number}"
