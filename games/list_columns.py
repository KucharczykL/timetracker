"""Read and write the column choice of a person."""

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
    """The statement of this person, by key."""
    stored = (
        ListColumnChoice.objects.filter(user=user, mode=_known(mode))
        .values_list("shown", flat=True)
        .first()
    )
    return stored or {}


def hidden_columns(
    user: User, mode: str, columns: Sequence[Column]
) -> frozenset[ColumnKey]:
    """The keys this person does not show.

    A column that the map does not name reads its own default. A column added
    later thus starts where it declares, not where an older row left it.
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
    """Replace the choice with the keys that stay shown.

    Only a column that differs from its default is written. A choice equal to
    the defaults removes the row.
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
    """Remove the choice. The defaults apply again."""
    ListColumnChoice.objects.filter(user=user, mode=_known(mode)).delete()


class ColumnChoice(NamedTuple):
    """What one request shows, and its control."""

    hidden: frozenset[ColumnKey]
    picker: Node


def column_choice(
    request: HttpRequest, mode: str, columns: Sequence[Column]
) -> ColumnChoice:
    """The choice of this person, and its picker.

    A key for a column that refuses to hide is removed here. The store can hold
    one from an earlier name, and the list keeps its row header and its
    operations.
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
