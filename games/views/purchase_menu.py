"""A purchase's words and acts."""

from collections.abc import Sequence

from common.components import (
    Div,
    DropdownDivider,
    DropdownLinkItem,
    DropdownPostItem,
    Fragment,
    Node,
    PurchaseAmount,
    RowActionMenu,
    Span,
)
from common.components.primitives import ButtonSize
from common.date_time_presentation import DateTimePresentation
from common.returns import OriginUrl, action_url
from common.temporal_presentation import TemporalText
from games.endpoints import PURCHASE_REFUND
from games.models import Purchase, PurchaseKind
from games.reads.endpoints import stated
from games.reads.purchases import ValuedRow
from games.views.submission import submission_input


def purchase_label(purchase: Purchase) -> str:
    """A game's name or Bought; else kind, name."""
    kind = PurchaseKind(purchase.kind)
    if kind is PurchaseKind.GAME:
        return purchase.name or "Bought"
    return f"{kind.label}: {purchase.name}" if purchase.name else kind.label


def price_words(purchase: Purchase) -> str:
    if purchase.amount is None:
        return "Unknown price"
    if purchase.amount == 0:
        return "Free"
    return f"{purchase.amount} {purchase.currency}"


def purchase_summary(purchase: Purchase, presentation: DateTimePresentation) -> Node:
    """Label, day, price; a refund marked."""
    refunded = stated(purchase, PURCHASE_REFUND) is not None
    return Fragment(
        purchase_label(purchase),
        " · ",
        TemporalText(purchase.purchased, presentation),
        " · ",
        price_words(purchase),
        " · refunded" if refunded else "",
    )


def purchase_line(purchase: Purchase, presentation: DateTimePresentation) -> Node:
    """Label, day, the amount."""
    return Div(class_="flex min-w-0 flex-wrap items-center gap-x-2")[
        Span()[purchase_label(purchase)],
        Span(aria_hidden="true")["·"],
        TemporalText(purchase.purchased, presentation),
        Span(aria_hidden="true")["·"],
        PurchaseAmount(purchase),
    ]


def _amount(purchase: ValuedRow) -> Node:
    if purchase.amount is None:
        return Span()["Unknown price"]
    return PurchaseAmount(purchase)


def price_line(purchase: ValuedRow) -> Node:
    """The amount, led by kind or name."""
    if purchase.kind == PurchaseKind.GAME and not purchase.name:
        return _amount(purchase)
    return Fragment(f"{purchase_label(purchase)} · ", _amount(purchase))


def price_lines(purchases: Sequence[ValuedRow]) -> Node:
    """One line per valued purchase."""
    return Div(class_="flex flex-col items-start")[
        *(Span()[price_line(purchase)] for purchase in purchases)
    ]


def purchase_items(
    purchase: Purchase, origin: OriginUrl | None, csrf_token: str
) -> list[Node]:
    """Edit, Refund unless refunded, Remove."""

    def page(route: str) -> str:
        return action_url(route, purchase.pk, origin=origin)

    refund: list[Node] = (
        []
        if stated(purchase, PURCHASE_REFUND) is not None
        else [
            DropdownPostItem(
                page("games:refund_purchase_now"),
                "Refund",
                csrf_token=csrf_token,
                hidden_fields=submission_input(),
                icon="refund",
                description="Dated today",
            )
        ]
    )
    return [
        DropdownLinkItem(page("games:edit_purchase"), "Edit purchase…", icon="edit"),
        *refund,
        DropdownDivider(),
        DropdownLinkItem(
            page("games:remove_purchase"),
            "Remove purchase…",
            icon="delete",
            danger=True,
        ),
    ]


def purchase_row_menu(
    purchase: Purchase,
    origin: OriginUrl | None,
    csrf_token: str,
    *,
    size: ButtonSize = "control",
) -> Node:
    game = purchase.entry.player_game.game
    return RowActionMenu(
        purchase_items(purchase, origin, csrf_token),
        label=f"{purchase_label(purchase)} ({game.name}) actions",
        id=f"purchase-menu-{purchase.pk}",
        size=size,
    )
