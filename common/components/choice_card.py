"""A radio group whose options are whole rows.

The mark is the first thing in a card and the first thing in the DOM, so a
card reads as the option it is rather than as a row with a control at the
end. Content goes through the htpy ``[]`` slot, as ``Modal`` does.
"""

from __future__ import annotations

from typing import Final

from common.components.core import BaseComponent, Children, Node, as_children
from common.components.elements import Fieldset, Legend
from common.components.primitives import Div, Label, Radio, Span

#: The card's own mark, told apart from any control it hosts.
CHOICE_CARD_MARK_ATTRIBUTE: Final[str] = "data-choice-card"

_CARD_CLASS: Final[str] = (
    "grid grid-cols-[1fr_auto] gap-x-3 gap-y-2 rounded-base border p-3 "
    "border-default bg-neutral-primary items-start "
    # Scoped to the card's own mark. A hosted control may hold checked
    # radios of its own, and a bare :has(:checked) lights every card.
    f"has-[[{CHOICE_CARD_MARK_ATTRIBUTE}]:checked]:border-brand "
    f"has-[[{CHOICE_CARD_MARK_ATTRIBUTE}]:checked]:ring-1 "
    f"has-[[{CHOICE_CARD_MARK_ATTRIBUTE}]:checked]:ring-brand "
    f"has-[[{CHOICE_CARD_MARK_ATTRIBUTE}]:checked]:bg-neutral-secondary-soft"
)

#: A bare radio is 16px wide; sr-only text collapses the label around it.
#: The column holds the target instead.
_MARK_CLASS: Final[str] = (
    "col-start-1 row-start-1 flex min-h-control cursor-pointer items-center "
    "gap-2 text-type-label text-heading @2xl/edition:min-w-11"
)

_GROUP_CLASS: Final[str] = "@container/edition flex flex-col gap-3"


class ChoiceCardGroup(BaseComponent):
    """One group of choice cards, named for whoever cannot see it.

    ``columns`` is the container-query track list the group's header and
    every card in it declare. They are separate grids, so a track stated
    once in each is the only thing that keeps a header over its control.
    """

    def __init__(
        self,
        *,
        name: str,
        legend: str,
        columns: str = "",
        class_: str = "",
        _children: Children = None,
    ) -> None:
        self.name = name
        self.legend = legend
        self.columns = columns
        self.class_ = class_
        self._children = as_children(_children)

    def __getitem__(self, children: Children) -> ChoiceCardGroup:
        return ChoiceCardGroup(
            name=self.name,
            legend=self.legend,
            columns=self.columns,
            class_=self.class_,
            _children=children,
        )

    def render(self) -> Node:
        return Fieldset(
            class_=" ".join(
                part for part in (_GROUP_CLASS, self.columns, self.class_) if part
            ),
            data_choice_card_group=self.name,
        )[Legend(class_="sr-only")[self.legend], *self._children]


class ChoiceCard(BaseComponent):
    """One option: its mark, then whatever the caller puts in it."""

    def __init__(
        self,
        *,
        name: str,
        value: str,
        label: str,
        checked: bool = False,
        columns: str = "",
        class_: str = "",
        _children: Children = None,
    ) -> None:
        self.name = name
        self.value = value
        self.label = label
        self.checked = checked
        self.columns = columns
        self.class_ = class_
        self._children = as_children(_children)

    def __getitem__(self, children: Children) -> ChoiceCard:
        return ChoiceCard(
            name=self.name,
            value=self.value,
            label=self.label,
            checked=self.checked,
            columns=self.columns,
            class_=self.class_,
            _children=children,
        )

    def render(self) -> Node:
        mark = Label(class_=_MARK_CLASS)[
            Radio(
                [(CHOICE_CARD_MARK_ATTRIBUTE, "")],
                name=self.name,
                value=self.value,
                checked=self.checked,
                aria_label=self.label,
            ),
            # Redundant beside the aria-label above the breakpoint, and the
            # only thing naming the mark below it.
            Span(class_="@2xl/edition:sr-only")[self.label],
        ]
        return Div(
            class_=" ".join(
                part for part in (_CARD_CLASS, self.columns, self.class_) if part
            ),
        )[mark, *self._children]
