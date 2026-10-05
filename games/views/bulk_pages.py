"""The pages the runner renders."""

from collections.abc import Sequence
from typing import Any

from django.template.defaultfilters import pluralize

from common.components import (
    ConfirmPage,
    Div,
    Fragment,
    Li,
    P,
    Ul,
)
from common.components.core import Node
from common.components.primitives import (
    FORM_MAX_WIDTH_CLASS,
    Column,
    Input,
    StyledTable,
    make_row,
)
from games.bulk_actions import BulkAction
from games.bulk_parts import Presentations, Refused

#: A page that asks for a fact beside its rows.
WIDE_CONFIRMATION = "max-w-3xl"

#: The confirmation's words.
WILL_BE_LEFT_ALONE = "{count} of them will be left as {pronoun}:"


def _reasons(refused: Sequence[Refused]) -> list[str]:
    """Each distinct reason once, in order."""
    return list(dict.fromkeys(entry.sentence for entry in refused))


def _refusals(count: int, reasons: Sequence[str]) -> Node:
    """How many rows are left, and why.

    The count is rows, the list is reasons: one sentence can stand over
    many rows, so a heading counting sentences would say fewer.
    """
    if not reasons:
        return Fragment()
    pronoun = "it is" if count == 1 else "they are"
    return Div(class_="mb-4")[
        P(class_="text-type-body text-body mb-2")[
            WILL_BE_LEFT_ALONE.format(count=count, pronoun=pronoun)
        ],
        Ul(class_="list-disc ps-5 text-type-body text-body")[
            Fragment(*(Li()[reason] for reason in reasons))
        ],
    ]


def _caution(action: BulkAction[Any], rows: Sequence[Any]) -> Node:
    """The act's note above the rows."""
    if action.caution is None:
        return Fragment()
    said = action.caution(rows)
    if said is None:
        return Fragment()
    return P(class_="text-type-body text-body-subtle mb-4")[said]


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
        #: The heading counts; nothing to ask.
        message=None
        if total
        #: `pluralize`: a hardcoded "s" mis-spells some subject.
        else f"None of those {action.subject}{pluralize(0)} can be changed.",
        details=Fragment(
            *(Input(type="hidden", name=name, value=value) for name, value in hidden),
            _caution(action, rows),
            _refusals(len(refused), _reasons(refused)),
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
