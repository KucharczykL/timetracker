"""APCA math checks + the fill on-color drift/threshold guard.

The guard re-derives, for every solid fill token, the APCA-picked foreground
(white/black) from its resolved hex in both themes and asserts the authored
``--color-fg-on-*`` token in ``common/input.css`` matches and clears the APCA
contrast floor. A shade change or a hand-edited token that no longer matches
APCA fails here — the analogue of ``gen_icons --check`` for the on-color tokens.
"""

import re
import unittest
from pathlib import Path

from common.apca import FILL_HEX, ON_HEX, apca_lc, pick_on_color

# APCA Lc floor for bold/large UI text (button labels). Every current fill's
# white pick clears this comfortably; warning/orange-500 (Lc ~59) is the floor.
CONTRAST_FLOOR = 45.0

INPUT_CSS = Path(__file__).resolve().parent.parent / "common" / "input.css"


class ApcaMathTest(unittest.TestCase):
    def test_reference_pairs(self) -> None:
        # Published APCA-W3 reference magnitudes.
        self.assertAlmostEqual(apca_lc("#ffffff", "#000000"), -107.9, delta=1.0)
        self.assertAlmostEqual(apca_lc("#000000", "#ffffff"), 106.0, delta=1.0)

    def test_equal_colors_are_zero(self) -> None:
        self.assertEqual(apca_lc("#777777", "#777777"), 0.0)

    def test_pick_on_color_by_fill_lightness(self) -> None:
        self.assertEqual(pick_on_color("#000000"), "white")
        self.assertEqual(pick_on_color("#1447e6"), "white")  # blue-700 fill
        self.assertEqual(pick_on_color("#ffdd00"), "black")  # bright yellow fill


def _authored_on_colors(css: str) -> dict[str, str]:
    """Map fill name -> authored on-color ("white"/"black") from @theme tokens."""
    authored: dict[str, str] = {}
    for name, value in re.findall(
        r"--color-fg-on-([a-z-]+):\s*var\(--color-(white|black)\);", css
    ):
        authored[name] = value
    return authored


class FillTokenGuard(unittest.TestCase):
    def setUp(self) -> None:
        self.authored = _authored_on_colors(INPUT_CSS.read_text(encoding="utf-8"))

    def test_every_fill_has_an_on_color_token(self) -> None:
        for name in FILL_HEX:
            self.assertIn(
                name,
                self.authored,
                f"--color-fg-on-{name} missing from common/input.css @theme",
            )

    def test_authored_matches_apca_pick_both_themes(self) -> None:
        for name, theme_hex in FILL_HEX.items():
            expected = {pick_on_color(theme_hex.light), pick_on_color(theme_hex.dark)}
            self.assertEqual(
                len(expected),
                1,
                f"{name}: APCA pick differs between light/dark "
                f"({theme_hex}); author a .dark override for --color-fg-on-{name}",
            )
            computed = expected.pop()
            self.assertEqual(
                self.authored.get(name),
                computed,
                f"--color-fg-on-{name} is '{self.authored.get(name)}' but APCA "
                f"picks '{computed}' for {theme_hex}",
            )

    def test_on_color_clears_contrast_floor(self) -> None:
        for name, theme_hex in FILL_HEX.items():
            for theme, fill_hex in (
                ("light", theme_hex.light),
                ("dark", theme_hex.dark),
            ):
                on_color = pick_on_color(fill_hex)
                contrast = abs(apca_lc(ON_HEX[on_color], fill_hex))
                self.assertGreaterEqual(
                    contrast,
                    CONTRAST_FLOOR,
                    f"{name} {theme}: {on_color} on {fill_hex} is Lc {contrast:.1f}, "
                    f"below floor {CONTRAST_FLOOR}",
                )
