"""Refusing "delete" where a person reads it.

Nothing a person removes is destroyed: the row keeps its place and the
mark comes off again. `make vale` states the vocabulary over docs and
code comments, and a string a screen renders is neither, so this walks
the keys that carry one.
"""

import ast
from pathlib import Path

#: The packages that render for a person.
GUARDED_PACKAGES = ("games", "common")

#: Keyword arguments whose value a screen reads out.
SPOKEN_KEYWORDS = frozenset({"title", "aria_label", "label", "confirm_label"})

#: Keys of an action mapping that a screen reads out. `slot` carries
#: either an Icon node or the words beside it.
SPOKEN_KEYS = frozenset({"title", "label", "slot", "confirm_label"})

REFUSED = "delete"

REPORT = (
    "{path}:{line} states {spoken!r} for a person to read. Nothing a "
    "person removes is destroyed, so the word is Remove; `delete` is "
    "Django's word and SQL's. An identifier, an icon slug, a data "
    "attribute or an HTTP verb may keep it -- this reads only the keys "
    "a screen speaks."
)


def _refused(value: ast.expr) -> str | None:
    """The string, where it names the refused word."""
    if (
        isinstance(value, ast.Constant)
        and isinstance(value.value, str)
        and REFUSED in value.value.casefold()
    ):
        return value.value
    return None


def spoken_strings(source: str, path: str) -> list[str]:
    """Every rendered string that states the refused word."""
    reports: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.keyword) and node.arg in SPOKEN_KEYWORDS:
            spoken = _refused(node.value)
            if spoken is not None:
                reports.append(
                    REPORT.format(path=path, line=node.value.lineno, spoken=spoken)
                )
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=True):
                if not isinstance(key, ast.Constant) or key.value not in SPOKEN_KEYS:
                    continue
                spoken = _refused(value)
                if spoken is not None:
                    reports.append(
                        REPORT.format(path=path, line=value.lineno, spoken=spoken)
                    )
    return reports


def test_no_screen_says_delete():
    root = Path(__file__).resolve().parent.parent
    reports: list[str] = []
    for package in GUARDED_PACKAGES:
        for module in (root / package).rglob("*.py"):
            reports.extend(
                spoken_strings(module.read_text(), str(module.relative_to(root)))
            )
    assert not reports, "\n".join(reports)
