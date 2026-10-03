"""The conversion's review words and labels."""

from collections.abc import Mapping
from enum import StrEnum
from typing import Final

ORIGIN: Final = "conversion"


class Category(StrEnum):
    """The conversion's review words."""

    UNKNOWN_PRICE = "unknown_price"
    EPIC_FREE = "epic_free"
    RENTAL = "rental"
    CREATED_RELEASE = "created_release"
    DEMO_EDITION = "demo_edition"
    MIXED_INFINITE = "mixed_infinite"
    ADDON_GAME = "addon_game"
    QUANTIZED = "quantized"
    BUNDLE_SPLIT = "bundle_split"
    HAND_RECORDED_COPY = "hand_recorded_copy"
    OWN_COPY_FALLBACK = "own_copy_fallback"
    RENAMED_ADDON = "renamed_addon"


REVIEW_LABELS: Final[Mapping[Category, str]] = {
    Category.UNKNOWN_PRICE: "Unknown price",
    Category.EPIC_FREE: "Free on Epic",
    Category.QUANTIZED: "Rounded price",
    Category.RENTAL: "Rentals",
    Category.CREATED_RELEASE: "New releases",
    Category.DEMO_EDITION: "Demos",
    Category.MIXED_INFINITE: "Mixed infinite",
    Category.ADDON_GAME: "DLC as games",
    Category.BUNDLE_SPLIT: "Split bundles",
    Category.HAND_RECORDED_COPY: "Copies recorded twice",
    Category.OWN_COPY_FALLBACK: "Passes without a game copy",
    Category.RENAMED_ADDON: "Renamed DLC",
}

#: The words an event can carry.
REVIEWED: Final[tuple[Category, ...]] = tuple(REVIEW_LABELS)
