"""The pages the runner renders."""

from collections.abc import Sequence
from typing import Any

from django.template.defaultfilters import pluralize

from common.components import (
    ConfirmPage,
    ControlButton,
    Div,
    Form,
    Fragment,
    Li,
    P,
    Ul,
)
from common.components.core import Node, Safe
from common.components.primitives import (
    FORM_MAX_WIDTH_CLASS,
    Column,
    Input,
    StyledTable,
    custom_element_builder,
    make_row,
)
from games.bulk_actions import BulkAction, Presentations, Refused

#: A page that asks for a fact beside its rows.
WIDE_CONFIRMATION = "max-w-3xl"

#: The confirmation's words, and the waypoint's.
WILL_BE_LEFT_ALONE = "{count} of them will be left as {pronoun}:"
LEFT_ALONE = "{count} left as {pronoun} so far:"

#: Carries its own script; no `scripts=` needed.
_ContinuingBatch = custom_element_builder("continuing-batch")


def _reasons(refused: Sequence[Refused]) -> list[str]:
    """Each distinct reason once, in order."""
    return list(dict.fromkeys(entry.sentence for entry in refused))


def _refusals(count: int, reasons: Sequence[str], lead: str) -> Node:
    """How many rows are left, and why.

    The count is rows, the list is reasons: one sentence can stand over
    many rows, so a heading counting sentences would say fewer.
    """
    if not reasons:
        return Fragment()
    pronoun = "it is" if count == 1 else "they are"
    return Div(class_="mb-4")[
        P(class_="text-type-body text-body mb-2")[
            lead.format(count=count, pronoun=pronoun)
        ],
        Ul(class_="list-disc ps-5 text-type-body text-body")[
            Fragment(*(Li()[reason] for reason in reasons))
        ],
    ]


def _sample(
    action: BulkAction[Any],
    rows: Sequence[Any],
    total: int,
    cap: int,
    presentations: Presentations,
) -> Node:
    """The rows the act states, to a cap; keys ride the field."""
    if not rows:
        return Fragment()
    shown = rows[:cap]
    table = StyledTable(
        columns=[
            Column(column.heading, None, align=column.align)
            for column in action.preview
        ],
        rows=[
            make_row(
                *(column.cell(row, presentations) for column in action.preview),
                data_bulk_sample_row="",
            )
            for row in shown
        ],
    )
    if total <= len(shown):
        return table
    return Fragment(
        table,
        P(class_="text-type-caption text-muted mt-2")[
            f"and {total - len(shown)} more."
        ],
    )


def RefusedBatch(
    *,
    title: str,
    sentence: str,
    post_url: str,
    csrf_token: str,
    cancel_url: str,
) -> Node:
    """Nothing was done, and why: no submit."""
    return ConfirmPage(
        title=title,
        message=sentence,
        post_url=post_url,
        csrf_token=csrf_token,
        cancel_url=cancel_url,
        confirm_label=None,
    )


def ConfirmBatch(
    action: BulkAction[Any],
    *,
    rows: Sequence[Any],
    refused: Sequence[Refused],
    hidden: Sequence[tuple[str, str]],
    post_url: str,
    csrf_token: str,
    cancel_url: str,
    sample_cap: int,
    presentations: Presentations,
    choice: Node | None = None,
    refusal: Sequence[str] = (),
) -> Node:
    """What the act will do, plus fields.

    `refusal` is why the last press was turned down.
    """
    total = len(rows)
    return ConfirmPage(
        title=action.title.for_count(total),
        message=(
            f"{action.label}: {total} {action.subject}{pluralize(total)}?"
            if total
            #: `pluralize` here too: a hardcoded "s" reads the plural
            #: of one subject and mis-spells the next.
            else f"None of those {action.subject}{pluralize(0)} can be changed."
        ),
        details=Fragment(
            *(Input(type="hidden", name=name, value=value) for name, value in hidden),
            _refusals(len(refused), _reasons(refused), WILL_BE_LEFT_ALONE),
            _sample(action, rows, total, sample_cap, presentations),
        ),
        choice=choice,
        refusal=refusal,
        post_url=post_url,
        csrf_token=csrf_token,
        cancel_url=cancel_url,
        #: A control needs the sample's room.
        max_width=WIDE_CONFIRMATION if choice is not None else FORM_MAX_WIDTH_CLASS,
        #: Nothing to do admits no press.
        confirm_label=action.confirm_label if total else None,
        #: The act declares one colour.
        confirm_color=action.color,
    )


def ProgressBatch(
    action: BulkAction[Any],
    *,
    done: int,
    total: int,
    refused: int,
    reasons: Sequence[str],
    hidden: Sequence[tuple[str, str]],
    post_url: str,
    csrf_token: str,
    stop_name: str,
) -> Node:
    """How far the batch got.

    Continue is for a reader whose element posts nothing.
    """
    return _ContinuingBatch()[
        Div(class_="mx-auto w-full max-w-xl p-5 @container")[
            P(class_="text-type-heading text-heading mb-2")[
                action.title.for_count(total)
            ],
            P(class_="text-type-body text-body mb-4")[
                f"{done} of {total} done. Continuing with the rest."
            ],
            _refusals(refused, reasons, LEFT_ALONE),
            Form(method="post", action=post_url, data_continuing_batch_form="")[
                Safe(
                    '<input type="hidden" name="csrfmiddlewaretoken" '
                    f'value="{csrf_token}">'
                ),
                Fragment(
                    *(
                        Input(type="hidden", name=name, value=value)
                        for name, value in hidden
                    )
                ),
                Div(class_="flex flex-wrap items-center gap-2")[
                    ControlButton(type="submit", color="blue")["Continue"],
                    ControlButton(
                        type="submit",
                        name=stop_name,
                        value="1",
                        color="gray",
                        data_continuing_batch_stop="",
                    )["Stop"],
                ],
            ],
        ]
    ]
