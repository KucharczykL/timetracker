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


END_WAY_LABELS: Mapping[EndWay, str] = {
    EndWay.SOLD: "Sold",
    EndWay.LOST: "Lost",
    EndWay.GIVEN_AWAY: "Given away",
    EndWay.BROKEN: "Broken",
    EndWay.STOLEN: "Stolen",
}
