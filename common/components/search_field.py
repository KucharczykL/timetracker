"""The quick bar's free-text field: a trigger joined to a box.

The trigger is a mark and a chevron, because the facets compete for the row.
One that spells its mode costs about four times the width. The wider menu
shows each mark beside its mode in words, so one opening teaches the six.
"""

from typing import Literal, NamedTuple

from common.components.core import Node
from common.components.custom_elements import (
    DROPDOWN_ITEM_CLASS,
    Dropdown,
    DropdownMenuPanel,
    FilterMode,
    _SearchFieldElement,
)
from common.components.icons_generated import ICON_NODES
from common.components.primitives import (
    Button,
    ControlButton,
    Icon,
    Input,
    Li,
    SegmentedField,
    Span,
    filter_widget_attributes,
)
from common.criteria import SEARCH_LOOKUPS

#: A mode this field can state, as the wire spells it.
type MatchModeToken = Literal[
    "INCLUDES",
    "EXCLUDES",
    "EQUALS",
    "NOT_EQUALS",
    "MATCHES_REGEX",
    "NOT_MATCHES_REGEX",
]


class MatchMode(NamedTuple):
    """One mode: its token, its mark's slug, its words."""

    token: MatchModeToken
    mark: str
    words: str


#: The modes, in the menu's order; the first is a fresh field's.
#:
#: The order is the menu's and lives here. Which modes exist does not: the
#: check below reads ``SEARCH_LOOKUPS``, so a mode ``search_q`` gains or loses
#: fails at import rather than rendering a control the server refuses.
MATCH_MODES: tuple[MatchMode, ...] = (
    MatchMode("INCLUDES", "match-includes", "includes"),
    MatchMode("EXCLUDES", "match-not-includes", "excludes"),
    MatchMode("EQUALS", "match-is", "is"),
    MatchMode("NOT_EQUALS", "match-not-is", "is not"),
    MatchMode("MATCHES_REGEX", "match-regex", "matches regex"),
    MatchMode("NOT_MATCHES_REGEX", "match-not-regex", "not matches regex"),
)

#: Every token the field renders, for a membership test per key per render.
MATCH_MODE_TOKENS: frozenset[str] = frozenset(mode.token for mode in MATCH_MODES)

if MATCH_MODE_TOKENS != {modifier.value for modifier in SEARCH_LOOKUPS}:
    raise RuntimeError(
        "The match modes and search_q's lookups name different modes: "
        f"{sorted(MATCH_MODE_TOKENS)} against "
        f"{sorted(modifier.value for modifier in SEARCH_LOOKUPS)}"
    )

# A mark no snippet draws reads as ``unspecified``, and six alike.
#
# ``get_icon_node`` falls back rather than raising, so a mistyped slug renders
# the placeholder mark in the trigger and in every menu row, with every test
# still green. The slugs are pinned here instead.
if _absent := sorted(mode.mark for mode in MATCH_MODES if mode.mark not in ICON_NODES):
    raise RuntimeError(f"No icon snippet draws these match marks: {_absent}")

#: A fresh field's mode, which is what people reach for.
DEFAULT_MATCH_MODE: MatchModeToken = "INCLUDES"

_BY_TOKEN: dict[str, MatchMode] = {mode.token: mode for mode in MATCH_MODES}

#: The box states no rounding and no shadow; the field decides both.
_INPUT_CLASS = (
    "min-w-0 w-48 sm:w-56 border border-default-medium bg-neutral-secondary-medium "
    "text-heading text-type-input px-3 min-h-control placeholder:text-body "
    "focus:ring-1 focus:ring-brand focus:border-brand focus:outline-hidden"
)

_MENU_ROW_CLASS = f"{DROPDOWN_ITEM_CLASS} flex items-center gap-3 whitespace-nowrap"

_MENU_MARK_CLASS = "shrink-0"


def _mode_row(mode: MatchMode, *, current: bool) -> Node:
    return Li(role="presentation")[
        Button(
            [
                ("type", "button"),
                ("role", "menuitemradio"),
                ("aria-checked", "true" if current else "false"),
                ("tabindex", "-1"),
                ("data-match-mode", mode.token),
                ("class", _MENU_ROW_CLASS),
            ]
        )[
            Icon(mode.mark, attributes=[("class", _MENU_MARK_CLASS)]),
            Span()[mode.words],
        ]
    ]


def SearchField(
    *,
    value: str = "",
    modifier: MatchModeToken = DEFAULT_MATCH_MODE,
    name: str = "quick-search",
    placeholder: str = "",
    id: str = "quick-search-field",
) -> Node:
    """A match-mode trigger and a text box, joined.

    ``placeholder`` names the columns this list's search reads, which differ
    per filter, and is the box's accessible name: the field carries no visible
    label. The root self-describes like every filter widget, so the bar's
    generic serializer needs no case for it, and carries ``data-modifier``:
    how a widget with no modifier ``select`` states its mode.

    A mode outside the six is refused rather than coerced. ``is_quick_editable``
    is the one place allowed to degrade a filter it cannot render: silently
    rendering *includes* over a mode the server reads otherwise is how a filter
    widens on the next apply.
    """
    mode = _BY_TOKEN.get(modifier)
    if mode is None:
        raise ValueError(
            f"{modifier!r} is not a mode this field states. One of: "
            + ", ".join(sorted(MATCH_MODE_TOKENS))
        )

    trigger = ControlButton(
        [
            ("data-match-trigger", ""),
            ("aria-haspopup", "menu"),
            # The name states the value, not just the control.
            ("aria-label", f"Match mode: {mode.words}"),
            ("title", f"Match mode: {mode.words}"),
        ],
        # segmented, not ghost: ghost bakes rounded-base for the field to undo,
        # and its border-transparent ties with any colour added beside it.
        variant="segmented",
        color="gray",
    )[
        Icon(mode.mark, attributes=[("data-match-mark", "")]),
        Icon("arrowdown", attributes=[("class", "h-3 w-3")]),
    ].as_element()

    menu = DropdownMenuPanel(
        items=[
            _mode_row(candidate, current=candidate.token == modifier)
            for candidate in MATCH_MODES
        ],
        aria_label="Match mode",
        menu_width="w-max",
    )

    field = Input(
        [("data-match-value", "")],
        type="text",
        name=name,
        value=value,
        placeholder=placeholder,
        aria_label=placeholder or "Search",
        class_=_INPUT_CLASS,
        autocomplete="off",
    )

    return _SearchFieldElement(
        [
            *filter_widget_attributes(["search"], "string"),
            ("data-modifier", modifier),
        ]
    )[
        SegmentedField(
            leading=Dropdown(
                trigger_element=trigger,
                target_element=menu,
                id=f"{id}-mode",
            ),
            field=field,
        )
    ]


#: The columns each list's search reads, in the field's own words.
SEARCH_PLACEHOLDERS: dict[FilterMode, str] = {
    "games": "Search name, platform",
    "sessions": "Search game, platform, device",
    "purchases": "Search name, game, platform",
    "playthroughs": "Search game, name, notes",
    "historical_playtime": "Search game, platform, device, note",
    "devices": "Search name, type",
    "platforms": "Search name, group",
}
