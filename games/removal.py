"""Take a record out; put it back.

Nothing here destroys a row. `games.retention` keeps the guard that
refuses a destroying delete of a referenced row.
"""

from collections.abc import Callable
from typing import Any

from django.db.models import Exists, Model, OuterRef
from django.utils.timezone import now

from games.models import (
    Device,
    Edition,
    FilterPreset,
    Game,
    Platform,
    PlayEvent,
    Purchase,
    Release,
    Session,
)
from games.signals import recalculate_playtime

#: Every model a user can remove.
#: PlayerGame is absent: it is a projection,
#: and only its projector writes it.
REMOVABLE_MODELS: tuple[type[Model], ...] = (
    Game,
    Edition,
    Release,
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


def _mark_the_references_of(instance: Model) -> None:
    """A reference follows the row it names.

    A removal stamps every reference of the row. A restore takes
    back only the keys no live row holds: re-claiming one would
    repeat the theft in the other direction, and raising would
    surface as a traceback, because restore() has no error channel
    until #695 and #795 give it one.
    """
    from games.models import ExternalReference

    column = ExternalReference.TARGET_FIELDS_BY_MODEL[type(instance)]
    held = ExternalReference.objects.filter(**{column: instance.pk})
    stamp = instance.removed_at  # type: ignore[attr-defined]
    if stamp is not None:
        held.filter(removed_at__isnull=True).update(removed_at=stamp)
        return
    free = ~Exists(
        ExternalReference.objects.filter(
            provider=OuterRef("provider"),
            entity_kind=OuterRef("entity_kind"),
            provider_key=OuterRef("provider_key"),
            removed_at__isnull=True,
        )
    )
    held.filter(removed_at__isnull=False).filter(free).update(removed_at=None)


def _mirror_the_wikidata_column(game: Game) -> None:
    """A restore that lost the key must not leave the column naming it."""
    from games.external_references import mirror_game_wikidata

    if game.removed_at is None:
        mirror_game_wikidata(game)


#: What a stamp does not do. Values run in order.
_AFTER_STAMP: dict[type[Model], tuple[Callable[[Any], None], ...]] = {
    Game: (_mark_the_references_of, _mirror_the_wikidata_column, _recount_purchases),
    Edition: (_mark_the_references_of,),
    Release: (_mark_the_references_of,),
    Platform: (_mark_the_references_of,),
    Session: (_recalculate_the_games_playtime,),
}


def _stamp(instance: Model, value: Any) -> None:
    model = type(instance)
    if model not in REMOVABLE_MODELS:
        raise TypeError(f"{model.__name__} is not a removable model.")
    #: An update, not a save.
    #: Game, Platform, Session and Purchase
    #: each override save() to call clean(),
    #: and a stamp must not revalidate
    #: a row a user is taking out.
    #: _AFTER_STAMP does what post_save would.
    model._default_manager.filter(pk=instance.pk).update(removed_at=value)
    instance.removed_at = value  # type: ignore[attr-defined]
    for after in _AFTER_STAMP.get(model, ()):
        after(instance)


def remove(instance: Model) -> None:
    """Take the row out of the library."""
    _stamp(instance, now())


def restore(instance: Model) -> None:
    """Put the row back."""
    _stamp(instance, None)
