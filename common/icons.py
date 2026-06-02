import functools
from pathlib import Path

_ICON_DIR = (
    Path(__file__).resolve().parent.parent / "games" / "templates" / "cotton" / "icon"
)


@functools.lru_cache(maxsize=1)
def _load_icons() -> dict[str, str]:
    """Load all icon HTML files into a dict.

    Cached so files are read once per process lifetime.
    Delegation (e.g. nintendo-3ds -> nintendo) is handled by
    both files containing identical SVG content.
    """
    icons: dict[str, str] = {}
    for filepath in _ICON_DIR.glob("*.html"):
        name = filepath.stem
        icons[name] = filepath.read_text()
    return icons


def get_icon(name: str) -> str:
    """Return the HTML for an icon by name. Falls back to 'unspecified'."""
    icons = _load_icons()
    return icons.get(name, icons.get("unspecified", ""))
