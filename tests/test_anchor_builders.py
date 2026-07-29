"""Guard: every anchor goes through one of the four builders.

`A` is the unstyled whitelist builder. Calling it directly is how the app grew
six different link looks, so the choice is pushed into the call instead:

- ``Link`` — an inline text link inside page content
- ``IconLink`` — a link whose entire content is an icon
- ``ControlLink`` — chrome that owns its appearance (navbar, pagination, sort
  headers, the settings rail, dropdown menu items)
- ``ControlButton(href=…)`` — a control that happens to navigate

Two details are load-bearing, both learned from real call sites:

*Match the call, not the keyword.* Three sites pass attributes positionally —
``A([("href", url), …])`` — so a walk keyed on ``href=`` would miss them and the
positional form would become a silent bypass.

*Allow by enclosing definition.* The builders call ``A`` themselves, so the
exemption belongs to the function or class they live in, not to a call shape.
"""

import ast
import pathlib

REPO = pathlib.Path(__file__).resolve().parent.parent
PACKAGES = ("common", "games")

# The definitions permitted to construct an anchor directly.
ANCHOR_BUILDERS = frozenset({"Link", "IconLink", "ControlLink", "ControlButton"})

# Where the raw anchor may legitimately be named: the module defining the
# builders, and the package's export barrel. Anywhere else, importing `A` is a
# smell in its own right — nothing but a builder should need it.
RAW_ANCHOR_MODULES = frozenset(
    {"common/components/primitives.py", "common/components/__init__.py"}
)


def _python_files() -> list[pathlib.Path]:
    return sorted(
        path
        for package in PACKAGES
        for path in (REPO / package).rglob("*.py")
        if "migrations" not in path.parts
    )


def _anchor_calls(tree: ast.AST) -> list[tuple[int, tuple[str, ...]]]:
    """(line, enclosing definition names) for every `A(...)` call in `tree`.

    The full chain, outermost first — a builder's anchor call sits inside its
    own method (`ControlButton.render`), so checking only the nearest
    definition would flag the very code the exemption is for.
    """
    scopes: dict[ast.AST, tuple[str, ...]] = {tree: ()}
    for node in ast.walk(tree):
        current = scopes.get(node, ())
        for child in ast.iter_child_nodes(node):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                scopes[child] = (*current, node.name)
            else:
                scopes[child] = current

    return [
        (node.lineno, scopes.get(node, ()))
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "A"
    ]


def test_no_anchor_is_built_outside_the_builders():
    offenders = []
    for path in _python_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        for line, scope in _anchor_calls(tree):
            if not ANCHOR_BUILDERS.intersection(scope):
                where = ".".join(scope) or "<module>"
                offenders.append(
                    f"{path.relative_to(REPO).as_posix()}:{line} in {where}"
                )

    assert not offenders, (
        "Build anchors with Link / IconLink / ControlLink / ControlButton, "
        "not A():\n  " + "\n  ".join(offenders)
    )


def test_raw_anchor_builder_is_imported_only_where_the_builders_live():
    offenders = []
    for path in _python_files():
        relative = path.relative_to(REPO).as_posix()
        if relative in RAW_ANCHOR_MODULES:
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and any(
                alias.name == "A" for alias in node.names
            ):
                offenders.append(f"{relative}:{node.lineno}")

    assert not offenders, (
        "Import a named anchor builder instead of the raw A:\n  "
        + "\n  ".join(offenders)
    )


def test_guard_catches_both_call_forms():
    """Self-check: the keyword form and the positional-attrs form both trip it.

    Without this, a refactor that narrowed the walk to `href=` keywords would
    leave the guard passing and the rule unenforced.
    """
    source = """
def SomeView():
    keyword = A(href="/x")["text"]
    positional = A([("href", "/y")])["text"]
    aliased = ControlLink(href="/z")["text"]
"""
    calls = _anchor_calls(ast.parse(source))
    assert [line for line, _ in calls] == [3, 4]
    assert {scope for _, scope in calls} == {("SomeView",)}


def test_guard_allows_the_builders_themselves():
    source = """
class ControlButton:
    def render(self):
        return A([("href", self._href)])[self._children]
"""
    calls = _anchor_calls(ast.parse(source))
    assert [scope for _, scope in calls] == [("ControlButton", "render")]
    assert ANCHOR_BUILDERS.intersection(calls[0][1])
