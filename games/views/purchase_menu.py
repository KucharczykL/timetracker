"""A purchase's words and acts."""

from common.components import Fragment, Node
from common.date_time_presentation import DateTimePresentation
from common.temporal_presentation import TemporalText
from games.endpoints import PURCHASE_REFUND
from games.models import Purchase, PurchaseKind
from games.reads.endpoints import stated


def purchase_label(purchase: Purchase) -> str:
    """Bought, or the kind and name."""
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
