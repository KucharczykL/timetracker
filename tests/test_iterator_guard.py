"""Refusing a server-side cursor in first-party code."""

import ast
from pathlib import Path

#: Not tests/ or e2e/: no pooler there.
GUARDED_PACKAGES = ("games", "common", "timetracker", "contrib", "scripts")
CURSOR_METHODS = frozenset({"iterator", "aiterator"})

#: A path, and why it is exempt.
#: A RawQuerySet opens no cursor.
ALLOWED_FILES: dict[str, str] = {}

REPORT = (
    "{path}:{line} calls .{method}(), which opens a server-side cursor. "
    "A transaction-pooling or statement-pooling connection pooler closes one "
    "between statements. Page by key with common.keyset.keyset_pages instead. "
    "If this is a RawQuerySet, add the file to ALLOWED_FILES with the reason."
)


def cursor_calls(source: str, path: str) -> list[str]:
    """Every call named `iterator` or `aiterator`."""
    reports = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        called = node.func
        if isinstance(called, ast.Attribute) and called.attr in CURSOR_METHODS:
            reports.append(
                REPORT.format(path=path, line=node.lineno, method=called.attr)
            )
    return reports


def test_the_guard_reports_a_call() -> None:
    """Proved on a string, not a file."""
    reports = cursor_calls(
        "rows = Game.objects.all().iterator(chunk_size=200)\n", "x.py"
    )
    assert len(reports) == 1
    assert "x.py:1" in reports[0]
    assert "common.keyset.keyset_pages" in reports[0]


def test_the_guard_passes_ordinary_source() -> None:
    assert cursor_calls("rows = list(Game.objects.all())\n", "x.py") == []


def test_no_first_party_module_opens_a_server_side_cursor() -> None:
    root = Path(__file__).resolve().parent.parent
    reports: list[str] = []
    for package in GUARDED_PACKAGES:
        directory = root / package
        assert directory.is_dir(), f"{package}/ is in the walk but is not a directory"
        for path in sorted(directory.rglob("*.py")):
            relative = path.relative_to(root).as_posix()
            if relative in ALLOWED_FILES:
                continue
            reports.extend(cursor_calls(path.read_text(encoding="utf-8"), relative))
    assert not reports, "\n".join(reports)
