"""Refusing a day off the process clock."""

import ast
from collections.abc import Mapping
from pathlib import Path
from typing import NamedTuple

import pytest

#: Tests too: process-clock fixtures fail in CI.
GUARDED_PACKAGES = (
    "games",
    "common",
    "timetracker",
    "contrib",
    "scripts",
    "tests",
    "e2e",
)

#: Active zone's day unless a zone stated.
ZONED_CLOCK_NAMES = frozenset({"localdate", "localtime"})

#: The process zone's day; takes no zone.
TODAY_NAMES = frozenset({"today"})

CLOCK_NAMES = ZONED_CLOCK_NAMES | TODAY_NAMES

#: Their `.date()` is UTC or naive.
NOW_NAMES = frozenset({"now"})

#: Modules whose attributes are the clock.
CLOCK_MODULES = frozenset({"timezone", "date", "datetime"})

type ModulePath = str  # e.g. "tests/calendar_days.py"
type FunctionName = str  # qualified, e.g. "Clock.today" or "<module>"
type Reason = str


class AllowedFunction(NamedTuple):
    path: ModulePath
    function: FunctionName


class Exemption(NamedTuple):
    """Why, and how many reads it covers."""

    reason: Reason
    reads: int = 1


ALLOWED_FUNCTIONS: dict[AllowedFunction, Exemption] = {
    AllowedFunction("games/views/general.py", "global_current_year"): Exemption(
        "a viewer with no library has no calendar to ask"
    ),
    AllowedFunction("games/checks.py", "<module>"): Exemption(
        "names the clock's factories to refuse them as a field default",
        reads=4,
    ),
    AllowedFunction("tests/calendar_days.py", "process_day"): Exemption(
        "the one read of the process clock, for proving a calendar disagrees with it"
    ),
    AllowedFunction(
        "tests/test_historical_playtime_filter.py", "test_created_at"
    ): Exemption(
        "created_at is compared through Django's __date lookup, which "
        "resolves in the active zone rather than the library's calendar"
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
    "library exists to ask, add AllowedFunction({path!r}, {function!r}) to "
    "ALLOWED_FUNCTIONS with the reason."
)


class ScopeSpan(NamedTuple):
    """A definition's qualified name and lines."""

    name: FunctionName
    first_line: int
    last_line: int

    def holds(self, line: int) -> bool:
        return self.first_line <= line <= self.last_line

    @property
    def length(self) -> int:
        return self.last_line - self.first_line


class ClockRead(NamedTuple):
    line: int
    function: FunctionName


def _scope_spans(body: list[ast.stmt], prefix: FunctionName = "") -> list[ScopeSpan]:
    spans = []
    for node in body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            name = f"{prefix}{node.name}"
            spans.append(ScopeSpan(name, node.lineno, node.end_lineno or node.lineno))
            spans.extend(_scope_spans(node.body, f"{name}."))
        else:
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.stmt):
                    spans.extend(_scope_spans([child], prefix))
    return spans


def _holding_scope(spans: list[ScopeSpan], line: int) -> FunctionName:
    """The innermost definition around a line."""
    holding = [span for span in spans if span.holds(line)]
    if not holding:
        return "<module>"
    return min(holding, key=lambda span: span.length).name


def _imported_names(tree: ast.AST) -> dict[str, str]:
    """Local import names to imported names."""
    names: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom | ast.Import):
            for alias in node.names:
                original = alias.name.rsplit(".", 1)[-1]
                names[alias.asname or original] = original
    return names


def _called_name(called: ast.expr, imported: Mapping[str, str]) -> str | None:
    if isinstance(called, ast.Attribute):
        return called.attr
    if isinstance(called, ast.Name):
        return imported.get(called.id, called.id)
    return None


def _states_a_zone(call: ast.Call) -> bool:
    """An instant alone is still the clock."""
    return len(call.args) >= 2 or any(
        keyword.arg == "timezone" for keyword in call.keywords
    )


def _reads_the_clock(call: ast.Call, imported: Mapping[str, str]) -> bool:
    name = _called_name(call.func, imported)
    if name in ZONED_CLOCK_NAMES:
        return not _states_a_zone(call)
    if name in TODAY_NAMES:
        return not (call.args or call.keywords)
    #: `now().date()`, not `now(zone).date()`.
    if (
        name == "date"
        and isinstance(call.func, ast.Attribute)
        and not (call.args or call.keywords)
        and isinstance(inner := call.func.value, ast.Call)
        and _called_name(inner.func, imported) in NOW_NAMES
    ):
        return not (inner.args or inner.keywords)
    return False


def _names_a_clock_module(node: ast.expr, imported: Mapping[str, str]) -> bool:
    if isinstance(node, ast.Attribute):
        return node.attr in CLOCK_MODULES
    if isinstance(node, ast.Name):
        return imported.get(node.id, node.id) in CLOCK_MODULES
    return False


def _refers_to_the_clock(node: ast.expr, imported: Mapping[str, str]) -> bool:
    """A clock factory named, not called."""
    if isinstance(node, ast.Attribute):
        return node.attr in CLOCK_NAMES and _names_a_clock_module(node.value, imported)
    if isinstance(node, ast.Name):
        return node.id in imported and imported[node.id] in CLOCK_NAMES
    return False


def clock_reads(source: str) -> list[ClockRead]:
    """Every clock-day call or reference."""
    tree = ast.parse(source)
    spans = _scope_spans(tree.body)
    imported = _imported_names(tree)
    called = {id(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
    reads = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            found = _reads_the_clock(node, imported)
        elif isinstance(node, ast.Attribute | ast.Name) and id(node) not in called:
            found = _refers_to_the_clock(node, imported)
        else:
            continue
        if found:
            reads.append(ClockRead(node.lineno, _holding_scope(spans, node.lineno)))
    return reads


def clock_calls(
    source: str,
    path: ModulePath,
    allowed: Mapping[AllowedFunction, Exemption] = ALLOWED_FUNCTIONS,
) -> list[str]:
    """Reports for reads no exemption covers."""
    return [
        REPORT.format(path=path, line=read.line, function=read.function)
        for read in clock_reads(source)
        if AllowedFunction(path, read.function) not in allowed
    ]


def test_the_guard_reports_a_call() -> None:
    """Proved on a string, not a file."""
    reports = clock_calls("def view():\n    return localdate()\n", "x.py")

    assert len(reports) == 1
    assert "x.py:2 in view()" in reports[0]
    assert "calendar_today(library)" in reports[0]


def test_the_guard_reports_the_attribute_spelling() -> None:
    reports = clock_calls("def view():\n    return timezone.localdate()\n", "x.py")

    assert len(reports) == 1


def test_the_guard_reports_an_aliased_import() -> None:
    source = (
        "from django.utils.timezone import localdate as day\n"
        "def view():\n"
        "    return day()\n"
    )

    assert len(clock_calls(source, "x.py")) == 1


@pytest.mark.parametrize(
    "expression",
    [
        "timezone.localtime()",
        "timezone.localtime(timezone.now())",
        "timezone.localdate(timezone.now())",
        "timezone.localdate(value=instant)",
        "timezone.now().date()",
        "datetime.now().date()",
        "datetime.date.today()",
    ],
)
def test_the_guard_reports_every_spelling_of_the_active_day(expression) -> None:
    source = f"def view():\n    return {expression}\n"

    assert len(clock_calls(source, "x.py")) == 1, expression


def test_the_guard_reports_a_clock_named_rather_than_called() -> None:
    source = "def view():\n    factory = date.today\n    return factory()\n"

    assert len(clock_calls(source, "x.py")) == 1


def test_the_guard_passes_an_attribute_of_no_clock_module() -> None:
    """A domain field may be `today`."""
    source = "def view(clock):\n    return clock.today\n"

    assert clock_calls(source, "x.py") == []


def test_the_guard_names_the_innermost_function() -> None:
    source = "def outer():\n    def inner():\n        return date.today()\n"

    assert "in outer.inner()" in clock_calls(source, "x.py")[0]


def test_the_guard_qualifies_a_method() -> None:
    source = "class View:\n    def get(self):\n        return localdate()\n"

    assert "in View.get()" in clock_calls(source, "x.py")[0]


@pytest.mark.parametrize(
    "expression",
    [
        "datetime.now(tz=ZoneInfo(zone)).date()",
        "datetime.now(UTC).date()",
        "timezone.now().astimezone(ZoneInfo(zone)).date()",
        "timezone.localtime(instant, zone)",
        "timezone.localdate(instant, timezone=zone)",
    ],
)
def test_the_guard_passes_a_day_built_from_a_stated_zone(expression) -> None:
    """An explicit zone is the caller's answer."""
    source = f"def read():\n    return {expression}\n"

    assert clock_calls(source, "x.py") == []


def test_the_guard_passes_a_stated_day() -> None:
    """A test may name a day."""
    source = "def test_x():\n    return date(2026, 3, 5)\n"

    assert clock_calls(source, "tests/test_x.py") == []


def test_the_guard_reports_a_read_in_a_test_package() -> None:
    source = "def test_x():\n    return timezone.localdate()\n"

    assert len(clock_calls(source, "tests/test_x.py")) == 1


def test_the_walk_reaches_the_test_packages() -> None:
    """Scope asserted, not assumed."""
    reached = {path for path, _ in _first_party_files()}

    assert "tests/test_calendar_clock_guard.py" in reached
    assert "e2e/test_date_range_picker_e2e.py" in reached


def test_an_allowed_function_is_passed() -> None:
    source = "def global_current_year(request):\n    return localdate().year\n"

    assert clock_calls(source, "games/views/general.py") == []


def test_an_allowed_function_of_the_same_name_elsewhere_is_reported() -> None:
    source = (
        "class Other:\n"
        "    def global_current_year(self):\n"
        "        return localdate().year\n"
    )

    assert len(clock_calls(source, "games/views/general.py")) == 1


def _first_party_files() -> list[tuple[ModulePath, str]]:
    """Every guarded module, path and source."""
    root = Path(__file__).resolve().parent.parent
    files = []
    for package in GUARDED_PACKAGES:
        directory = root / package
        assert directory.is_dir(), f"{package}/ is in the walk but is not a directory"
        for path in sorted(directory.rglob("*.py")):
            if path.is_relative_to(root / "games" / "migrations"):
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


def test_every_exemption_covers_exactly_the_reads_it_states() -> None:
    """Stale entry, or a read hiding."""
    sources = dict(_first_party_files())
    for entry, exemption in ALLOWED_FUNCTIONS.items():
        assert entry.path in sources, f"{entry} names a file the walk does not reach"
        reads = [
            read
            for read in clock_reads(sources[entry.path])
            if read.function == entry.function
        ]
        assert len(reads) == exemption.reads, (
            f"{entry} states {exemption.reads} reads and covers {len(reads)}"
        )
