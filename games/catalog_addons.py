"""A Game's kind and parent, or refusal."""

from typing import Final, Literal

from django.core.exceptions import ValidationError
from django.db import transaction

from games.events.dispatch import RowNotHeld, RowUnreadable
from games.models import Game, GameKind, UserLibrary

type AddonField = Literal["kind", "parent"]

PARENT_ON_MAIN: Final = (
    "A main game has no parent. Choose an add-on kind or clear the parent."
)
ADDON_WITHOUT_PARENT: Final = "An add-on names the game it belongs to."
OWN_PARENT: Final = "A game cannot be its own parent."
FOREIGN_PARENT: Final = "That game is not in your library."
REMOVED_PARENT: Final = "That game is removed. Put it back before you name it."
PARENT_NOT_MAIN: Final = "An add-on belongs to a main game."
#: Names a foreign parent without its name.
FOREIGN_PARENT_LABEL: Final = "A game in another library"
#: Formatted with `count` and `plural`.
HAS_ADDONS: Final = (
    "{count} add-on{plural} name this game as the parent. "
    "Give them another parent before you make this game an add-on."
)


def foreign_to(game: Game, library: UserLibrary) -> bool:
    """Another library's private game."""
    return game.library_id is not None and game.library_id != library.pk


class AddonRefused(ValidationError):
    """One refusal, on its own field."""

    def __init__(self, sentence: str, *, field: AddonField) -> None:
        super().__init__(sentence)
        self.field: AddonField = field


def state_addon(
    game: Game, *, kind: GameKind, parent: Game | None, library: UserLibrary
) -> None:
    """Set kind and parent; the caller saves."""
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("state_addon runs inside the caller's transaction.")
    persisted = not game._state.adding
    keys = {game.pk} if persisted else set()
    if parent is not None:
        keys.add(parent.pk)
    locked = {
        row.pk: row
        for row in Game.objects.select_for_update().filter(pk__in=keys).order_by("pk")
    }
    stored = locked.get(game.pk) if persisted else None
    #: The edited Game, or its parent.
    missing = keys - locked.keys()
    if missing:
        raise RowNotHeld(
            f"Games {missing} are gone before library {library.pk}'s lock."
        )

    if kind == GameKind.MAIN:
        if parent is not None:
            raise AddonRefused(PARENT_ON_MAIN, field="parent")
    else:
        if parent is None:
            raise AddonRefused(ADDON_WITHOUT_PARENT, field="parent")
        _refuse_the_parent(game, locked.get(parent.pk), stored, library)
        if stored is not None and stored.kind == GameKind.MAIN:
            _refuse_while_addons_name(game)

    game.kind = kind
    game.parent = None if parent is None else locked[parent.pk]


def _refuse_the_parent(
    game: Game, parent: Game | None, stored: Game | None, library: UserLibrary
) -> None:
    if parent is None:
        raise RowUnreadable(f"Game {game.pk} names a parent no row holds.")
    if parent.pk == game.pk:
        raise AddonRefused(OWN_PARENT, field="parent")
    #: Not `visible_to`: it hides removed parents.
    #: The removed-parent check must see them.
    if foreign_to(parent, library):
        raise AddonRefused(FOREIGN_PARENT, field="parent")
    #: Keeps an add-on editable.
    unchanged = stored is not None and stored.parent_id == parent.pk
    if parent.removed_at is not None and not unchanged:
        raise AddonRefused(REMOVED_PARENT, field="parent")
    if parent.kind != GameKind.MAIN:
        raise AddonRefused(PARENT_NOT_MAIN, field="parent")


def _refuse_while_addons_name(game: Game) -> None:
    """Removed add-ons count too.

    Restoring one runs no rule, so a live-only
    count would let an add-on stand under one.
    """
    count = Game.objects.filter(parent=game).count()
    if count:
        raise AddonRefused(
            HAS_ADDONS.format(count=count, plural="" if count == 1 else "s"),
            field="kind",
        )
