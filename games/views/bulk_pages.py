"""The two pages the runner renders: what it will do, and how far it got."""

from collections.abc import Sequence
from typing import Any

from common.components import ConfirmPage, Div, Fragment, Li, P, Ul
from common.components.core import Node
from common.components.primitives import Column, Input, StyledTable, make_row
from games.bulk_actions import BulkAction, Refused


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
