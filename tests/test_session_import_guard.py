"""Refusing the legacy Session table in first-party code.

Every page, API and read answers from `PlayerSession`. The legacy
`Session` model stays only for the conversion that reads it, the
census that counts it, the parity source that compares against it,
and the fixture commands that load it. TODO: drop the table and this
guard with it.
"""

import ast
from pathlib import Path

#: Not tests/ or e2e/: the legacy-table tests leave with the table.
GUARDED_PACKAGES = ("games", "common", "timetracker")
LEGACY_NAMES = frozenset({"Session", "SessionQuerySet"})

#: A path, and why it still reads the legacy table.
ALLOWED_FILES: dict[str, str] = {
    "games/models.py": "Declares the model.",
    "games/backfill/playersession.py": "Converts every legacy row.",
    "games/preflight/session.py": "The census of legacy rows.",
    "games/reads/playtime/legacy.py": "The parity command's other source.",
    "games/reads/session_parity.py": "The statistics gate's legacy side.",
    "games/removal.py": "REMOVABLE_MODELS lists it until the table goes.",
    "games/management/commands/load_sample_data.py": "Loads the fixture.",
    "games/management/commands/anonymize_sample.py": "Writes the fixture.",
}

REPORT = (
    "{path}:{line} reads the legacy Session table through `{name}`. "
    "Every surface answers from PlayerSession: read through "
    "games.reads.player_sessions and write through games.writes.playersession. "
    "A reader the table itself needs goes in ALLOWED_FILES with the reason."
)


def _report(path: str, line: int, name: str) -> str:
    return REPORT.format(path=path, line=line, name=name)


def legacy_reads(source: str, path: str) -> list[str]:
    """Every declaration, import and dotted read of the legacy model."""
    reports = []
    for node in ast.walk(ast.parse(source)):
        match node:
            case ast.ClassDef(name=name) if name in LEGACY_NAMES:
                reports.append(_report(path, node.lineno, name))
            case ast.ImportFrom(module="games.models", names=names):
                reports.extend(
                    _report(path, node.lineno, alias.name)
                    for alias in names
                    if alias.name in LEGACY_NAMES
                )
            case ast.Attribute(
                value=ast.Attribute(value=ast.Name(id="games"), attr="models"),
                attr=attr,
            ) if attr in LEGACY_NAMES:
                reports.append(_report(path, node.lineno, f"games.models.{attr}"))
    return reports


def test_the_guard_reports_an_import() -> None:
    """Proved on a string, not a file."""
    reports = legacy_reads(
        "from games.models import Game, Session\n"
        "from games.models import SessionQuerySet\n",
        "x.py",
    )
    assert [report.split(" ")[0] for report in reports] == ["x.py:1", "x.py:2"]
    assert "games.reads.player_sessions" in reports[0]


def test_the_guard_reports_a_dotted_read() -> None:
    reports = legacy_reads(
        "import games.models\nrows = games.models.Session.objects.all()\n", "x.py"
    )
    assert len(reports) == 1
    assert "x.py:2" in reports[0]


def test_the_guard_passes_the_projection() -> None:
    assert (
        legacy_reads(
            "from games.models import PlayerSession\n"
            "from django.contrib.sessions.models import Session\n",
            "x.py",
        )
        == []
    )


def test_every_allowed_file_still_reads_the_table() -> None:
    """An exemption nothing needs is taken away."""
    root = Path(__file__).resolve().parent.parent
    for relative in ALLOWED_FILES:
        path = root / relative
        assert path.is_file(), f"{relative} is exempt but does not exist"
        assert legacy_reads(path.read_text(encoding="utf-8"), relative), (
            f"{relative} is exempt but reads the legacy table nowhere"
        )


def test_no_first_party_module_reads_the_legacy_session_table() -> None:
    root = Path(__file__).resolve().parent.parent
    reports: list[str] = []
    for package in GUARDED_PACKAGES:
        directory = root / package
        assert directory.is_dir(), f"{package}/ is in the walk but is not a directory"
        for path in sorted(directory.rglob("*.py")):
            relative = path.relative_to(root).as_posix()
            if relative in ALLOWED_FILES:
                continue
            reports.extend(legacy_reads(path.read_text(encoding="utf-8"), relative))
    assert not reports, "\n".join(reports)
