from pathlib import Path

ICON_DIR = Path(__file__).resolve().parent.parent / "games" / "templates" / "icons"


def iter_icon_sources() -> list[tuple[str, str]]:
    """Return ``(name, raw_svg)`` for every icon snippet, sorted by name.

    The raw-source layer: used only by the ``gen_icons`` codegen command and the
    faithfulness test. Runtime icon rendering goes through ``get_icon_node``
    (in ``common.components.primitives``), which reads pre-built node trees and
    never touches these files or any XML parser. Kept free of any dependency on
    the generated module so the codegen command can run before it exists.
    """
    return sorted(
        (filepath.stem, filepath.read_text()) for filepath in ICON_DIR.glob("*.html")
    )
