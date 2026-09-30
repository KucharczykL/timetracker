"""A Game's kind and parent, stated or refused."""

from typing import Final, Literal

from django.core.exceptions import ValidationError
from django.db import transaction

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
#: Formatted with `count` and `plural`.
HAS_ADDONS: Final = (
    "{count} add-on{plural} name this game as the parent. "
    "Give them another parent before you make this game an add-on."
)


class AddonRefused(ValidationError):
    """One refusal, on its own field."""

    def __init__(self, sentence: str, *, field: AddonField) -> None:
        super().__init__(sentence)
        self.field: AddonField = field
        self.sentence = sentence


def state_addon(
    game: Game, *, kind: GameKind, parent: Game | None, library: UserLibrary
) -> None:
    """Set kind and parent; the caller saves.

    Locks both rows in key order: two edits
    naming each other wait, never deadlock.
    """
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
        raise AddonRefused(FOREIGN_PARENT, field="parent")
    if parent.pk == game.pk:
        raise AddonRefused(OWN_PARENT, field="parent")
    #: Not `visible_to`: it hides removed parents.
    #: Rule 5 must see them, to pass an unchanged one.
    if parent.library_id is not None and parent.library_id != library.pk:
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
