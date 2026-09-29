"""Refusing a day off the process clock."""

import ast
from pathlib import Path
from typing import NamedTuple

#: `tests` and `e2e` are guarded too, since #1221 moved the readers onto the
#: library's calendar and left every test seeding off the process clock. Such
#: a test agrees with the code it exercises for 22 hours a day and disagrees
#: by a day for the other two, so CI fails on whichever PR happens to run
#: between 22:00 and 00:00 UTC rather than on the commit that caused it.
#: A test states a fixed day or asks the calendar; it never asks the clock.
GUARDED_PACKAGES = (
    "games",
    "common",
    "timetracker",
    "contrib",
    "scripts",
    "tests",
    "e2e",
)

#: Names answering a day from the active zone.
CLOCK_NAMES = frozenset({"localdate", "today"})

#: `<path>:<function>`, and why the clock is right there.
ALLOWED_FUNCTIONS: dict[str, str] = {
    "games/views/general.py:global_current_year": (
        "a viewer with no library has no calendar to ask"
    ),
    "tests/test_navbar_calendar_day.py:elsewhere": (
        "picks the zone that disagrees with the process clock, so it must "
        "read that clock to know which one does"
    ),
    "tests/test_playthrough_companion_status.py:"
    "test_a_start_states_the_librarys_day_not_the_processs": (
        "asserts the two clocks answer differently, which is unsayable "
        "without reading both"
    ),
    "tests/test_calendar_days.py:displaced": (
        "picks the zone that disagrees with the process clock, so it must "
        "read that clock to know which one does"
    ),
    "tests/test_calendar_days.py:test_the_fixture_puts_the_clocks_a_day_apart": (
        "asserts the two clocks answer differently, which is what makes "
        "every other assertion in that file prove something"
    ),
    "tests/test_historical_playtime_filter.py:test_created_at": (
        "created_at is compared through Django's __date lookup, which "
        "resolves in the active zone rather than the library's calendar"
    ),
    "e2e/test_date_range_picker_e2e.py:_pinned_today": (
        "the browser context is pinned to settings.TIME_ZONE, so the day "
        "the picker computes is the active zone's and no library is involved"
    ),
}

REPORT = (
    "{path}:{line} in {function}() reads a day from the process clock. "
    "A day belongs to the library's calendar: ask "
    "games.reads.calendar.calendar_today(library), or "
    "games.views.general.request_calendar_today(request, library) where a "
    "request is at hand. In a test, state a fixed day -- date(2026, 3, 5) -- "
    "or seed against the calendar with tests/calendar_days.py's "
    "library_noon(library); a fixture built on the process clock agrees with "
    "the reader for most of the day and is one day out for the rest. If no "
    "library exists to ask, add '{path}:{function}' to ALLOWED_FUNCTIONS "
    "with the reason."
)


class FunctionSpan(NamedTuple):
    """One definition, and the lines it covers."""

    name: str
    first_line: int
    last_line: int

    def holds(self, line: int) -> bool:
        return self.first_line <= line <= self.last_line

    @property
    def length(self) -> int:
        return self.last_line - self.first_line


def _function_spans(tree: ast.AST) -> list[FunctionSpan]:
    return [
        FunctionSpan(node.name, node.lineno, node.end_lineno or node.lineno)
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    ]


def _holding_function(spans: list[FunctionSpan], line: int) -> str:
    """The innermost function around a line."""
    holding = [span for span in spans if span.holds(line)]
    if not holding:
        return "<module>"
    return min(holding, key=lambda span: span.length).name


def _clock_name(called: ast.expr) -> str | None:
    if isinstance(called, ast.Attribute):
        return called.attr
    if isinstance(called, ast.Name):
        return called.id
    return None


def clock_calls(source: str, path: str) -> list[str]:
    """Every call answering today from the clock."""
    tree = ast.parse(source)
    spans = _function_spans(tree)
    reports = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        #: A stated zone is not the clock.
        if node.args or node.keywords:
            continue
        if _clock_name(node.func) not in CLOCK_NAMES:
            continue
        function = _holding_function(spans, node.lineno)
        if f"{path}:{function}" in ALLOWED_FUNCTIONS:
            continue
        reports.append(REPORT.format(path=path, line=node.lineno, function=function))
    return reports


def test_the_guard_reports_a_call() -> None:
    """Proved on a string, not a file."""
    reports = clock_calls("def view():\n    return localdate()\n", "x.py")

    assert len(reports) == 1
    assert "x.py:2 in view()" in reports[0]
    assert "calendar_today(library)" in reports[0]


def test_the_guard_reports_the_attribute_spelling() -> None:
    reports = clock_calls("def view():\n    return timezone.localdate()\n", "x.py")

    assert len(reports) == 1


def test_the_guard_names_the_innermost_function() -> None:
    source = "def outer():\n    def inner():\n        return date.today()\n"

    assert "in inner()" in clock_calls(source, "x.py")[0]


def test_the_guard_passes_a_day_built_from_a_stated_zone() -> None:
    """An explicit zone is the caller's answer."""
    source = "def read():\n    return datetime.now(tz=ZoneInfo(zone)).date()\n"

    assert clock_calls(source, "x.py") == []


def test_the_guard_passes_a_name_that_is_never_called() -> None:
    """`games/checks.py` names it without calling it."""
    source = "FACTORIES = frozenset({timezone.localdate, date.today})\n"

    assert clock_calls(source, "x.py") == []


def test_the_guard_passes_a_stated_day() -> None:
    """A test may name a day. It may not ask what day it is."""
    source = "def test_x():\n    return date(2026, 3, 5)\n"

    assert clock_calls(source, "tests/test_x.py") == []


def test_the_walk_reaches_the_test_packages() -> None:
    """The scope is the guard here, so it is asserted and not assumed.

    #1221 moved the readers onto the calendar and left the tests on the
    process clock, which is why this walk covers them at all. Dropping
    either package would restore a suite that fails for two hours a day
    on whichever PR runs in the window, so it fails here instead.
    """
    reached = {path for path, _ in _first_party_files()}

    assert "tests/test_calendar_clock_guard.py" in reached
    assert "e2e/test_date_range_picker_e2e.py" in reached


def test_an_allowed_function_is_passed() -> None:
    source = "def global_current_year(request):\n    return localdate().year\n"

    assert clock_calls(source, "games/views/general.py") == []


def _first_party_files() -> list[tuple[str, str]]:
    """Every guarded module, path and source."""
    root = Path(__file__).resolve().parent.parent
    files = []
    for package in GUARDED_PACKAGES:
        directory = root / package
        assert directory.is_dir(), f"{package}/ is in the walk but is not a directory"
        for path in sorted(directory.rglob("*.py")):
            if "migrations" in path.parts:
                continue
            files.append(
                (path.relative_to(root).as_posix(), path.read_text(encoding="utf-8"))
            )
    return files


def test_no_first_party_module_reads_a_day_from_the_clock() -> None:
    reports: list[str] = []
    for relative, source in _first_party_files():
        reports.extend(clock_calls(source, relative))
    assert not reports, "\n".join(reports)


def test_every_allowed_function_still_reads_the_clock() -> None:
    """An entry the walk no longer needs."""
    sources = dict(_first_party_files())
    for entry in ALLOWED_FUNCTIONS:
        path, function = entry.rsplit(":", 1)
        assert path in sources, f"{entry} names a file the walk does not reach"
        spans = _function_spans(ast.parse(sources[path]))
        assert any(span.name == function for span in spans), (
            f"{entry} names a function {path} no longer defines"
        )
        without_the_allowlist = [
            report
            for report in clock_calls(sources[path], f"{path}-unexempt")
            if f"in {function}()" in report
        ]
        assert without_the_allowlist, (
            f"{entry} exempts a function that no longer reads the clock"
        )
