"""The conversion's review words and where each leads."""

from collections.abc import Mapping
from enum import StrEnum
from typing import Final, NamedTuple

ORIGIN: Final = "conversion"


class Category(StrEnum):
    """A review list a planned copy joins."""

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
    SKIPPED_REMOVED_GAME = "skipped_removed_game"


class ReviewTarget(StrEnum):
    """The list a category's link opens."""

    PURCHASES = "purchases"
    ENTRIES = "entries"


class ReviewWords(NamedTuple):
    label: str
    reason: str
    target: ReviewTarget


REVIEW_WORDS: Final[Mapping[Category, ReviewWords]] = {
    Category.UNKNOWN_PRICE: ReviewWords(
        "Unknown price",
        "Owned, but recorded without a price.",
        ReviewTarget.PURCHASES,
    ),
    Category.EPIC_FREE: ReviewWords(
        "Free on Epic",
        "Owned on Epic without a price, so recorded as free.",
        ReviewTarget.PURCHASES,
    ),
    Category.QUANTIZED: ReviewWords(
        "Rounded price",
        "The price had more than two decimal places.",
        ReviewTarget.PURCHASES,
    ),
    Category.RENTAL: ReviewWords(
        "Rentals",
        "Recorded as rented; state when the rental ended.",
        ReviewTarget.ENTRIES,
    ),
    Category.CREATED_RELEASE: ReviewWords(
        "New releases",
        "The conversion added a release for the purchase's platform.",
        ReviewTarget.ENTRIES,
    ),
    Category.DEMO_EDITION: ReviewWords(
        "Demos",
        "Recorded as a copy of a demo edition.",
        ReviewTarget.ENTRIES,
    ),
    Category.MIXED_INFINITE: ReviewWords(
        "Mixed infinite",
        "Some purchases of the game were infinite and some were not.",
        ReviewTarget.ENTRIES,
    ),
    Category.ADDON_GAME: ReviewWords(
        "DLC as games",
        "A DLC purchase became a copy of its own DLC game.",
        ReviewTarget.ENTRIES,
    ),
    Category.BUNDLE_SPLIT: ReviewWords(
        "Split bundles",
        "One purchase of several games, split by cents.",
        ReviewTarget.ENTRIES,
    ),
    Category.HAND_RECORDED_COPY: ReviewWords(
        "Copies recorded twice",
        "A copy recorded by hand sits beside a converted one.",
        ReviewTarget.ENTRIES,
    ),
    Category.OWN_COPY_FALLBACK: ReviewWords(
        "Passes without a game copy",
        "No owned copy of the base game, so the pass got its own.",
        ReviewTarget.ENTRIES,
    ),
    Category.RENAMED_ADDON: ReviewWords(
        "Renamed DLC",
        "The DLC's name was taken, so the game's name leads it.",
        ReviewTarget.ENTRIES,
    ),
}

#: The words an event can carry.
REVIEWED: Final[tuple[Category, ...]] = tuple(REVIEW_WORDS)
