"""How an act that has ways happened."""

from collections.abc import Mapping
from enum import StrEnum


class EndWay(StrEnum):
    """Every way any endpoint admits."""

    SOLD = "sold"
    LOST = "lost"
    GIVEN_AWAY = "given_away"
    BROKEN = "broken"
    STOLEN = "stolen"
    RETURNED = "returned"
    EXPIRED = "expired"
    REVOKED = "revoked"
    REFUNDED = "refunded"
    #: Gone for a reason nobody stated.
    UNSTATED = "unstated"


#: One endpoint's ways; never empty.
type EndWays = tuple[EndWay, *tuple[EndWay, ...]]


END_WAY_LABELS: Mapping[EndWay, str] = {
    EndWay.SOLD: "Sold",
    EndWay.LOST: "Lost",
    EndWay.GIVEN_AWAY: "Given away",
    EndWay.BROKEN: "Broken",
    EndWay.STOLEN: "Stolen",
    EndWay.RETURNED: "Returned",
    EndWay.EXPIRED: "Expired",
    EndWay.REVOKED: "Revoked",
    EndWay.REFUNDED: "Refunded",
    EndWay.UNSTATED: "Not said",
}


def way_words(way: EndWay) -> str | None:
    """Its label; an unstated way says nothing."""
    return None if way == EndWay.UNSTATED else END_WAY_LABELS[way]


def ended_hint(way: EndWay) -> str:
    """Picker hint; unstated says Ended."""
    return way_words(way) or "Ended"
