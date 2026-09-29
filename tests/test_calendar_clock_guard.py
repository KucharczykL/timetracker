"""Refusing a day off the process clock.

Out of reach: `getattr`, a rebound module, ORM `__date`.
"""

import ast
from collections.abc import Mapping
from pathlib import Path
from typing import NamedTuple

import pytest

#: Tests too: process-clock fixtures are a day out some hours.
GUARDED_PACKAGES = (
    "games",
    "common",
    "timetracker",
    "contrib",
    "scripts",
    "tests",
    "e2e",
)

#: Active zone's time unless a zone stated.
ZONED_CLOCK_NAMES = frozenset({"localdate", "localtime"})

#: The process zone's day; takes no zone.
TODAY_NAMES = frozenset({"today"})

CLOCK_NAMES = ZONED_CLOCK_NAMES | TODAY_NAMES

#: An instant; its day needs a stated zone.
NOW_NAMES = frozenset({"now", "utcnow"})

#: Reading any of these off an instant reads a day.
DAY_READS = frozenset(
    {
        "date",
        "year",
        "month",
        "day",
        "isocalendar",
        "weekday",
        "isoweekday",
        "timetuple",
        "strftime",
    }
)

#: Returns an instant in its receiver's zone.
ZONE_KEEPING_CALLS = frozenset({"replace"})

#: Modules whose attributes are the clock.
CLOCK_MODULES = frozenset({"timezone", "date", "datetime"})

#: Name the process or active zone, not a stated one.
ZONELESS_ZONE_CALLS = frozenset({"get_current_timezone", "get_default_timezone"})

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
    AllowedFunction("games/checks.py", "_CLOCK_FACTORIES"): Exemption(
        "names the clock's factories to refuse them as a field default",
        reads=4,
    ),
    AllowedFunction("scripts/db_dump.py", "main"): Exemption(
        "names a dump file by the operator's day; no library is involved"
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
    "{path}:{line} in {function}() reads a day from the process clock or the "
    "active zone. A day belongs to the library's calendar: ask "
    "games.reads.calendar.calendar_today(library), or "
    "games.views.general.request_calendar_today(request, library) where a "
    "request is at hand. In a test, state a fixed day -- date(2026, 3, 5) -- "
    "or seed at tests/calendar_days.py's library_noon(library). The suite runs "
    "the process clock on another date than the calendar, so such a fixture "
    "is wrong at every hour. A filter compared through Django's __date lookup "
    "reads the active zone instead; state that zone. If nothing else can "
    "answer, add AllowedFunction({path!r}, {function!r}): "
    'Exemption("<why>", reads=<how many>) to ALLOWED_FUNCTIONS.'
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


def _assigned_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Assign) and len(node.targets) == 1:
        target = node.targets[0]
    elif isinstance(node, ast.AnnAssign):
        target = node.target
    else:
        return None
    return target.id if isinstance(target, ast.Name) else None


def _scope_spans(
    body: list[ast.stmt], prefix: FunctionName = "", *, in_function: bool = False
) -> list[ScopeSpan]:
    """Definitions, and constants outside functions."""
    spans = []
    for node in body:
        last_line = node.end_lineno or node.lineno
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            name = f"{prefix}{node.name}"
            #: A decorator runs outside, but belongs here.
            first_line = min(
                [node.lineno, *(decorator.lineno for decorator in node.decorator_list)]
            )
            spans.append(ScopeSpan(name, first_line, last_line))
            spans.extend(
                _scope_spans(
                    node.body,
                    f"{name}.",
                    in_function=not isinstance(node, ast.ClassDef),
                )
            )
            continue
        if not in_function and (assigned := _assigned_name(node)) is not None:
            spans.append(ScopeSpan(f"{prefix}{assigned}", node.lineno, last_line))
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.stmt):
                spans.extend(_scope_spans([child], prefix, in_function=in_function))
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


def _zone_argument(call: ast.Call, position: int, keyword: str) -> ast.expr | None:
    for stated in call.keywords:
        if stated.arg == keyword:
            return stated.value
    positional = [
        argument for argument in call.args if not isinstance(argument, ast.Starred)
    ]
    return positional[position] if len(positional) > position else None


class Module:
    """One module's imports, scopes and clock-bound names."""

    def __init__(self, tree: ast.Module) -> None:
        self.imported = _imported_names(tree)
        self.spans = _scope_spans(tree.body)
        self.clock_names: set[tuple[FunctionName, str]] = set()
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Assign | ast.AnnAssign)
                and (assigned := _assigned_name(node)) is not None
                and node.value is not None
                and self.is_zoneless_clock(node.value)
            ):
                self.clock_names.add((self.scope_of(node), assigned))

    def scope_of(self, node: ast.expr | ast.stmt) -> FunctionName:
        return _holding_scope(self.spans, node.lineno)

    def name_of(self, node: ast.expr) -> str | None:
        if isinstance(node, ast.Attribute):
            return node.attr
        if isinstance(node, ast.Name):
            return self.imported.get(node.id, node.id)
        return None

    def names_a_clock_module(self, node: ast.expr) -> bool:
        return self.name_of(node) in CLOCK_MODULES

    def is_a_clock_callee(self, called: ast.expr, names: frozenset[str]) -> bool:
        """`now` or `timezone.now`, never `schedule.now`."""
        if isinstance(called, ast.Attribute):
            return called.attr in names and self.names_a_clock_module(called.value)
        return self.name_of(called) in names

    def states_a_zone(self, zone: ast.expr | None) -> bool:
        """`None`, the active zone and `TIME_ZONE` state none."""
        if zone is None:
            return False
        for node in ast.walk(zone):
            if isinstance(node, ast.Constant) and node.value is None:
                return False
            if isinstance(node, ast.Attribute) and node.attr == "TIME_ZONE":
                return False
            if isinstance(node, ast.Call) and (
                self.name_of(node.func) in ZONELESS_ZONE_CALLS
            ):
                return False
        return True

    def is_zoneless_clock(self, node: ast.expr) -> bool:
        """An instant in no zone the code stated."""
        if isinstance(node, ast.BinOp):
            return self.is_zoneless_clock(node.left) or self.is_zoneless_clock(
                node.right
            )
        if isinstance(node, ast.Name):
            return (self.scope_of(node), node.id) in self.clock_names
        if not isinstance(node, ast.Call):
            return False
        if self.is_a_clock_callee(node.func, NOW_NAMES):
            return not self.states_a_zone(_zone_argument(node, 0, "tz"))
        if not isinstance(node.func, ast.Attribute):
            return False
        if node.func.attr in ZONE_KEEPING_CALLS:
            return self.is_zoneless_clock(node.func.value)
        if node.func.attr == "astimezone":
            return not self.states_a_zone(_zone_argument(node, 0, "tz"))
        return False

    def reads_the_clock(self, call: ast.Call) -> bool:
        if self.is_a_clock_callee(call.func, ZONED_CLOCK_NAMES):
            return not self.states_a_zone(_zone_argument(call, 1, "timezone"))
        if self.is_a_clock_callee(call.func, TODAY_NAMES):
            return True
        if isinstance(call.func, ast.Attribute) and self.is_a_clock_callee(
            call.func, frozenset({"fromtimestamp"})
        ):
            if self.name_of(call.func.value) == "date":
                return True
            return not self.states_a_zone(_zone_argument(call, 1, "tz"))
        return (
            isinstance(call.func, ast.Attribute)
            and call.func.attr in DAY_READS
            and self.is_zoneless_clock(call.func.value)
        )

    def reads_a_field(self, node: ast.Attribute) -> bool:
        """`now().year`, not called."""
        return node.attr in DAY_READS and self.is_zoneless_clock(node.value)

    def refers_to_the_clock(self, node: ast.expr) -> bool:
        """A clock factory named, not called."""
        if isinstance(node, ast.Attribute):
            return node.attr in CLOCK_NAMES and self.names_a_clock_module(node.value)
        if isinstance(node, ast.Name):
            return self.imported.get(node.id) in CLOCK_NAMES
        return False


def clock_reads(source: str) -> list[ClockRead]:
    """Every clock-day call or reference."""
    tree = ast.parse(source)
    module = Module(tree)
    called = {id(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
    reads = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            found = module.reads_the_clock(node)
        elif id(node) in called:
            continue
        elif isinstance(node, ast.Attribute):
            found = module.reads_a_field(node) or module.refers_to_the_clock(node)
        elif isinstance(node, ast.Name):
            found = module.refers_to_the_clock(node)
        else:
            continue
        if found:
            reads.append(ClockRead(node.lineno, module.scope_of(node)))
    return sorted(reads)


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


def _in_a_function(expression: str) -> str:
    return f"def view():\n    return {expression}\n"


def test_the_guard_reports_a_call() -> None:
    """Proved on a string, not a file."""
    reports = clock_calls(_in_a_function("localdate()"), "x.py")

    assert len(reports) == 1
    assert "x.py:2 in view()" in reports[0]
    assert "calendar_today(library)" in reports[0]
    assert 'Exemption("<why>", reads=<how many>)' in reports[0]


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
        "timezone.localdate()",
        "timezone.localtime()",
        "timezone.localtime(timezone.now())",
        "timezone.localdate(timezone.now())",
        "timezone.localdate(value=instant)",
        "timezone.localdate(timezone=None)",
        "timezone.localdate(instant, timezone.get_current_timezone())",
        "timezone.localdate(*arguments, *arguments)",
        "timezone.now().date()",
        "timezone.now().year",
        "timezone.now().strftime('%Y-%m-%d')",
        "datetime.now().date()",
        "datetime.utcnow().date()",
        "datetime.now(tz=None).date()",
        "datetime.now(ZoneInfo(settings.TIME_ZONE)).date()",
        "timezone.now().astimezone().date()",
        "timezone.now().astimezone(timezone.get_default_timezone()).date()",
        "(timezone.now() - timedelta(days=1)).date()",
        "timezone.now().replace(microsecond=0).date()",
        "datetime.date.today()",
        "date.today(*arguments)",
        "date.fromtimestamp(stamp)",
        "datetime.fromtimestamp(stamp).date()",
    ],
)
def test_the_guard_reports_every_spelling_of_the_active_day(expression) -> None:
    assert len(clock_calls(_in_a_function(expression), "x.py")) == 1, expression


def test_the_guard_follows_a_name_bound_to_the_clock() -> None:
    source = "def view():\n    instant = timezone.now()\n    return instant.date()\n"

    assert len(clock_calls(source, "x.py")) == 1


def test_the_guard_reports_a_clock_named_rather_than_called() -> None:
    source = "def view():\n    factory = date.today\n    return factory()\n"

    assert len(clock_calls(source, "x.py")) == 1


@pytest.mark.parametrize(
    "expression",
    [
        "datetime.now(tz=ZoneInfo(zone)).date()",
        "datetime.now(UTC).date()",
        "timezone.now().astimezone(ZoneInfo(zone)).date()",
        "timezone.localtime(instant, zone)",
        "timezone.localdate(instant, timezone=zone)",
        "datetime.fromtimestamp(stamp, tz=UTC)",
        "clock.today",
        "schedule.today()",
        "date(2026, 3, 5)",
        "timezone.now()",
        "timezone.now() - timedelta(hours=1)",
    ],
)
def test_the_guard_passes_what_states_its_zone_or_reads_no_day(expression) -> None:
    assert clock_calls(_in_a_function(expression), "x.py") == [], expression


def test_the_guard_names_the_innermost_function() -> None:
    source = "def outer():\n    def inner():\n        return date.today()\n"

    assert "in outer.inner()" in clock_calls(source, "x.py")[0]


def test_the_guard_qualifies_a_method() -> None:
    source = "class View:\n    def get(self):\n        return localdate()\n"

    assert "in View.get()" in clock_calls(source, "x.py")[0]


def test_the_guard_puts_a_decorator_in_its_function() -> None:
    source = "@cache(key=date.today())\ndef view():\n    return 1\n"

    assert "in view()" in clock_calls(source, "x.py")[0]


def test_the_guard_names_a_constant_by_its_target() -> None:
    source = "FACTORIES = frozenset({timezone.localdate})\nDAY = date.today()\n"

    reads = clock_reads(source)

    assert [read.function for read in reads] == ["FACTORIES", "DAY"]


def test_the_guard_reports_a_read_in_a_test_package() -> None:
    reports = clock_calls(_in_a_function("timezone.localdate()"), "tests/test_x.py")

    assert len(reports) == 1


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
            #: Frozen history; nothing else skipped.
            if path.is_relative_to(root / "games" / "migrations"):
                continue
            assert not path.is_symlink(), f"{path} is a link the walk skips"
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
