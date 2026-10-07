"""Guard: raw palette colours need `color-ok:`."""

import re

from test_typography_tokens import REPO, guarded_files, ts_files

# Palette hue with a stop, white/black, or arbitrary.
_HUES = (
    "gray|slate|zinc|neutral|stone|red|orange|amber|yellow|lime|green|"
    "emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose"
)
RAW_COLOR = re.compile(
    r"(?<![\w-])(?:[a-z@\[\]:.-]+:)?!?"
    r"(?:ring-offset|inset-ring|inset-shadow|drop-shadow|text-shadow|placeholder"
    r"|bg|text|border|ring|divide|outline|decoration|shadow|fill|stroke"
    r"|from|via|to|accent|caret)"
    r"(?:-[a-z]{1,2})?-"
    rf"(?:(?P<hue>{_HUES})-\d{{2,3}}(?![\w])"
    r"|(?P<plain>white|black)(?![\w-])"
    r"|(?P<arbitrary>\[(?:#|rgb|hsl|oklch|oklab|color:)))"
)
# The reason names each colour it admits.
COLOR_OK = re.compile(r"(?:#|//)\s*color-ok:\s*(?P<reason>\S.*)$")


def unadmitted(line: str) -> list[str]:
    """Raw colours the line's marker does not name."""
    marker = COLOR_OK.search(line)
    admitted = set(re.findall(r"[a-z]+", marker["reason"])) if marker else set()
    code = line[: marker.start()] if marker else line
    return [
        match[0]
        for match in RAW_COLOR.finditer(code)
        if (match["hue"] or match["plain"] or "arbitrary") not in admitted
    ]


def test_raw_color_regex_self_check():
    for hit in (
        "border-l-teal-400",
        "dark:bg-gray-900/40",
        "dark:bg-teal-500/20",
        "ring-red-500",
        "bg-amber-50",
        "text-indigo-500",
        "dark:text-white",
        "text-white!",
        "bg-black/10",
        "border-l-white/30",
        "ring-offset-white",
        "placeholder-gray-400",
        "drop-shadow-black/50",
        "bg-[#fff]",
        "text-[color:var(--x)]",
    ):
        assert RAW_COLOR.search(hit), hit
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
        "shadow-[0_1px_0_rgb(255_255_255_/_0.7)]",
    ):
        assert not RAW_COLOR.search(miss), miss


def test_marker_admits_only_the_colours_it_names():
    assert unadmitted('"bg-gray-500"  # color-ok: gray status dot') == []
    assert unadmitted('"bg-gray-500"  // color-ok: gray status dot') == []
    assert unadmitted('"bg-gray-500"  # color-ok') == ["bg-gray-500"]
    assert unadmitted('"bg-gray-500"  # color-ok:') == ["bg-gray-500"]
    assert unadmitted('"bg-gray-500 bg-red-500"  # color-ok: gray dot') == [
        "bg-red-500"
    ]


def test_walker_finds_both_halves():
    # An empty half would pass vacuously.
    files = list(guarded_files())
    assert any(path.suffix == ".py" for path in files)
    assert any(path.suffix == ".ts" for path in files)
    assert all(not path.name.endswith(".test.ts") for path in ts_files())


def test_no_raw_palette_colors():
    offenders = [
        f"{path.relative_to(REPO)}:{line_number}: {line.strip()}"
        for path in guarded_files()
        for line_number, line in enumerate(path.read_text().splitlines(), 1)
        if unadmitted(line)
    ]
    assert not offenders, (
        "raw palette colors — use semantic tokens (or add "
        "`# color-ok: <colour> reason` / `// color-ok: <colour> reason`):\n"
        + "\n".join(offenders)
    )


def test_input_css_does_not_restore_the_tailwind_v3_border_color_shim():
    """Bordering components must choose semantic colors themselves (#410)."""
    input_css = (REPO / "common" / "input.css").read_text()
    assert "border-color:" not in input_css, (
        "do not restore Tailwind v3's global border-color compatibility shim; "
        "add an explicit border-* color utility to the dependent component instead"
    )
