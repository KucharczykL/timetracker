"""The quick bar's free-text field: a trigger joined to a box.

The trigger is a mark and a chevron, because the facets compete for the row.
One that spells its mode costs about four times the width. The wider menu
shows each mark beside its mode in words, so one opening teaches the six.
"""

from common.components.core import Node
from common.components.custom_elements import (
    DROPDOWN_ITEM_CLASS,
    Dropdown,
    DropdownMenuPanel,
    _SearchFieldElement,
)
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

#: A mode's token, its mark, and its words.
type MatchMode = tuple[str, str, str]

#: The six modes, in the menu's order; the first is the default.
#:
#: ``IS_NULL`` and ``NOT_NULL`` are absent: "is null" across an OR of several
#: columns states nothing a person could mean.
MATCH_MODES: tuple[MatchMode, ...] = (
    ("INCLUDES", "match-includes", "includes"),
    ("EXCLUDES", "match-not-includes", "excludes"),
    ("EQUALS", "match-is", "is"),
    ("NOT_EQUALS", "match-not-is", "is not"),
    ("MATCHES_REGEX", "match-regex", "matches regex"),
    ("NOT_MATCHES_REGEX", "match-not-regex", "not matches regex"),
)

DEFAULT_MATCH_MODE = MATCH_MODES[0][0]

_BY_TOKEN = {token: (icon, words) for token, icon, words in MATCH_MODES}

#: The box states no rounding and no shadow; the field decides both.
_INPUT_CLASS = (
    "min-w-0 w-48 sm:w-56 border border-default-medium bg-neutral-secondary-medium "
    "text-heading text-type-input px-3 min-h-control placeholder:text-body "
    "focus:ring-1 focus:ring-brand focus:border-brand focus:outline-hidden"
)

_MENU_ROW_CLASS = f"{DROPDOWN_ITEM_CLASS} flex items-center gap-3 whitespace-nowrap"

_MENU_MARK_CLASS = "shrink-0"


def _mode_row(token: str, icon: str, words: str, *, current: bool) -> Node:
    return Li(role="presentation")[
        Button(
            [
                ("type", "button"),
                ("role", "menuitemradio"),
                ("aria-checked", "true" if current else "false"),
                ("tabindex", "-1"),
                ("data-match-mode", token),
                ("class", _MENU_ROW_CLASS),
            ]
        )[
            Icon(icon, attributes=[("class", _MENU_MARK_CLASS)]),
            Span()[words],
        ]
    ]


def SearchField(
    *,
    value: str = "",
    modifier: str = DEFAULT_MATCH_MODE,
    name: str = "quick-search",
    placeholder: str = "",
    id: str = "quick-search-field",
) -> Node:
    """A match-mode trigger and a text box, joined.

    ``placeholder`` names the columns this list's search reads, which differ
    per filter. The root self-describes like every filter widget, so the bar's
    generic serializer needs no case for it, and carries ``data-modifier``:
    how a widget with no modifier ``select`` states its mode.
    """
    if modifier not in _BY_TOKEN:
        modifier = DEFAULT_MATCH_MODE
    icon, words = _BY_TOKEN[modifier]

    trigger = ControlButton(
        [
            ("data-match-trigger", ""),
            ("aria-haspopup", "menu"),
            # The name states the value, not just the control.
            ("aria-label", f"Match mode: {words}"),
            ("title", f"Match mode: {words}"),
        ],
        # segmented, not ghost: ghost bakes rounded-base for the field to undo,
        # and its border-transparent ties with any colour added beside it.
        variant="segmented",
        color="gray",
    )[
        Icon(icon, attributes=[("data-match-mark", "")]),
        Icon("arrowdown", attributes=[("class", "h-3 w-3")]),
    ].as_element()

    menu = DropdownMenuPanel(
        items=[
            _mode_row(token, mark, mode_words, current=token == modifier)
            for token, mark, mode_words in MATCH_MODES
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
SEARCH_PLACEHOLDERS: dict[str, str] = {
    "games": "Search name, platform",
    "sessions": "Search game, platform, device",
    "purchases": "Search name, game, platform",
    "playthroughs": "Search game, name, notes",
    "historical_playtime": "Search game, platform, device, note",
    "devices": "Search name, type",
    "platforms": "Search name, group",
}
