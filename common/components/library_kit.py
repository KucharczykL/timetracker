"""Pure reusable presenters for Library-shaped summary surfaces."""

from collections.abc import Sequence
from dataclasses import dataclass

from common.components.core import Child, Fragment, Node, randomid
from common.components.custom_elements import (
    Dropdown,
    DropdownLinkItem,
    DropdownMenuPanel,
)
from common.components.primitives import (
    ControlButton,
    Dd,
    Div,
    Dl,
    Dt,
    Icon,
    Link,
    P,
    Path,
    Popover,
    Rect,
    Span,
    Svg,
    custom_element_builder,
)

_CopyControl = custom_element_builder("copy-control")


def StatisticGrid(*cards: Child) -> Node:
    return Div(
        data_statistic_grid="",
        class_="flex flex-wrap gap-6",
    )[*cards]


def StatisticCard(label: str, value: str | int, *, href: str | None = None) -> Node:
    value_text = str(value)
    value_node = (
        Link(
            href=href,
            aria_label=f"{value_text} {label}",
            class_="text-type-title",
        )[value_text]
        if href is not None
        else Span(class_="text-type-title text-heading")[value_text]
    )
    return Div(
        data_statistic_card="",
        class_="flex min-w-32 flex-1 flex-col gap-1",
    )[
        P(class_="text-type-body text-body")[label],
        value_node,
    ]


def FactList(facts: Sequence[tuple[str, Child]]) -> Node:
    return Dl(
        data_fact_list="",
        class_="grid grid-cols-1 gap-4 @xl:grid-cols-2",
    )[
        *[
            Div(class_="flex min-w-0 flex-col gap-1")[
                Dt(class_="text-type-micro-caps uppercase text-body")[label],
                Dd(class_="min-w-0 text-type-body text-heading")[value],
            ]
            for label, value in facts
        ]
    ]


def CopyableFactValue(
    value: str,
    *,
    description: str = "Copy value to clipboard",
) -> Node:
    """A monospace identifier paired with its local clipboard control."""
    return Fragment(
        Span(class_="font-mono")[value],
        " ",
        CopyControl(value, description=description),
    )


def EmptyState(title: str, description: str) -> Node:
    """A centered message for content areas with no current material.

    Containers own their headings; this deliberately renders only the empty
    content so it can be placed under a section, table, or panel title.
    """
    return Div(
        data_empty_state="",
        class_="flex min-h-40 flex-col items-center justify-center gap-2 text-center",
    )[
        P(class_="text-type-subheading text-heading")[title],
        P(class_="text-type-body text-body")[description],
    ]


def CopyControl(
    value: str,
    *,
    label: str = "Copy",
    description: str = "Copy value to clipboard",
) -> Node:
    copy_control = _CopyControl(value=value, class_="inline-flex")[
        ControlButton(
            [
                ("data-copy-control", ""),
                ("data-pop-over-anchor", ""),
                ("aria-label", description),
            ],
            variant="ghost",
        )[
            Svg(
                [
                    ("data-copy-icon", ""),
                    ("class", "h-4 w-4"),
                    ("viewBox", "0 0 24 24"),
                    ("fill", "none"),
                    ("stroke", "currentColor"),
                    ("stroke-width", "2"),
                    ("aria-hidden", "true"),
                ]
            )[
                Rect(
                    [
                        ("x", "8"),
                        ("y", "8"),
                        ("width", "13"),
                        ("height", "13"),
                        ("rx", "2"),
                    ]
                ),
                Path(
                    [("d", "M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3")]
                ),
            ],
            Span(
                data_copy_label="",
                class_="sr-only",
                aria_live="polite",
                aria_atomic="true",
            )[label],
        ],
    ]
    return Popover(
        popover_content=description,
        children=[copy_control],
        tap=False,
    )


@dataclass(frozen=True, slots=True)
class SummaryAction:
    label: str
    href: str


def SummaryList(*rows: Child) -> Node:
    return Div(
        data_summary_list="",
        class_="flex flex-col divide-y divide-default-medium",
    )[*rows]


def _summary_action_menu(
    label: str,
    actions: Sequence[SummaryAction],
) -> Node:
    menu_id = randomid(
        seed="summary-actions-",
        content=f"{label}:" + ":".join(action.href for action in actions),
        length=24,
    )
    trigger = ControlButton(
        [
            ("aria-label", f"{label} actions"),
            ("aria-haspopup", "menu"),
            ("class", "rounded-base p-2"),
        ],
        variant="ghost",
    )[Icon("ellipsis", [("aria-hidden", "true")])].as_element()
    return Dropdown(
        trigger_element=trigger,
        target_element=DropdownMenuPanel(
            items=[DropdownLinkItem(action.href, action.label) for action in actions],
            aria_label=f"{label} actions",
        ),
        id=menu_id,
        placement="bottom-end",
    )


def SummaryRow(
    *,
    label: str,
    subtitle: str,
    value: str | int | None = None,
    value_href: str | None = None,
    actions: Sequence[SummaryAction] = (),
    detail: Child | None = None,
) -> Node:
    primary_children: list[Child] = [
        Div(class_="flex min-w-0 flex-col gap-1")[
            P(class_="text-type-subheading text-heading")[label],
            P(class_="text-type-body text-body")[subtitle],
        ]
    ]
    if value is not None:
        value_text = str(value)
        value_node = (
            Link(
                href=value_href,
                aria_label=f"{value_text} {label}",
                class_="text-type-subheading tabular-nums",
            )[value_text]
            if value_href is not None
            else Span(class_="text-type-subheading text-heading tabular-nums")[
                value_text
            ]
        )
        primary_children.append(Div(class_="justify-self-end text-right")[value_node])
    if actions:
        primary_children.extend(
            [
                Div(
                    data_summary_overflow="",
                    class_="justify-self-end @2xl:hidden",
                )[_summary_action_menu(label, actions)],
                Div(
                    data_summary_wide_actions="",
                    class_="hidden items-center justify-end gap-4 @2xl:flex",
                )[*[Link(href=action.href)[action.label] for action in actions]],
            ]
        )
    grid_columns = (
        "grid-cols-[minmax(0,1fr)_auto_auto]"
        if value is not None and actions
        else "grid-cols-[minmax(0,1fr)_auto]"
        if value is not None or actions
        else "grid-cols-1"
    )
    row_children: list[Child] = [
        Div(class_=f"grid {grid_columns} items-center gap-4")[*primary_children]
    ]
    if detail is not None:
        row_children.append(
            Div(
                data_summary_detail="",
                class_="text-type-body text-body",
            )[detail]
        )
    return Div(
        data_summary_row="",
        class_="@container flex min-w-0 flex-col gap-3 py-4 first:pt-0 last:pb-0",
    )[*row_children]


__all__ = [
    "CopyControl",
    "CopyableFactValue",
    "EmptyState",
    "FactList",
    "StatisticCard",
    "StatisticGrid",
    "SummaryAction",
    "SummaryList",
    "SummaryRow",
]
