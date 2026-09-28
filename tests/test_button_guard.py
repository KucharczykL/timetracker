"""Every button is a ControlButton, or allowed."""

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ROOTS = ("common", "games")

#: Not box buttons: items, glyphs, chips.
ALLOWED = {
    ("common/components/primitives.py", "ControlButton.render"),
    ("common/components/primitives.py", "_popover_reveal"),
    ("common/components/primitives.py", "_popover_html"),
    ("common/components/primitives.py", "TruncatedText"),
    ("common/components/primitives.py", "Pill"),
    ("common/components/custom_elements.py", "DropdownPostItem"),
    ("common/components/custom_elements.py", "DropdownActionItem.render"),
    ("common/components/custom_elements.py", "DropdownCheckItem"),
    ("common/components/custom_elements.py", "ListboxPanel"),
    ("common/components/search_field.py", "_mode_row"),
    ("common/components/filters.py", "chip_templates"),
    ("common/components/navigation.py", "AvatarButton"),
    ("common/components/temporal_field.py", "_disclosure"),
    #: A field that opens a grid, not a box button.
    ("common/components/icon_picker.py", "IconPicker"),
}


def _button_names(tree: ast.Module) -> set[str]:
    """Local names bound to Button."""
    names = {"Button"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
            "common.components"
        ):
            names |= {
                alias.asname or alias.name
                for alias in node.names
                if alias.name == "Button"
            }
    return names


def _raw_buttons(path: Path) -> list[tuple[str, int]]:
    tree = ast.parse(path.read_text())
    names = _button_names(tree)
    found: list[tuple[str, int]] = []

    def visit(node: ast.AST, scope: tuple[str, ...]) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            scope = (*scope, node.name)
        if isinstance(node, ast.Call):
            function = node.func
            called = (isinstance(function, ast.Name) and function.id in names) or (
                isinstance(function, ast.Attribute) and function.attr == "Button"
            )
            element = (
                isinstance(function, ast.Name)
                and function.id == "Element"
                and bool(node.args)
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "button"
            )
            if called or element:
                found.append((".".join(scope), node.lineno))
        for child in ast.iter_child_nodes(node):
            visit(child, scope)

    visit(tree, ())
    return found


def _all_raw_buttons() -> dict[tuple[str, str], list[int]]:
    sites: dict[tuple[str, str], list[int]] = {}
    for root in ROOTS:
        for path in sorted((REPO / root).rglob("*.py")):
            relative = path.relative_to(REPO).as_posix()
            for qualname, line in _raw_buttons(path):
                sites.setdefault((relative, qualname), []).append(line)
    return sites


def test_every_raw_button_is_allowed():
    stray = {
        site: lines for site, lines in _all_raw_buttons().items() if site not in ALLOWED
    }
    assert not stray, f"use ControlButton, or name the builder in ALLOWED: {stray}"


def test_the_allow_list_names_only_live_builders():
    assert set(_all_raw_buttons()) >= ALLOWED
