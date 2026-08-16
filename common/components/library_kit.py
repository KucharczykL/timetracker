"""Pure reusable presenters for Library-shaped summary surfaces."""

from collections.abc import Sequence

from common.components.core import Child, Node
from common.components.primitives import Dd, Div, Dl, Dt, Link, P, Span


def StatisticGrid(*cards: Child) -> Node:
    return Div(
        data_statistic_grid="",
        class_="grid grid-cols-2 gap-3 @3xl:grid-cols-4",
    )[*cards]


def StatisticCard(
    label: str,
    value: str | int,
    href: str | None = None,
) -> Node:
    value_text = str(value)
    value_node = (
        Link(
            href=href,
            aria_label=f"{value_text} {label}",
            class_="text-type-title text-heading",
        )[value_text]
        if href is not None
        else Span(class_="text-type-title text-heading")[value_text]
    )
    return Div(
        data_statistic_card="",
        class_=(
            "flex min-w-0 flex-col gap-1 rounded-base border border-default "
            "bg-neutral-secondary-medium p-4"
        ),
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


__all__ = ["FactList", "StatisticCard", "StatisticGrid"]
