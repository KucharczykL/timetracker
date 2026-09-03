"""Take a record out; put it back.

Nothing here destroys a row. `games.retention` keeps the guard that
refuses a destroying delete of a referenced row.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Any

from django.db import transaction
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


def _recount_purchases(game: Game, previous_mark: datetime | None) -> None:
    """A count of the live games only."""
    for purchase in game.purchases.all():
        purchase.num_purchases = purchase.games.alive().count()
        purchase.updated_at = now()
        purchase.save(update_fields=["num_purchases", "updated_at"])


def _recalculate_the_games_playtime(
    session: Session, previous_mark: datetime | None
) -> None:
    """A stamp fires no session signal."""
    recalculate_playtime(session.game)


def _mark_the_references_of(instance: Model, previous_mark: datetime | None) -> None:
    """A reference follows the row it names.

    A removal stamps every live reference of the row with the row's
    own mark, thus the mark says which act took the reference out.
    A restore reads it back and takes only those: a key the record
    let go of earlier carries the mark of that act instead, and a
    restore that took it back would state two keys of one provider.

    A key another row has claimed meanwhile stays claimed. Taking
    it back would repeat the theft in the other direction, and
    raising would surface as a traceback, because restore() has no
    error channel until #695 and #795 give it one.
    """
    from games.models import ExternalReference

    column = ExternalReference.TARGET_FIELDS_BY_MODEL[type(instance)]
    held = ExternalReference.objects.filter(**{column: instance.pk})
    stamp = instance.removed_at  # type: ignore[attr-defined]
    if stamp is not None:
        held.filter(removed_at__isnull=True).update(removed_at=stamp)
        return
    if previous_mark is None:
        return
    free = ~Exists(
        ExternalReference.objects.filter(
            provider=OuterRef("provider"),
            entity_kind=OuterRef("entity_kind"),
            provider_key=OuterRef("provider_key"),
            removed_at__isnull=True,
        )
    )
    held.filter(removed_at=previous_mark).filter(free).update(removed_at=None)


def _mirror_the_wikidata_column(game: Game, previous_mark: datetime | None) -> None:
    """A restore that lost the key must not leave the column naming it."""
    from games.external_references import mirror_game_wikidata

    if game.removed_at is None:
        mirror_game_wikidata(game)


#: What a stamp does not do. Values run in order, and each reads
#: the mark the row carried before this one.
_AFTER_STAMP: dict[type[Model], tuple[Callable[[Any, datetime | None], None], ...]] = {
    Game: (_mark_the_references_of, _mirror_the_wikidata_column, _recount_purchases),
    Edition: (_mark_the_references_of,),
    Release: (_mark_the_references_of,),
    Platform: (_mark_the_references_of,),
    Session: (_recalculate_the_games_playtime,),
}


def _stamp(instance: Model, value: datetime | None) -> None:
    model = type(instance)
    if model not in REMOVABLE_MODELS:
        raise TypeError(f"{model.__name__} is not a removable model.")
    rows = model._default_manager.filter(pk=instance.pk)
    #: One transaction: the mark and everything _AFTER_STAMP does
    #: about it land together, or a refusal in the middle leaves
    #: the row as it was rather than half put back.
    with transaction.atomic():
        #: Read from the row and not from the instance a caller
        #: holds, because only the row says which act to undo.
        previous_mark = rows.values_list("removed_at", flat=True).first()
        #: An update, not a save.
        #: Game, Platform, Session and Purchase
        #: each override save() to call clean(),
        #: and a stamp must not revalidate
        #: a row a user is taking out.
        #: _AFTER_STAMP does what post_save would.
        rows.update(removed_at=value)
        instance.removed_at = value  # type: ignore[attr-defined]
        for after in _AFTER_STAMP.get(model, ()):
            after(instance, previous_mark)


def remove(instance: Model) -> None:
    """Take the row out of the library."""
    _stamp(instance, now())


def restore(instance: Model) -> None:
    """Put the row back."""
    _stamp(instance, None)
