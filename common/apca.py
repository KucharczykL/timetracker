"""APCA (Accessible Perceptual Contrast Algorithm, APCA-W3 0.1.9) contrast.

Used to choose the foreground text color that sits on a solid background fill:
white or black, whichever APCA rates as higher contrast. The project picks its
on-fill text by APCA rather than WCAG 2 because APCA better matches perception
on saturated mid-tones (white stays readable on orange/emerald where WCAG's
ratio would force black). ``tests/test_apca.py`` uses this module to guard the
``--color-fg-on-*`` tokens in ``common/input.css`` against drift.

Pure computation, no Django.
"""

from typing import NamedTuple

type HexColor = str  # "#1447e6"
type FillName = str  # "brand", "danger", "success", "warning" (+ "-strong")
type OnColor = str  # "white" | "black"


class ThemeHex(NamedTuple):
    """A fill token's resolved sRGB hex in each theme."""

    light: HexColor
    dark: HexColor


# APCA-W3 0.1.9 constants.
_MAIN_TRC = 2.4
_R_COEFFICIENT = 0.2126
_G_COEFFICIENT = 0.7152
_B_COEFFICIENT = 0.0722
_BLACK_THRESHOLD = 0.022
_BLACK_CLAMP = 1.414
_SCALE = 1.14
_NORMAL_BACKGROUND_EXPONENT = 0.56
_NORMAL_TEXT_EXPONENT = 0.57
_REVERSE_BACKGROUND_EXPONENT = 0.65
_REVERSE_TEXT_EXPONENT = 0.62
_LOW_CLIP = 0.1
_LOW_OFFSET = 0.027
_MIN_DELTA_LUMINANCE = 0.0005

_WHITE: HexColor = "#ffffff"
_BLACK: HexColor = "#000000"

ON_HEX: dict[OnColor, HexColor] = {"white": _WHITE, "black": _BLACK}

# Each carrying fill's resolved Tailwind hex (light, dark), computed from the
# Tailwind theme's OKLCH values. Regenerate if a fill token's shade changes; the
# test in tests/test_apca.py re-derives the APCA pick from these and fails if an
# authored --color-fg-on-* token no longer matches.
FILL_HEX: dict[FillName, ThemeHex] = {
    "brand": ThemeHex("#1447e6", "#155dfc"),  # blue-700 / blue-600
    "brand-strong": ThemeHex("#193cb8", "#1447e6"),  # blue-800 / blue-700
    "danger": ThemeHex("#c70036", "#c70036"),  # rose-700 / rose-700
    "danger-strong": ThemeHex("#a50036", "#a50036"),  # rose-800 / rose-800
    "success": ThemeHex("#007a55", "#009966"),  # emerald-700 / emerald-600
    "success-strong": ThemeHex("#006045", "#007a55"),  # emerald-800 / emerald-700
    "warning": ThemeHex("#ff6900", "#f54900"),  # orange-500 / orange-600
    "warning-strong": ThemeHex("#ca3500", "#ca3500"),  # orange-700 / orange-700
}


def _channels(hex_color: HexColor) -> tuple[int, int, int]:
    value = hex_color.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _luminance(hex_color: HexColor) -> float:
    """APCA screen luminance: simple-gamma sRGB with a soft black clamp."""
    red, green, blue = _channels(hex_color)
    luminance = (
        _R_COEFFICIENT * (red / 255) ** _MAIN_TRC
        + _G_COEFFICIENT * (green / 255) ** _MAIN_TRC
        + _B_COEFFICIENT * (blue / 255) ** _MAIN_TRC
    )
    if luminance < _BLACK_THRESHOLD:
        luminance += (_BLACK_THRESHOLD - luminance) ** _BLACK_CLAMP
    return luminance


def apca_lc(text_hex: HexColor, background_hex: HexColor) -> float:
    """APCA lightness contrast (Lc), signed. Positive = dark text on light bg,
    negative = light text on dark bg; magnitude runs to roughly 106."""
    text_luminance = _luminance(text_hex)
    background_luminance = _luminance(background_hex)
    if abs(background_luminance - text_luminance) < _MIN_DELTA_LUMINANCE:
        return 0.0
    if background_luminance > text_luminance:
        contrast = (
            background_luminance**_NORMAL_BACKGROUND_EXPONENT
            - text_luminance**_NORMAL_TEXT_EXPONENT
        ) * _SCALE
        lightness_contrast = 0.0 if contrast < _LOW_CLIP else contrast - _LOW_OFFSET
    else:
        contrast = (
            background_luminance**_REVERSE_BACKGROUND_EXPONENT
            - text_luminance**_REVERSE_TEXT_EXPONENT
        ) * _SCALE
        lightness_contrast = 0.0 if contrast > -_LOW_CLIP else contrast + _LOW_OFFSET
    return lightness_contrast * 100


def pick_on_color(fill_hex: HexColor) -> OnColor:
    """Return the higher-contrast foreground ("white" or "black") for a fill."""
    white_contrast = abs(apca_lc(_WHITE, fill_hex))
    black_contrast = abs(apca_lc(_BLACK, fill_hex))
    return "white" if white_contrast >= black_contrast else "black"
