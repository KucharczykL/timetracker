"""The control that selects a list's columns."""

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

#: The name of the trigger and its panel.
COLUMN_PICKER_LABEL = "Choose columns"

#: The field the panel posts shown keys as.
SHOWN_FIELD = "shown"

#: The field that only the reset button posts.
RESET_FIELD = "reset"

#: The shared surface. It states the layer, which a hand-written one omits
#: and then opens below the device selector of each row. The header row is
#: uppercase and right-aligned; the panel is prose.
_PANEL_CLASS = f"{dropdown_combobox_panel_class('w-64')} normal-case text-left"

#: A panel row is a dropdown item.
_SHOWS_CLASS = DROPDOWN_ITEM_WITH_ICON_CLASS
#: A refusing row wears the one disabled look.
_PINNED_CLASS = (
    f"{DROPDOWN_ITEM_WITH_ICON_CLASS} cursor-not-allowed {DISABLED_WITHIN_CLASS}"
)


def _box(column: Column, *, shown: bool) -> Node:
    """One column's box and its label.

    A column that refuses to hide shows a checked and disabled box, not no box:
    the panel is then the whole table, and a reader sees that the column is
    pinned instead of missing.
    """
    box = Checkbox(
        name=SHOWN_FIELD,
        value=column.key,
        #: A pinned column reads shown, whatever the row says.
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
    """The header icon and the panel it opens.

    Nothing wraps a list's table in a form, thus the panel holds its own. Once
    the panel is open the statement needs no script.
    """
    trigger = IconTrigger(
        #: A glyph says nothing to a pointer. The row menu beside it states
        #: no title, because its name is its row rather than one word.
        [("title", COLUMN_PICKER_LABEL)],
        icon="columns",
        label=COLUMN_PICKER_LABEL,
        haspopup="dialog",
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
                #: Named, so a reset posts as itself.
                ControlButton(
                    type="submit", variant="ghost", name=RESET_FIELD, value="1"
                )["Reset"],
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
