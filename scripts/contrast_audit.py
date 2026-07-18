"""WCAG 2.1 contrast audit for timetracker's token/raw color pairings.

Converts Tailwind v4 oklch palette values to sRGB, computes relative-luminance
contrast ratios for every text-on-surface pairing in both themes, and emits a
markdown table. Alpha-composited surfaces (frosted dropdown, chip fills) are
flattened against their backdrop first. brand-soft is the input.css
color-mix(in oklab, brand 15%, neutral-primary), computed in oklab.
"""

import math

OKLCH = {
    "white": (1.0, 0.0, 0.0),
    "black": (0.0, 0.0, 0.0),
    "gray-50": (0.985, 0.002, 247.839),
    "gray-100": (0.967, 0.003, 264.542),
    "gray-200": (0.928, 0.006, 264.531),
    "gray-300": (0.872, 0.010, 258.338),
    "gray-400": (0.707, 0.022, 261.325),
    "gray-500": (0.551, 0.027, 264.364),
    "gray-600": (0.446, 0.030, 256.802),
    "gray-700": (0.373, 0.034, 259.733),
    "gray-800": (0.278, 0.033, 256.848),
    "gray-900": (0.210, 0.034, 264.665),
    "gray-950": (0.130, 0.028, 261.692),
    "slate-200": (0.929, 0.013, 255.508),
    "slate-300": (0.869, 0.022, 252.894),
    "slate-500": (0.554, 0.046, 257.417),
    "slate-600": (0.446, 0.043, 257.281),
    "slate-800": (0.279, 0.041, 260.031),
    "slate-900": (0.208, 0.042, 265.755),
    "indigo-100": (0.930, 0.034, 272.788),
    "indigo-200": (0.870, 0.065, 274.039),
    "blue-500": (0.623, 0.214, 259.815),
    "blue-600": (0.546, 0.245, 262.881),
    "blue-700": (0.488, 0.243, 264.376),
    "red-600": (0.577, 0.245, 27.325),
    "red-700": (0.505, 0.213, 27.518),
    "rose-700": (0.514, 0.222, 16.935),  # from tailwind theme.css rose scale
    "green-600": (0.627, 0.194, 149.214),
    "green-700": (0.527, 0.154, 150.069),
    "emerald-600": (0.596, 0.145, 163.225),
    "emerald-700": (0.508, 0.118, 165.612),
    "teal-100": (0.953, 0.051, 180.801),
    "teal-200": (0.910, 0.096, 180.426),
    "teal-500": (0.704, 0.140, 182.503),
    "teal-800": (0.437, 0.078, 188.216),
    "orange-100": (0.954, 0.038, 75.164),
    "orange-200": (0.901, 0.076, 70.697),
    "orange-500": (0.705, 0.213, 47.604),
    "orange-800": (0.470, 0.157, 37.304),
    "amber-100": (0.962, 0.059, 95.617),
    "amber-400": (0.828, 0.189, 84.429),
    "amber-500": (0.769, 0.188, 70.080),
    "amber-700": (0.555, 0.163, 48.998),
    "amber-900": (0.414, 0.112, 45.904),
    "green-50": (0.982, 0.018, 155.826),
    "green-200": (0.925, 0.084, 155.995),
    "green-800": (0.448, 0.119, 151.328),
    "green-900": (0.393, 0.095, 152.535),
    "red-50": (0.971, 0.013, 17.380),
    "red-200": (0.885, 0.062, 18.334),
    "red-800": (0.444, 0.177, 26.899),
    "red-900": (0.396, 0.141, 25.723),
    "amber-200": (0.924, 0.120, 95.746),
    "amber-800": (0.473, 0.137, 46.201),
    "amber-950": (0.279, 0.077, 45.635),
    "blue-50": (0.970, 0.014, 254.604),
    "blue-800": (0.424, 0.199, 265.638),
    "blue-900": (0.379, 0.146, 265.522),
    "blue-200": (0.882, 0.059, 254.128),
}


def oklch_to_oklab(L, C, H):
    h = math.radians(H)
    return (L, C * math.cos(h), C * math.sin(h))


def oklab_to_linear_srgb(L, a, b):
    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = l_**3, m_**3, s_**3
    return (
        +4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
        -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
        -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s,
    )


def name_to_linear(name):
    lab = oklch_to_oklab(*OKLCH[name])
    return tuple(max(0.0, min(1.0, c)) for c in oklab_to_linear_srgb(*lab))


def mix_oklab(name_a, name_b, frac_a):
    """color-mix(in oklab, A frac_a, B) -> linear sRGB."""
    la = oklch_to_oklab(*OKLCH[name_a])
    lb = oklch_to_oklab(*OKLCH[name_b])
    mixed = tuple(frac_a * x + (1 - frac_a) * y for x, y in zip(la, lb))
    return tuple(max(0.0, min(1.0, c)) for c in oklab_to_linear_srgb(*mixed))


def composite(fg_linear, alpha, bg_linear):
    """Flatten fg with alpha over bg (linear-light compositing approximation)."""
    return tuple(alpha * f + (1 - alpha) * b for f, b in zip(fg_linear, bg_linear))


def luminance(linear_rgb):
    r, g, b = linear_rgb
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ratio(fg, bg):
    lf, lb = luminance(fg), luminance(bg)
    lighter, darker = max(lf, lb), min(lf, lb)
    return (lighter + 0.05) / (darker + 0.05)


def col(name):
    return name_to_linear(name)


# brand-soft: color-mix(in oklab, brand 15%, neutral-primary)
BRAND_SOFT_LIGHT = mix_oklab("blue-700", "white", 0.15)
BRAND_SOFT_DARK = mix_oklab("blue-600", "gray-950", 0.15)

# Frosted dropdown dark panel: gray-800 at 40% over page bg gray-950
FROSTED_DARK = composite(col("gray-800"), 0.40, col("gray-950"))
# Chip dark fills: color-500/20 over gray-950
TEAL_CHIP_DARK = composite(col("teal-500"), 0.20, col("gray-950"))
ORANGE_CHIP_DARK = composite(col("orange-500"), 0.20, col("gray-950"))
AMBER_CHIP_DARK = composite(col("amber-500"), 0.25, col("gray-950"))
QUICK_PILL_DARK = composite(col("gray-800"), 0.50, col("gray-950"))
QUICK_PILL_LIGHT = composite(col("gray-50"), 0.50, col("white"))

# (role, theme, fg description, fg linear, bg description, bg linear, threshold)
# threshold: 4.5 = AA normal text, 3.0 = AA large text / UI component
CASES = [
    # ── Semantic tokens, light ──
    ("text-heading on page (neutral-primary)", "light", "gray-900", col("gray-900"), "white", col("white"), 4.5),
    ("text-body on page", "light", "gray-600", col("gray-600"), "white", col("white"), 4.5),
    ("text-body-subtle on page", "light", "gray-500", col("gray-500"), "white", col("white"), 4.5),
    ("text-heading on control (neutral-secondary-medium)", "light", "gray-900", col("gray-900"), "gray-50", col("gray-50"), 4.5),
    ("text-body/placeholder on control", "light", "gray-600", col("gray-600"), "gray-50", col("gray-50"), 4.5),
    ("text-heading on brand-soft (Pill/Badge/popover)", "light", "gray-900", col("gray-900"), "brand-soft", BRAND_SOFT_LIGHT, 4.5),
    ("white on brand (primary button)", "light", "white", col("white"), "blue-700", col("blue-700"), 4.5),
    ("text-fg-brand link on page", "light", "blue-700", col("blue-700"), "white", col("white"), 4.5),
    ("text-fg-brand on hover surface (gray-100)", "light", "blue-700", col("blue-700"), "gray-100", col("gray-100"), 4.5),
    ("control border vs control bg (default-medium)", "light", "gray-200", col("gray-200"), "gray-50", col("gray-50"), 3.0),
    ("control border vs page (default-medium)", "light", "gray-200", col("gray-200"), "white", col("white"), 3.0),
    # ── Semantic tokens, dark ──
    ("text-heading on page (neutral-primary)", "dark", "white", col("white"), "gray-950", col("gray-950"), 4.5),
    ("text-body on page", "dark", "gray-400", col("gray-400"), "gray-950", col("gray-950"), 4.5),
    ("text-heading on control (neutral-secondary-medium)", "dark", "white", col("white"), "gray-800", col("gray-800"), 4.5),
    ("text-body/placeholder on control", "dark", "gray-400", col("gray-400"), "gray-800", col("gray-800"), 4.5),
    ("text-heading on brand-soft", "dark", "white", col("white"), "brand-soft", BRAND_SOFT_DARK, 4.5),
    ("white on brand (primary button)", "dark", "white", col("white"), "blue-600", col("blue-600"), 4.5),
    ("text-fg-brand link on page", "dark", "blue-500", col("blue-500"), "gray-950", col("gray-950"), 4.5),
    ("text-fg-brand on hover surface (gray-700)", "dark", "blue-500", col("blue-500"), "gray-700", col("gray-700"), 4.5),
    ("control border vs control bg (default-medium)", "dark", "gray-700", col("gray-700"), "gray-800", col("gray-800"), 3.0),
    ("control border vs page (default-medium)", "dark", "gray-800", col("gray-800"), "gray-950", col("gray-950"), 3.0),
    # ── Raw-palette clusters, light ──
    ("gray button text (gray-900 on white)", "light", "gray-900", col("gray-900"), "white", col("white"), 4.5),
    ("table body text on zebra-odd (gray-500 on white)", "light", "gray-500", col("gray-500"), "white", col("white"), 4.5),
    ("table body text on zebra-even (gray-500 on gray-50)", "light", "gray-500", col("gray-500"), "gray-50", col("gray-50"), 4.5),
    ("thead text (gray-700 on gray-50)", "light", "gray-700", col("gray-700"), "gray-50", col("gray-50"), 4.5),
    ("pagination link (gray-500 on white)", "light", "gray-500", col("gray-500"), "white", col("white"), 4.5),
    ("pagination disabled (gray-300 on white)", "light", "gray-300", col("gray-300"), "white", col("white"), 4.5),
    ("pagination current (white on gray-400)", "light", "white", col("white"), "gray-400", col("gray-400"), 4.5),
    ("white on red-700 (destructive button)", "light", "white", col("white"), "red-700", col("red-700"), 4.5),
    ("white on green-700 (positive button)", "light", "white", col("white"), "green-700", col("green-700"), 4.5),
    ("white on rose-700 (proposed danger token)", "light", "white", col("white"), "rose-700", col("rose-700"), 4.5),
    ("white on emerald-700 (proposed success token)", "light", "white", col("white"), "emerald-700", col("emerald-700"), 4.5),
    ("dropdown item hover (gray-600 text-body on gray-100)", "light", "gray-600", col("gray-600"), "gray-100", col("gray-100"), 4.5),
    ("version footer (slate-300 on white) [intentionally faint]", "light", "slate-300", col("slate-300"), "white", col("white"), 4.5),
    ("nav-link hover accent (blue-700 on white)", "light", "blue-700", col("blue-700"), "white", col("white"), 4.5),
    ("theme-toggle icon (gray-500 on white)", "light", "gray-500", col("gray-500"), "white", col("white"), 3.0),
    # ── Raw-palette clusters, dark ──
    ("gray button text (gray-400 on gray-800)", "dark", "gray-400", col("gray-400"), "gray-800", col("gray-800"), 4.5),
    ("table body text on zebra-odd (gray-400 on gray-900)", "dark", "gray-400", col("gray-400"), "gray-900", col("gray-900"), 4.5),
    ("table body text on zebra-even (gray-400 on gray-800)", "dark", "gray-400", col("gray-400"), "gray-800", col("gray-800"), 4.5),
    ("table row hover (gray-400 on gray-600)", "dark", "gray-400", col("gray-400"), "gray-600", col("gray-600"), 4.5),
    ("thead text (gray-400 on gray-700)", "dark", "gray-400", col("gray-400"), "gray-700", col("gray-700"), 4.5),
    ("pagination link (gray-400 on gray-800)", "dark", "gray-400", col("gray-400"), "gray-800", col("gray-800"), 4.5),
    ("pagination disabled (gray-600 on gray-800)", "dark", "gray-600", col("gray-600"), "gray-800", col("gray-800"), 4.5),
    ("white on red-600 (destructive button)", "dark", "white", col("white"), "red-600", col("red-600"), 4.5),
    ("white on green-600 (positive button)", "dark", "white", col("white"), "green-600", col("green-600"), 4.5),
    ("white on emerald-600 (proposed success dark)", "dark", "white", col("white"), "emerald-600", col("emerald-600"), 4.5),
    ("dropdown item (gray-400 text-body on frosted gray-800/40)", "dark", "gray-400", col("gray-400"), "frosted", FROSTED_DARK, 4.5),
    ("dropdown item hover (white on gray-700)", "dark", "white", col("white"), "gray-700", col("gray-700"), 4.5),
    ("version footer (slate-600 on gray-950) [intentionally faint]", "dark", "slate-600", col("slate-600"), "gray-950", col("gray-950"), 4.5),
    ("nav-link hover accent (blue-500 on gray-900 navbar)", "dark", "blue-500", col("blue-500"), "gray-900", col("gray-900"), 4.5),
    # ── .responsive-table (stats page), both ──
    ("stats zebra text (gray-600 body on indigo-100)", "light", "gray-600", col("gray-600"), "indigo-100", col("indigo-100"), 4.5),
    ("stats zebra text (gray-600 body on indigo-200)", "light", "gray-600", col("gray-600"), "indigo-200", col("indigo-200"), 4.5),
    ("stats zebra border (slate-500 vs indigo-100)", "light", "slate-500", col("slate-500"), "indigo-100", col("indigo-100"), 3.0),
    ("stats zebra text (gray-400 body on slate-800)", "dark", "gray-400", col("gray-400"), "slate-800", col("slate-800"), 4.5),
    ("stats zebra text (gray-400 body on slate-900)", "dark", "gray-400", col("gray-400"), "slate-900", col("slate-900"), 4.5),
    # ── Status/chips ──
    ("toast success (green-800 on green-50)", "light", "green-800", col("green-800"), "green-50", col("green-50"), 4.5),
    ("toast success (green-200 on green-900)", "dark", "green-200", col("green-200"), "green-900", col("green-900"), 4.5),
    ("toast error (red-800 on red-50)", "light", "red-800", col("red-800"), "red-50", col("red-50"), 4.5),
    ("toast error (red-200 on red-900)", "dark", "red-200", col("red-200"), "red-900", col("red-900"), 4.5),
    ("AND chip (teal-800 on teal-100)", "light", "teal-800", col("teal-800"), "teal-100", col("teal-100"), 4.5),
    ("AND chip (teal-200 on teal-500/20)", "dark", "teal-200", col("teal-200"), "chip", TEAL_CHIP_DARK, 4.5),
    ("OR chip (orange-800 on orange-100)", "light", "orange-800", col("orange-800"), "orange-100", col("orange-100"), 4.5),
    ("OR chip (orange-200 on orange-500/20)", "dark", "orange-200", col("orange-200"), "chip", ORANGE_CHIP_DARK, 4.5),
    ("NOT-on chip (amber-900 on amber-100)", "light", "amber-900", col("amber-900"), "amber-100", col("amber-100"), 4.5),
    ("builder warning (amber-700 on white)", "light", "amber-700", col("amber-700"), "white", col("white"), 4.5),
    ("builder warning (amber-400 on gray-950)", "dark", "amber-400", col("amber-400"), "gray-950", col("gray-950"), 4.5),
    ("degraded pill text (gray-600 on secondary-medium/50)", "light", "gray-600", col("gray-600"), "pill", QUICK_PILL_LIGHT, 4.5),
    ("degraded pill text (gray-400 on secondary-medium/50)", "dark", "gray-400", col("gray-400"), "pill", QUICK_PILL_DARK, 4.5),
]

# rose-700 needed above
OKLCH["rose-700"] = (0.514, 0.222, 16.935)

rows = []
fails = []
for role, theme, fgname, fg, bgname, bg, threshold in CASES:
    r = ratio(fg, bg)
    ok = r >= threshold
    mark = "✅" if ok else ("⚠️" if r >= 3.0 and threshold == 4.5 else "❌")
    rows.append((role, theme, f"{r:.2f}", f"{threshold}", mark))
    if not ok:
        fails.append((role, theme, r, threshold))

print("| Pairing | Theme | Ratio | Req | Verdict |")
print("|---|---|---|---|---|")
for role, theme, r, t, mark in rows:
    print(f"| {role} | {theme} | {r} | {t}:1 | {mark} |")

print(f"\n{len(fails)} failures:")
for role, theme, r, t in fails:
    print(f"  {theme}: {role} — {r:.2f} (needs {t})")
