"""Read and state which columns a person turned off on a list."""

from collections.abc import Collection, Sequence
from typing import NamedTuple, cast

from django.contrib.auth.models import User
from django.http import HttpRequest

from common.components import Column, ColumnKey, ColumnPicker, CsrfInput, Node
from common.returns import action_url
from games.models import FilterPreset, ListColumnChoice

LIST_MODES = frozenset(mode for mode, _ in FilterPreset.MODE_CHOICES)


def _known(mode: str) -> str:
    if mode not in LIST_MODES:
        raise ValueError(f"no list states the mode {mode!r}")
    return mode


def _stated(user: User, mode: str) -> dict[ColumnKey, bool]:
    """What this person states about this list, by key. Empty where nothing."""
    stored = (
        ListColumnChoice.objects.filter(user=user, mode=_known(mode))
        .values_list("shown", flat=True)
        .first()
    )
    return stored or {}


def hidden_columns(
    user: User, mode: str, columns: Sequence[Column]
) -> frozenset[ColumnKey]:
    """The keys this person does not show on this list.

    A column the person states nothing about reads its own default, so a column
    added later starts where it says rather than where an older row left it.
    """
    stated = _stated(user, mode)
    return frozenset(
        column.key
        for column in columns
        if not stated.get(column.key, not column.hidden_by_default)
    )


def state_shown_columns(
    user: User, mode: str, shown: Collection[ColumnKey], columns: Sequence[Column]
) -> None:
    """Replace the person's choice with the keys they leave shown.

    Only a column standing away from its default is written down. A choice that
    states the defaults back removes the row, because that is what the row said.
    """
    known = _known(mode)
    stated = {
        column.key: (column.key in shown)
        for column in columns
        if (column.key in shown) is column.hidden_by_default
    }
    if not stated:
        reset_columns(user, known)
        return
    ListColumnChoice.objects.update_or_create(
        user=user, mode=known, defaults={"shown": stated}
    )


def reset_columns(user: User, mode: str) -> None:
    """Take the person's choice away. The list reads its defaults again."""
    ListColumnChoice.objects.filter(user=user, mode=_known(mode)).delete()


class ColumnChoice(NamedTuple):
    """What one request shows, and the control that states it."""

    hidden: frozenset[ColumnKey]
    picker: Node


def column_choice(
    request: HttpRequest, mode: str, columns: Sequence[Column]
) -> ColumnChoice:
    """This person's choice for this list, and the picker that restates it.

    A key naming a column that refuses to hide is read out of the set here:
    the store may hold one a rename orphaned, and the list owes its row header
    and its acts whatever the row says.
    """
    pinned = {column.key for column in columns if not column.hideable}
    hidden = hidden_columns(cast(User, request.user), mode, columns) - pinned
    return ColumnChoice(
        hidden,
        ColumnPicker(
            columns,
            hidden,
            post_url=action_url(
                "games:state_list_columns", mode, origin=request.get_full_path()
            ),
            csrf_input=CsrfInput(request),
            mode=mode,
        ),
    )
