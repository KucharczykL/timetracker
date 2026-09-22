"""No act module reads a name off another act module.

The act table imports every act at its foot, so an act reached first runs that
foot before its own body. A sibling reading a name off it then finds a module
in `sys.modules` with nothing defined yet, and the import fails — but only for
the one entry order, which is why a suite can stay green while a page 500s.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TABLE = ROOT / "games" / "bulk_actions.py"


def declared_act_modules() -> set[str]:
    """The modules the table imports at its foot."""
    tree = ast.parse(TABLE.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "games":
            return {alias.name for alias in node.names}
    raise AssertionError("The act table imports no act module at its foot.")


def test_the_table_imports_every_act_module_it_holds():
    modules = declared_act_modules()

    assert modules
    for name in modules:
        assert (ROOT / "games" / f"{name}.py").exists(), name


def test_no_act_module_imports_a_sibling():
    modules = declared_act_modules()

    for name in sorted(modules):
        tree = ast.parse((ROOT / "games" / f"{name}.py").read_text())
        read = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        siblings = {f"games.{other}" for other in modules if other != name} & read
        assert not siblings, (
            f"games/{name}.py reads a name off {sorted(siblings)}, which the act "
            "table imports at its foot. Whichever of the two a request reaches "
            "first decides whether the import works. Put the shared half in a "
            "module that declares no act."
        )
