"""Refusing a projector write that states its own scope."""

import ast
from pathlib import Path

#: Every projector; the helpers live in games/events/projection.py.
GUARDED_PACKAGE = "games/projectors"
#: A path, and why.
ALLOWED_FILES: dict[str, str] = {}

REPORT = (
    "{path}:{line} reaches a manager. A projector writes through "
    "Projector.project, Projector.amend or Projector.library_rows, which "
    "read the library off the event so no handler holds one to get wrong."
)

MANAGER_ROOTS = frozenset({"objects", "_default_manager"})


def manager_reaches(source: str, path: str) -> list[str]:
    """Every attribute access naming a manager."""
    return [
        REPORT.format(path=path, line=node.lineno)
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Attribute) and node.attr in MANAGER_ROOTS
    ]


def test_the_guard_reports_a_manager_reach() -> None:
    """Proved on a string, not a file."""
    source = "rows = self.target.model(Shelf)._default_manager.filter(pk=1)\n"

    assert manager_reaches(source, "probe.py") == [
        REPORT.format(path="probe.py", line=1)
    ]


def test_the_guard_passes_the_helpers() -> None:
    source = "self.library_rows(Shelf, event).update(day_zone=zone)\n"

    assert manager_reaches(source, "probe.py") == []


def test_no_projector_reaches_a_manager() -> None:
    root = Path(__file__).resolve().parent.parent
    reports = []
    for path in sorted((root / GUARDED_PACKAGE).rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        if relative in ALLOWED_FILES:
            continue
        reports.extend(manager_reaches(path.read_text(), relative))

    assert reports == []
