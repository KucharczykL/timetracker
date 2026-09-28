"""The icon snippets a platform may name."""

#: Icon slugs a platform may name.
type PlatformIcon = str  # "steam"

PLATFORM_ICONS: tuple[PlatformIcon, ...] = (
    "unspecified",
    "battlenet",
    "bethesda",
    "eaorigin",
    "egs",
    "gog",
    "itchio",
    "microsoft",
    "nintendo",
    "nintendo-3ds",
    "nintendo-switch",
    "physical",
    "physical-media",
    "playstation",
    "ps1",
    "ps3",
    "ps4",
    "ps5",
    "steam",
    "ubisoft",
    "xbox-gamepass",
    "yuzu",
)
