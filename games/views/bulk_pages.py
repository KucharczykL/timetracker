"""The pages the runner renders.

What the act will do, how far it got, and why nothing more happened.
Its words are the reclassification's, because that is the one act
declared; #712 brings the second, and the nouns move to the act then.
"""

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
    Column,
    Input,
    StyledTable,
    custom_element_builder,
    make_row,
)
from common.duration_presentation import DurationPresentation
from games.bulk_actions import BulkAction, Refused

#: What the confirmation says of the rows the act will not reach, and
#: what the waypoint says of the ones it has met so far. One row is
#: "it is", and a batch of one is the ordinary case on a row's own
#: control, so neither line may read as though it were many.
WILL_BE_LEFT_ALONE = "{count} of them will be left as {pronoun}:"
LEFT_ALONE = "{count} left as {pronoun} so far:"

#: Carries its own script, so the waypoint needs no `scripts=`.
_ContinuingBatch = custom_element_builder("continuing-batch")


def _reasons(refused: Sequence[Refused]) -> list[str]:
    """One sentence per distinct reason, in the order they were met."""
    return list(dict.fromkeys(entry.sentence for entry in refused))


def _refusals(count: int, reasons: Sequence[str], lead: str) -> Node:
    """How many rows are left alone, and why.

    The count is the rows and the list is the reasons, which are two
    numbers: one reason may stand over many rows, and a heading that
    counted sentences would tell a person fewer rows were left than
    were.
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
    rows: Sequence[Any], total: int, cap: int, durations: DurationPresentation
) -> Node:
    """The rows, to a cap.

    Every key still rides the hidden field; this is what a person
    reads, and a table of thousands is not read.
    """
    if not rows:
        return Fragment()
    shown = rows[:cap]
    table = StyledTable(
        columns=[
            Column("Game", None),
            Column("Day", None),
            Column("Duration", None, align="right"),
        ],
        rows=[
            make_row(
                row.playthrough.player_game.game.name,
                str(row.effective_day),
                durations.format(row.effective_duration),
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
    """Nothing was done, and here is why.

    It states no act, because the reason may be that there is none left
    to state. No submit and no token, so the page it draws cannot act.
    """
    return ConfirmPage(
        title=title,
        message=sentence,
        post_url=post_url,
        csrf_token=csrf_token,
        cancel_url=cancel_url,
        confirm_label=None,
    )


def ConfirmBatch(
    action: BulkAction,
    *,
    rows: Sequence[Any],
    refused: Sequence[Refused],
    hidden: Sequence[tuple[str, str]],
    post_url: str,
    csrf_token: str,
    cancel_url: str,
    sample_cap: int,
    durations: DurationPresentation,
) -> Node:
    """What the act will do, and the fields that make it do it."""
    total = len(rows)
    return ConfirmPage(
        title=action.title,
        message=(
            f"{action.label}: {total} {action.subject}{pluralize(total)}?"
            if total
            else "None of those sessions can be recorded."
        ),
        details=Fragment(
            *(Input(type="hidden", name=name, value=value) for name, value in hidden),
            _refusals(len(refused), _reasons(refused), WILL_BE_LEFT_ALONE),
            _sample(rows, total, sample_cap, durations),
        ),
        post_url=post_url,
        csrf_token=csrf_token,
        cancel_url=cancel_url,
        #: Nothing to do admits no press.
        confirm_label=action.confirm_label if total else None,
    )


def ProgressBatch(
    action: BulkAction,
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
    """How far the batch got, and the press that carries it on.

    A waypoint, not a question: the act is already running. With
    scripting the element around the form continues by itself, so the
    Continue press is what a reader without it uses.
    """
    return _ContinuingBatch()[
        Div(class_="mx-auto w-full max-w-xl p-5 @container")[
            P(class_="text-type-heading text-heading mb-2")[action.title],
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
