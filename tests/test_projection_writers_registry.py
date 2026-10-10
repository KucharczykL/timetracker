"""Every door is opened by its registered module, and every writer has one."""

import ast
from collections.abc import Iterator
from pathlib import Path

from django.conf import settings

from games.models import PurchaseValuation
from games.projection_writers import (
    PERMITTED_WRITERS,
    GuardedKind,
    ProjectionWriter,
    guarded_tables,
)
from games.projections import projection_models

SOURCE_DIRECTORIES = ("games", "common", "timetracker", "contrib", "scripts")
DOOR_FILES = ("tests/projection_doors.py",)


def _repository_root() -> Path:
    return Path(settings.BASE_DIR)


def _source_files() -> Iterator[Path]:
    root = _repository_root()
    for directory in SOURCE_DIRECTORIES:
        for path in sorted((root / directory).rglob("*.py")):
            if "__pycache__" not in path.parts:
                yield path
    for door in DOOR_FILES:
        yield root / door


def _is_projection_writes_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == "projection_writes"
    if isinstance(func, ast.Attribute):
        return func.attr == "projection_writes"
    return False


def _opened_writers() -> tuple[dict[ProjectionWriter, list[str]], list[str]]:
    """Each member opened, with the locations opening it; and every problem."""
    root = _repository_root()
    opened: dict[ProjectionWriter, list[str]] = {}
    problems: list[str] = []
    for path in _source_files():
        relative = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not _is_projection_writes_call(node):
                continue
            location = f"{relative}:{node.lineno}"
            argument = node.args[0] if node.args else None
            if not (
                isinstance(argument, ast.Attribute)
                and isinstance(argument.value, ast.Name)
                and argument.value.id == "ProjectionWriter"
                and argument.attr in ProjectionWriter.__members__
            ):
                problems.append(
                    f"{location}: projection_writes must take ProjectionWriter.<member>"
                )
                continue
            writer = ProjectionWriter[argument.attr]
            if PERMITTED_WRITERS[writer].module != relative:
                problems.append(
                    f"{location}: {writer} is registered to "
                    f"{PERMITTED_WRITERS[writer].module}, not {relative}"
                )
            opened.setdefault(writer, []).append(location)
    return opened, problems


def test_every_door_call_names_a_member_registered_to_its_file():
    _opened, problems = _opened_writers()
    assert problems == []


def test_the_walk_finds_door_calls():
    opened, _problems = _opened_writers()
    assert opened, "the AST walk found no projection_writes call"


def test_every_writer_has_an_open_door_somewhere():
    opened, _problems = _opened_writers()
    missing = [writer for writer in ProjectionWriter if writer not in opened]
    assert missing == []


def test_every_projection_table_is_guarded_as_a_projection():
    tables = guarded_tables()
    for model in projection_models():
        assert tables[model._meta.db_table.lower()] is GuardedKind.PROJECTION


def test_the_valuation_table_is_guarded_as_a_valuation():
    tables = guarded_tables()
    assert tables[PurchaseValuation._meta.db_table.lower()] is GuardedKind.VALUATION


def test_every_registered_module_exists_on_disk():
    root = _repository_root()
    for writer, permitted in PERMITTED_WRITERS.items():
        assert (root / permitted.module).is_file(), f"{writer} names no file"


def test_the_registry_keys_are_exactly_the_writers():
    assert set(PERMITTED_WRITERS) == set(ProjectionWriter)
