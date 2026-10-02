"""What the Purchases list's acts share."""

import uuid
from collections.abc import Sequence

from django.contrib.auth.models import User
from django.db.models import QuerySet

from common.temporal_presentation import TemporalText
from games.bulk_narrowing import narrowed
from games.bulk_parts import FilterJson, PreviewColumn, Resolution
from games.bulk_sessions import lost
from games.events.dispatch import RowNotHeld
from games.filters import parse_purchase_filter
from games.models import (
    Purchase,
    UserLibrary,
    game_display_order_through,
)
from games.reads.purchases import (
    PURCHASE_PATHS,
    library_purchases,
    purchase_list_rows,
    with_valuation,
)
from games.views.purchase_menu import price_words, purchase_label
from games.writes.answers import answered
from games.writes.purchase import SUBJECT

PURCHASE_GONE = "One of the purchases is no longer available, so it was left as it is."


def purchase_scope(library: UserLibrary, filter_json: FilterJson) -> QuerySet[Purchase]:
    """The list's own read."""
    return narrowed(
        purchase_list_rows(library), library, filter_json, parse_purchase_filter
    )


def purchase_resolution(
    library: UserLibrary, keys: Sequence[uuid.UUID]
) -> Resolution[Purchase]:
    """Live purchases, with game and platform."""
    wanted = list(dict.fromkeys(keys))
    rows = tuple(
        with_valuation(library_purchases(library).filter(pk__in=wanted), library)
        .select_related(*PURCHASE_PATHS)
        .order_by(*game_display_order_through("entry__player_game__game"), "id")
    )
    return Resolution(
        rows, tuple(lost(wanted, {row.pk for row in rows}, PURCHASE_GONE))
    )


def removed_purchase(actor: User, purchase_id: uuid.UUID) -> Purchase:
    """An inverse's row, removed or not."""
    with answered(SUBJECT):
        purchase = (
            Purchase.objects.select_related(*PURCHASE_PATHS)
            .filter(library=actor.library, pk=purchase_id)
            .first()
        )
        if purchase is None:
            raise RowNotHeld(
                f"Purchase {purchase_id} is not library {actor.library.pk}'s, "
                "so the batch's inverse has no row to state a fact about."
            )
    return purchase


PURCHASE_PREVIEW: tuple[PreviewColumn[Purchase], ...] = (
    PreviewColumn("Game", lambda row, _: row.entry.player_game.game.name),
    PreviewColumn("Purchase", lambda row, _: purchase_label(row)),
    PreviewColumn("Price", lambda row, _: price_words(row), align="right"),
    PreviewColumn(
        "Purchased",
        lambda row, presentations: TemporalText(row.purchased, presentations.dates),
    ),
)
