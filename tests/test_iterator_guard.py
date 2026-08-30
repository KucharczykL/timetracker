"""Refusing `QuerySet.iterator()` anywhere in first-party code.

It opens a server-side cursor, which belongs to one connection: a pooler in
transaction or statement pooling mode hands the next FETCH a different one and
the read fails. `DISABLE_SERVER_SIDE_CURSORS` turns a cursor off globally, at the
cost of holding every raw row in the process. Paging by key needs neither.

`tests/` and `e2e/` are outside the walk. They are not the path a pooler serves.
"""

import ast
from pathlib import Path

GUARDED_PACKAGES = ("games", "common", "timetracker", "contrib", "scripts")
CURSOR_METHODS = frozenset({"iterator", "aiterator"})

#: Repository-relative path -> the reason it is exempt. `RawQuerySet.iterator()`
#: (django/db/models/query.py:2216) yields rows and opens no cursor, and a syntax
#: tree cannot tell it from a queryset -- that is what an entry here is for.
ALLOWED_FILES: dict[str, str] = {}

REPORT = (
    "{path}:{line} calls .{method}(), which opens a server-side cursor. "
    "A transaction-pooling or statement-pooling connection pooler closes one "
    "between statements. Page by key with common.keyset.keyset_pages instead. "
    "If this is a RawQuerySet, add the file to ALLOWED_FILES with the reason."
)


def cursor_calls(source: str, path: str) -> list[str]:
    """Every call to an attribute named `iterator` or `aiterator` in `source`."""
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
    """Proved on a string, so no violation has to live in the repository."""
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
