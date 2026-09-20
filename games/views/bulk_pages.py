"""The two pages the runner renders: what it will do, and how far it got."""

from collections.abc import Sequence
from typing import Any

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
from games.bulk_actions import BulkAction, Refused

#: Carries its own script, so the waypoint needs no `scripts=`.
_ContinuingBatch = custom_element_builder("continuing-batch")


def _reasons(refused: Sequence[Refused]) -> list[str]:
    """One sentence per distinct reason, in the order they were met."""
    return list(dict.fromkeys(entry.sentence for entry in refused))


def _refusals(refused: Sequence[Refused]) -> Node:
    reasons = _reasons(refused)
    if not reasons:
        return Fragment()
    return Div(class_="mb-4")[
        P(class_="text-type-body text-body mb-2")[
            f"{len(refused)} of them will be left as they are:"
        ],
        Ul(class_="list-disc ps-5 text-type-body text-body")[
            Fragment(*(Li()[reason] for reason in reasons))
        ],
    ]


def _sample(rows: Sequence[Any], total: int, cap: int) -> Node:
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
                str(row.effective_duration),
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
) -> Node:
    """What the act will do, and the fields that make it do it."""
    total = len(rows)
    return ConfirmPage(
        title=action.title,
        message=(
            f"{action.label}: {total} sessions?"
            if total
            else "None of those sessions can be recorded."
        ),
        details=Fragment(
            *(Input(type="hidden", name=name, value=value) for name, value in hidden),
            _refusals(refused),
            _sample(rows, total, sample_cap),
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
    refused: Sequence[Refused],
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
            _refusals(refused),
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
