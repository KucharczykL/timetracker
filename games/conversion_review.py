"""The conversion's review words and labels."""

from typing import Final

from django.db import models

ORIGIN: Final = "conversion"


class Category(models.TextChoices):
    """Words stored events carry; never remove one."""

    UNKNOWN_PRICE = "unknown_price", "Unknown price"
    EPIC_FREE = "epic_free", "Free on Epic"
    QUANTIZED = "quantized", "Rounded price"
    RENTAL = "rental", "Rentals"
    CREATED_RELEASE = "created_release", "New releases"
    DEMO_EDITION = "demo_edition", "Demos"
    MIXED_INFINITE = "mixed_infinite", "Mixed infinite"
    ADDON_GAME = "addon_game", "DLC as games"
    BUNDLE_SPLIT = "bundle_split", "Split bundles"
    HAND_RECORDED_COPY = "hand_recorded_copy", "Copies recorded twice"
    OWN_COPY_FALLBACK = "own_copy_fallback", "Passes without a game copy"
    RENAMED_ADDON = "renamed_addon", "Renamed DLC"
