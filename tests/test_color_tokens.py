"""Guard: raw palette colours need `color-ok:`."""

import re

from test_typography_tokens import REPO, guarded_files, ts_files

# Palette hue with a stop, or white/black.
_HUES = (
    "gray|slate|zinc|neutral|stone|red|orange|amber|yellow|lime|green|"
    "emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose"
)
RAW_COLOR = re.compile(
    r"(?<![\w-])(?:[a-z@\[\]:.-]+:)?"
    r"(?:bg|text|border|ring|divide|outline|decoration|shadow|fill|stroke"
    r"|from|via|to|accent|caret)"
    r"(?:-[a-z]{1,2})?-"
    rf"(?:(?:{_HUES})-\d{{2,3}}(?![\w])|(?:white|black)(?![\w-]))"
)


def test_raw_color_regex_self_check():
    # Matches raw palette (incl. side modifier + variant prefix + opacity).
    for hit in (
        "border-l-teal-400",
        "dark:bg-gray-900/40",
        "ring-red-500",
        "bg-amber-50",
        "text-indigo-500",
        "dark:text-white",
        "bg-black/10",
        "border-l-white/30",
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
        "text-whitesmoke",
        "solid-brand",
        "text-heading",
    ):
        assert not RAW_COLOR.search(miss), miss


def test_walker_finds_both_halves():
    # An empty half would pass vacuously.
    files = list(guarded_files())
    assert any(f.suffix == ".py" for f in files)
    assert any(f.suffix == ".ts" for f in files)
    assert all(not f.name.endswith(".test.ts") for f in ts_files())


def test_no_raw_palette_colors():
    offenders = []
    for f in guarded_files():
        for i, line in enumerate(f.read_text().splitlines(), 1):
            if "color-ok" in line:
                continue
            if RAW_COLOR.search(line):
                offenders.append(f"{f.relative_to(REPO)}:{i}: {line.strip()}")
    assert not offenders, (
        "raw palette colors — use semantic tokens (or add "
        "`# color-ok: reason` / `// color-ok: reason` for a deliberate hue):\n"
        + "\n".join(offenders)
    )


def test_input_css_does_not_restore_the_tailwind_v3_border_color_shim():
    """Bordering components must choose semantic colors themselves (#410)."""
    input_css = (REPO / "common" / "input.css").read_text()
    assert "border-color:" not in input_css, (
        "do not restore Tailwind v3's global border-color compatibility shim; "
        "add an explicit border-* color utility to the dependent component instead"
    )
