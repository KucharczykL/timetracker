"""The quick bar's free-text field: a match-mode trigger joined to a text box.

``search`` is a criterion on all seven filters and the only one with no
control. It reaches the database through ``search_q`` and it survives in a
saved preset; the flat bar that used to render it is gone. This gives it a
control again, and states the match mode it never expressed.

The trigger is an icon and a chevron, because the row is one line that the
facets compete for — a trigger that spells its mode costs about four times the
width, taken from the facets that stay in the row rather than move into the
overflow menu. The menu is wider than the trigger and shows each mode's mark
beside the mode in words, so a person who opens it once has read what each
mark means.
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

#: A match mode's token, its mark, and the words the menu prints for it.
type MatchMode = tuple[str, str, str]

#: The six modes the field states, in the order the menu lists them. ``IS_NULL``
#: and ``NOT_NULL`` are absent: ``search`` reads several columns at once, and
#: "is null" across an OR of them states nothing a person could mean. This order
#: is the menu's, and the first entry is the mode a field with none states.
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

#: The text box. It states no rounding and no shadow of its own — the segmented
#: field decides both, for every member — and it carries the control height so a
#: field of one member is still a row-control.
_INPUT_CLASS = (
    "min-w-0 w-48 sm:w-56 border border-default-medium bg-neutral-secondary-medium "
    "text-heading text-type-input px-3 min-h-control placeholder:text-body "
    "focus:ring-1 focus:ring-brand focus:border-brand focus:outline-hidden"
)

#: The trigger states no rounding and no border colour of its own. It is
#: ``segmented``, the variant a member of a joined control takes: it carries the
#: shared border and leaves every corner to whatever joins it. The ghost variant
#: would fight that twice — it bakes ``rounded-base``, and its
#: ``border-transparent`` ties on specificity with any colour added beside it, so
#: which one wins is decided by stylesheet order.

_MENU_ROW_CLASS = f"{DROPDOWN_ITEM_CLASS} flex items-center gap-3 whitespace-nowrap"

#: The mark of the mode a row states, then the mode in words. The row that is
#: current is marked, so the menu says which mode the field holds.
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
    """The field: a match-mode trigger and a text box, joined as one control.

    ``placeholder`` names what the mode reads on this list, because which
    columns a search spans differs per filter and the field is where a person
    can read it.

    The root carries the self-describe attributes every filter widget root
    carries, so the bar's generic serializer reads this field with no case of
    its own — plus ``data-modifier``, which is how a widget that renders no
    modifier ``select`` states its mode.
    """
    if modifier not in _BY_TOKEN:
        modifier = DEFAULT_MATCH_MODE
    icon, words = _BY_TOKEN[modifier]

    trigger = ControlButton(
        [
            ("data-match-trigger", ""),
            ("aria-haspopup", "menu"),
            # The name states the value, so a reader who cannot see the mark
            # hears the mode rather than a button with none.
            ("aria-label", f"Match mode: {words}"),
            ("title", f"Match mode: {words}"),
        ],
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
        # The mode is the field's state, not the box's; the box carries no
        # name the server reads, because the bar serializes to filter JSON.
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


#: What a search reads on each list, in the words the field prints. The columns
#: are ``_extra_q``'s, per filter; a person reads them here rather than guessing
#: which ones a free-text box spans.
SEARCH_PLACEHOLDERS: dict[str, str] = {
    "games": "Search name, platform",
    "sessions": "Search game, platform, device",
    "purchases": "Search name, game, platform",
    "playthroughs": "Search game, name, notes",
    "historical_playtime": "Search game, platform, device, note",
    "devices": "Search name, type",
    "platforms": "Search name, group",
}
