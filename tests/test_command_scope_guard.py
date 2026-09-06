"""Refusing a resolve that states no scope."""

import ast
from pathlib import Path

#: Commands only: a view uses owned_or_404.
GUARDED_PACKAGE = "games/commands"
#: The module holding the resolve itself.
EXEMPT = "games/commands/scope.py"
#: A verb stating a wider scope itself.
SCOPING_VERBS = frozenset({"visible_to"})
#: A path, and why.
ALLOWED_FILES: dict[str, str] = {}

REPORT = (
    "{path}:{line} resolves a row with .get() on a manager that states no "
    "scope. A command scopes a resolve by calling games.commands.scope."
    "library_row, which applies library=context.library so no caller holds a "
    "library to forget. A read wider than one library names a verb from "
    "SCOPING_VERBS instead."
)

MANAGER_ROOTS = frozenset({"objects", "_default_manager"})


def attribute_chain(node: ast.expr) -> list[str]:
    """Attribute names from a chain, innermost last."""
    names: list[str] = []
    current: ast.expr | None = node
    while current is not None:
        if isinstance(current, ast.Call):
            current = current.func
        elif isinstance(current, ast.Attribute):
            names.append(current.attr)
            current = current.value
        else:
            current = None
    return names


def unscoped_resolves(source: str, path: str) -> list[str]:
    """Manager .get() calls that name no scope."""
    reports = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        called = node.func
        if not isinstance(called, ast.Attribute) or called.attr != "get":
            continue
        chain = attribute_chain(called.value)
        if not MANAGER_ROOTS.intersection(chain):
            continue
        if SCOPING_VERBS.intersection(chain):
            continue
        reports.append(REPORT.format(path=path, line=node.lineno))
    return reports


def test_the_guard_reports_a_bare_manager_get() -> None:
    """Proved on a string, not a file."""
    reports = unscoped_resolves("row = Game.objects.get(pk=wanted)\n", "x.py")
    assert len(reports) == 1
    assert "x.py:1" in reports[0]
    assert "library_row" in reports[0]


def test_the_guard_accepts_a_scoping_verb() -> None:
    source = "row = Game.objects.visible_to(library).get(pk=wanted)\n"
    assert unscoped_resolves(source, "x.py") == []


def test_the_guard_passes_a_mapping_get() -> None:
    """The chain, not the method name."""
    assert unscoped_resolves("answer = ANSWERS.get(kind)\n", "x.py") == []


def test_the_guard_passes_a_filter_that_resolves_nothing() -> None:
    source = "row = PlayerGame.objects.filter(library=owned).first()\n"
    assert unscoped_resolves(source, "x.py") == []


def test_no_command_resolves_without_a_scope() -> None:
    root = Path(__file__).resolve().parent.parent
    directory = root / GUARDED_PACKAGE
    assert directory.is_dir(), f"{GUARDED_PACKAGE}/ is in the walk but is not one"
    reports: list[str] = []
    for path in sorted(directory.rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        if relative == EXEMPT or relative in ALLOWED_FILES:
            continue
        reports.extend(unscoped_resolves(path.read_text(encoding="utf-8"), relative))
    assert not reports, "\n".join(reports)


def test_every_exemption_names_a_file_that_exists() -> None:
    """An exemption outliving its file."""
    root = Path(__file__).resolve().parent.parent
    missing = [path for path in ALLOWED_FILES if not (root / path).is_file()]
    assert not missing, missing
