"""Take a record out of the library, and put it back.

Nothing here destroys a row. `games.retention` keeps the guard that
refuses a destroying delete of a referenced row.
"""

from collections.abc import Callable
from typing import Any

from django.db.models import Model
from django.utils.timezone import now

from games.models import (
    Device,
    FilterPreset,
    Game,
    Platform,
    PlayEvent,
    Purchase,
    Session,
)
from games.signals import recalculate_playtime

#: Every model a user can remove. PlayerGame is absent: it is a
#: projection, and only its projector writes it.
REMOVABLE_MODELS: tuple[type[Model], ...] = (
    Game,
    Platform,
    Device,
    Session,
    PlayEvent,
    Purchase,
    FilterPreset,
)


def _recount_purchases(game: Game) -> None:
    """A count of the live games only."""
    for purchase in game.purchases.all():
        purchase.num_purchases = purchase.games.alive().count()
        purchase.updated_at = now()
        purchase.save(update_fields=["num_purchases", "updated_at"])


def _recalculate_the_games_playtime(session: Session) -> None:
    """A stamp fires no session signal."""
    recalculate_playtime(session.game)


#: What a stamp does not do by itself.
_AFTER_STAMP: dict[type[Model], Callable[[Any], None]] = {
    Game: _recount_purchases,
    Session: _recalculate_the_games_playtime,
}


def _stamp(instance: Model, value: Any) -> None:
    model = type(instance)
    if model not in REMOVABLE_MODELS:
        raise TypeError(f"{model.__name__} is not a removable model.")
    #: An update, not a save: Game, Platform, Session and Purchase
    #: each override save() to call clean(), and a stamp must not
    #: revalidate a row a user is taking out. _AFTER_STAMP therefore
    #: does by hand what a post_save receiver would have done.
    model._default_manager.filter(pk=instance.pk).update(removed_at=value)
    instance.removed_at = value  # type: ignore[attr-defined]
    after = _AFTER_STAMP.get(model)
    if after is not None:
        after(instance)


def remove(instance: Model) -> None:
    """Take the row out of the library."""
    _stamp(instance, now())


def restore(instance: Model) -> None:
    """Put the row back."""
    _stamp(instance, None)
