"""The icon snippets a platform may name, and their names."""

from collections.abc import Mapping
from types import MappingProxyType

#: An icon snippet's slug.
type PlatformIcon = str  # "steam"

#: The icon of a platform stating none.
UNSPECIFIED_ICON: PlatformIcon = "unspecified"

#: A person's name for an icon.
type IconLabel = str  # "Steam"

#: Every icon a platform may name, one per glyph, in picker order.
PLATFORM_ICONS: Mapping[PlatformIcon, IconLabel] = MappingProxyType(
    {
        "unspecified": "Unspecified",
        "battlenet": "Battle.net",
        "bethesda": "Bethesda",
        "eaorigin": "EA app",
        "egs": "Epic Games Store",
        "gog": "GOG.com",
        "itchio": "itch.io",
        "microsoft": "Microsoft Store",
        "nintendo": "Nintendo",
        "nintendo-switch": "Nintendo Switch",
        "physical": "Physical media",
        "playstation": "PlayStation",
        "ps3": "PlayStation 3",
        "ps4": "PlayStation 4",
        "ps5": "PlayStation 5",
        "steam": "Steam",
        "ubisoft": "Ubisoft",
        "xbox-gamepass": "Xbox / Game Pass",
        "yuzu": "Yuzu (Switch emulator)",
    }
)

#: Slugs that once copied a glyph, and that glyph.
RETIRED_ICONS: Mapping[PlatformIcon, PlatformIcon] = MappingProxyType(
    {
        "nintendo-3ds": "nintendo",
        "physical-media": "physical",
        "ps1": "playstation",
    }
)


def canonical_icon(slug: str) -> PlatformIcon:
    """The icon a slug names, or Unspecified."""
    if slug in PLATFORM_ICONS:
        return slug
    return RETIRED_ICONS.get(slug, UNSPECIFIED_ICON)
