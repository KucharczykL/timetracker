"""What kind of work a Game is, and the Game an add-on belongs to.

Request-free: the Game form's save calls it, and so does a writer
with no form. It sets the two columns and leaves the save to the
caller, inside the caller's transaction.
"""

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
    """One rule refused, on the field that stated it."""

    def __init__(self, sentence: str, *, field: AddonField) -> None:
        super().__init__(sentence)
        self.field: AddonField = field
        self.sentence = sentence


def state_addon(
    game: Game, *, kind: GameKind, parent: Game | None, library: UserLibrary
) -> None:
    """Set `game.kind` and `game.parent`, or refuse.

    The Game (when persisted) and the parent are locked in one
    statement ordered by key, thus two edits naming each other
    wait on each other rather than deadlock.
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
    #: Read off the row, not `visible_to`, which hides a removed parent.
    if parent.library_id is not None and parent.library_id != library.pk:
        raise AddonRefused(FOREIGN_PARENT, field="parent")
    #: An unchanged removed parent passes: the add-on stays editable.
    unchanged = stored is not None and stored.parent_id == parent.pk
    if parent.removed_at is not None and not unchanged:
        raise AddonRefused(REMOVED_PARENT, field="parent")
    if parent.kind != GameKind.MAIN:
        raise AddonRefused(PARENT_NOT_MAIN, field="parent")


def _refuse_while_addons_name(game: Game) -> None:
    """A removed add-on counts: restoring it runs no rule."""
    count = Game.objects.filter(parent=game).count()
    if count:
        raise AddonRefused(
            HAS_ADDONS.format(count=count, plural="" if count == 1 else "s"),
            field="kind",
        )
