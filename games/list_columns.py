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


def hidden_columns(user: User, mode: str) -> frozenset[ColumnKey]:
    """The keys this person turned off on this list. Empty where none."""
    stored = (
        ListColumnChoice.objects.filter(user=user, mode=_known(mode))
        .values_list("hidden", flat=True)
        .first()
    )
    return frozenset(stored or ())


def state_hidden_columns(user: User, mode: str, hidden: Collection[ColumnKey]) -> None:
    """Replace the person's choice. An empty set removes the row."""
    known = _known(mode)
    if not hidden:
        ListColumnChoice.objects.filter(user=user, mode=known).delete()
        return
    ListColumnChoice.objects.update_or_create(
        user=user, mode=known, defaults={"hidden": sorted(hidden)}
    )


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
    hidden = frozenset(hidden_columns(cast(User, request.user), mode) - pinned)
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
