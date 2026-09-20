"""Refusing a corner stated as a literal class on a ControlButton call."""

import ast
from pathlib import Path

from common.components.primitives import _refuse_a_stated_corner

#: Not tests/: a test states a refused class on purpose.
GUARDED_PACKAGES = ("games", "common", "timetracker", "contrib", "scripts")
GUARDED_BUILDERS = frozenset({"ControlButton"})
#: The class attribute under both its spellings.
CLASS_KEYWORDS = frozenset({"class_", "class"})

REPORT = (
    "{path}:{line} states a corner as a class on {builder}: {word!r}. "
    'A button states its corners with shape= ("full", "start", "end" or '
    '"square"). The component refuses this at render time, which is a 500 on '
    "whatever page reaches it first; this is the same refusal at `make check`."
)


def _stated_corner(value: str) -> str:
    """The refused word in ``value``, or "" — the component's own predicate.

    Sharing it is the point: a spelling the walk knows and the component does
    not would be a rule two places state differently.
    """
    try:
        _refuse_a_stated_corner(value)
    except TypeError as refusal:
        return str(refusal).split("'")[1]
    return ""


def _literal_parts(node: ast.expr) -> list[str]:
    """Every string literal a class expression is built from.

    An f-string composing a baked class with a corner states that corner as
    surely as a plain literal does, so its literal parts count. A name the
    walk cannot resolve does not — that is the runtime refusal's half.
    """
    if isinstance(node, ast.Constant):
        return [node.value] if isinstance(node.value, str) else []
    if isinstance(node, ast.JoinedStr):
        return [
            part.value
            for part in node.values
            if isinstance(part, ast.Constant) and isinstance(part.value, str)
        ]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _literal_parts(node.left) + _literal_parts(node.right)
    return []


def stated_corners(source: str, path: str) -> list[str]:
    """Every literal corner stated on a guarded builder's class argument."""
    reports = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        called = node.func
        name = called.attr if isinstance(called, ast.Attribute) else None
        if isinstance(called, ast.Name):
            name = called.id
        if name not in GUARDED_BUILDERS:
            continue
        stated: list[ast.expr] = [
            keyword.value for keyword in node.keywords if keyword.arg in CLASS_KEYWORDS
        ]
        # The positional slot carries runtime pairs: ("class", "…") among them.
        for argument in node.args:
            stated.extend(_literal_parts_of_pairs(argument))
        for value in stated:
            for part in _literal_parts(value):
                word = _stated_corner(part)
                if word:
                    reports.append(
                        REPORT.format(
                            path=path, line=node.lineno, builder=name, word=word
                        )
                    )
    return reports


def _literal_parts_of_pairs(node: ast.expr) -> list[ast.expr]:
    """The value of every ``("class", …)`` pair in a positional attrs list."""
    if not isinstance(node, (ast.List, ast.Tuple)):
        return []
    values = []
    for element in node.elts:
        if not isinstance(element, ast.Tuple) or len(element.elts) != 2:
            continue
        name, value = element.elts
        if isinstance(name, ast.Constant) and name.value in CLASS_KEYWORDS:
            values.append(value)
    return values


def test_the_guard_reports_a_keyword_class() -> None:
    """Proved on a string, not a file."""
    reports = stated_corners('ControlButton(class_="rounded-s-base")\n', "x.py")
    assert len(reports) == 1
    assert "x.py:1" in reports[0]
    assert "shape=" in reports[0]


def test_the_guard_reports_every_spelling_the_component_refuses() -> None:
    """One predicate, so the walk cannot know a smaller grammar."""
    for spelling in (
        "rounded",
        "rounded-full",
        "sm:rounded-base",
        "hover:rounded-full",
        "!rounded-full",
        "[&>*:first-child]:rounded-s-base",
    ):
        source = f'ControlButton(class_="{spelling}")\n'
        assert stated_corners(source, "x.py"), spelling


def test_the_guard_reads_a_composed_class() -> None:
    """A corner composed onto a baked class is still stated."""
    assert stated_corners('ControlButton(class_=f"{base} rounded-e-base")\n', "x.py")
    assert stated_corners('ControlButton(class_=base + " rounded-e-base")\n', "x.py")


def test_the_guard_reads_the_positional_attribute_slot() -> None:
    assert stated_corners('ControlButton([("class", "rounded-base")])\n', "x.py")


def test_the_guard_passes_a_class_that_states_no_corner() -> None:
    assert stated_corners('ControlButton(class_="ms-auto w-full")\n', "x.py") == []
    assert stated_corners('ControlButton(shape="start")\n', "x.py") == []
    assert stated_corners('Div(class_="rounded-base")\n', "x.py") == []


def test_no_first_party_module_states_a_corner_on_a_button() -> None:
    root = Path(__file__).resolve().parent.parent
    reports: list[str] = []
    for package in GUARDED_PACKAGES:
        directory = root / package
        assert directory.is_dir(), f"{package}/ is in the walk but is not a directory"
        for path in sorted(directory.rglob("*.py")):
            relative = path.relative_to(root).as_posix()
            reports.extend(stated_corners(path.read_text(encoding="utf-8"), relative))
    assert not reports, "\n".join(reports)
