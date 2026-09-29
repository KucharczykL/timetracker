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
}
