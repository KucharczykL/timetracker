"""The control a person chooses a list's columns with."""

from collections.abc import Collection, Sequence

from common.components.core import Node
from common.components.custom_elements import (
    DROPDOWN_ITEM_WITH_ICON_CLASS,
    Dropdown,
    dropdown_combobox_panel_class,
)
from common.components.primitives import (
    DISABLED_WITHIN_CLASS,
    Checkbox,
    Column,
    ColumnKey,
    ControlButton,
    Div,
    Form,
    IconTrigger,
    Label,
    Span,
)

#: What the trigger and its panel are named, for a reader who hears no glyph.
COLUMN_PICKER_LABEL = "Choose columns"

#: What the panel posts the columns it leaves shown as.
SHOWN_FIELD = "shown"

#: The shared dialog surface, which states the stratum every other dropdown
#: panel sits on: a hand-written surface opens under the row's own selectors.
#: The header row is uppercase and centred on its own; the panel is prose.
_PANEL_CLASS = f"{dropdown_combobox_panel_class('w-64')} normal-case text-left"

#: One row of the panel is a dropdown item that leads with its box.
_SHOWS_CLASS = DROPDOWN_ITEM_WITH_ICON_CLASS
#: A row whose box refuses states the one disabled look, off the box itself.
_PINNED_CLASS = (
    f"{DROPDOWN_ITEM_WITH_ICON_CLASS} cursor-not-allowed {DISABLED_WITHIN_CLASS}"
)


def _box(column: Column, *, shown: bool) -> Node:
    """One column's row: a box, and the label it answers for.

    A column that refuses to hide states a checked, disabled box rather than
    none, so the panel reads as the whole table and a person sees that the
    column is pinned instead of wondering whether the panel forgot it.
    """
    box = Checkbox(
        name=SHOWN_FIELD,
        value=column.key,
        #: A pinned column reads as shown whatever a stale stored key says,
        #: the same way the list keeps rendering it.
        checked=shown or not column.hideable,
        disabled=not column.hideable,
    )
    row_class = _SHOWS_CLASS if column.hideable else _PINNED_CLASS
    return Label(class_=row_class)[box, Span()[column.label]]


def ColumnPicker(
    columns: Sequence[Column],
    hidden: Collection[ColumnKey],
    *,
    post_url: str,
    csrf_input: Node,
    mode: str,
) -> Node:
    """The header row's icon, and the panel of boxes it opens.

    The panel holds a plain ``<form method="post">``: nothing wraps a list's
    table in a form, so the statement is ordinary HTML that reads no script
    once the panel is open. An unchecked box posts nothing, which is why the
    route stores the declared keys less the posted ones rather than reading
    what the request carries as the whole truth.
    """
    trigger = IconTrigger(
        icon="columns", label=COLUMN_PICKER_LABEL, haspopup="dialog"
    ).as_element()

    panel = Div(role="dialog", aria_label=COLUMN_PICKER_LABEL, class_=_PANEL_CLASS)[
        Form(method="post", action=post_url)[
            csrf_input,
            Div(class_="px-4 pt-1 pb-2 text-type-micro text-body-subtle")[
                "Columns shown"
            ],
            *[_box(column, shown=column.key not in hidden) for column in columns],
            Div(class_="mt-2 pt-2 border-t border-default-medium flex gap-2")[
                ControlButton(type="submit", color="blue", class_="grow")["Apply"],
                #: A named submit, so a reset posts as itself: the boxes it
                #: carries are whatever the panel stood at, which is the
                #: opposite of what a reset states.
                ControlButton(type="submit", variant="ghost", name="reset", value="1")[
                    "Reset"
                ],
            ],
        ]
    ]

    return Dropdown(
        trigger_element=trigger,
        target_element=panel,
        id=f"column-picker-{mode}",
        placement="bottom-end",
        behavior="column-picker",
    )
