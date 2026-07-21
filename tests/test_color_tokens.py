"""Guard: no raw Tailwind palette colors in ts/ class strings (#441).

Class strings hardcoded in ts/ escape the .py color-token conventions (the
guards are otherwise Python-only). Raw palette utilities (`bg-gray-50`,
`border-l-teal-400`, `ring-red-500`) must use semantic tokens
(`bg-neutral-*`, `border-default-medium`, `ring-danger`, …). Deliberate
categorical hues (the filter-builder accents that mirror the logic chips) opt
out per line with `// color-ok: <reason>`.

Scoped to ts/ ONLY — common/ still carries raw palette mid-migration
(#404–#407); a .py color guard belongs to those issues, not here.
"""

import re

from test_typography_tokens import REPO, ts_files

# A palette utility: a color property, an optional side/axis (border-l), a
# Tailwind hue, and a numeric stop. Semantic tokens (neutral-*, default-*,
# body, danger, warning, brand — no numeric stop) don't match.
_HUES = (
    "gray|slate|zinc|neutral|stone|red|orange|amber|yellow|lime|green|"
    "emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose"
)
RAW_COLOR = re.compile(
    r"(?<![\w-])(?:[a-z@\[\]:.-]+:)?"
    r"(?:bg|text|border|ring|divide|outline|decoration|shadow|fill|stroke"
    r"|from|via|to|accent|caret)"
    r"(?:-[a-z]{1,2})?-"
    rf"(?:{_HUES})"
    r"-\d{2,3}(?![\w])"
)


def test_raw_color_regex_self_check():
    # Matches raw palette (incl. side modifier + variant prefix + opacity).
    for hit in (
        "border-l-teal-400",
        "dark:bg-gray-900/40",
        "ring-red-500",
        "bg-amber-50",
        "text-indigo-500",
    ):
        assert RAW_COLOR.search(hit), hit
    # Does NOT match semantic tokens or the colorless side utility.
    for miss in (
        "border-default-medium",
        "bg-neutral-tertiary-medium",
        "text-body",
        "ring-danger",
        "bg-warning-soft",
        "text-type-body",
        "border-l-4",
    ):
        assert not RAW_COLOR.search(miss), miss


def test_ts_walker_finds_files():
    # Guard against a vacuous pass: if ts_files() ever yields nothing (a broken
    # rglob/exclusion), test_no_raw_palette_colors_in_ts would pass trivially.
    files = list(ts_files())
    assert files, "ts_files() yielded no files — the ts/ guard would pass vacuously"
    assert all(not f.name.endswith(".test.ts") for f in files)


def test_no_raw_palette_colors_in_ts():
    offenders = []
    for f in ts_files():
        for i, line in enumerate(f.read_text().splitlines(), 1):
            if "color-ok" in line:  # `// color-ok: <reason>` opts a line out
                continue
            if RAW_COLOR.search(line):
                offenders.append(f"{f.relative_to(REPO)}:{i}: {line.strip()}")
    assert not offenders, (
        "raw palette colors in ts/ — use semantic tokens (or add "
        "`// color-ok: reason` for a deliberate categorical hue):\n"
        + "\n".join(offenders)
    )


def test_input_css_does_not_restore_the_tailwind_v3_border_color_shim():
    """Bordering components must choose semantic colors themselves (#410)."""
    input_css = (REPO / "common" / "input.css").read_text()
    assert "border-color:" not in input_css, (
        "do not restore Tailwind v3's global border-color compatibility shim; "
        "add an explicit border-* color utility to the dependent component instead"
    )
