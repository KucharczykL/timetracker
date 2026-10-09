"""Motion classes come from tokens, not literals."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCANNED_PYTHON = ("common", "games")
SCANNED_TYPESCRIPT = ("ts",)
#: Literal Tailwind duration, e.g. duration-150.
LITERAL_DURATION = re.compile(r"\bduration-\d+\b")
#: Bare Tailwind easing; tokens replace it.
BARE_EASING = re.compile(r"\bease-(in|out|in-out|linear)\b")
#: Reduced-motion variant; tokens cover it.
MOTION_SAFE = re.compile(r"\bmotion-safe:")
PATTERNS = (LITERAL_DURATION, BARE_EASING, MOTION_SAFE)


def _python_sources() -> list[Path]:
    sources: list[Path] = []
    for directory in SCANNED_PYTHON:
        for path in sorted((ROOT / directory).rglob("*.py")):
            if "migrations" in path.parts or path.name == "icons_generated.py":
                continue
            sources.append(path)
    return sources


def _typescript_sources() -> list[Path]:
    sources: list[Path] = []
    for directory in SCANNED_TYPESCRIPT:
        for path in sorted((ROOT / directory).rglob("*.ts")):
            if path.name.endswith(".test.ts") or "generated" in path.parts:
                continue
            sources.append(path)
    return sources


def _hits(paths: list[Path]) -> list[str]:
    hits: list[str] = []
    for path in paths:
        lines = path.read_text(encoding="utf-8").splitlines()
        for number, line in enumerate(lines, start=1):
            if any(pattern.search(line) for pattern in PATTERNS):
                hits.append(f"{path.relative_to(ROOT)}:{number}")
    return hits


def test_no_literal_duration_or_bare_easing_or_motion_safe_in_source():
    hits = _hits(_python_sources() + _typescript_sources())
    assert hits == [], (
        "Use --duration-* and ease-enter/ease-exit tokens, and no motion-safe: "
        "variant, at: " + ", ".join(hits)
    )
