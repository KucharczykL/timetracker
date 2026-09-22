"""Read and state which columns a person turned off on a list."""

from collections.abc import Collection

from django.contrib.auth.models import User

from common.components.primitives import ColumnKey
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
