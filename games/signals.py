import logging
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Sum
from django.db.models.signals import (
    m2m_changed,
    post_delete,
    post_save,
    pre_delete,
)
from django.dispatch import receiver
from django.utils.timezone import now

from games.models import (
    Device,
    Game,
    Platform,
    Purchase,
    PurchaseConversionState,
    Release,
    Session,
    SiteSetting,
    UserLibrary,
    UserLibraryPreferences,
    UserPreferences,
)
from games.retention import refuse_to_delete_a_referenced_row
from timetracker.settings_resolver import clear_cache as clear_settings_cache

logger = logging.getLogger("games")


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def provision_user_library(sender, instance, created, raw=False, **kwargs) -> None:
    if raw or not created:
        return
    with transaction.atomic():
        library, _ = UserLibrary.objects.get_or_create(user=instance)
        UserPreferences.objects.get_or_create(user=instance)
        UserLibraryPreferences.objects.get_or_create(library=library)
        from timetracker.settings_resolver import resolve_for_user_with_origin

        display_currency = str(
            resolve_for_user_with_origin(instance, "DEFAULT_DISPLAY_CURRENCY").value
        ).upper()
        PurchaseConversionState.objects.get_or_create(
            library=library,
            defaults={
                "requested_currency": display_currency,
                "published_currency": display_currency,
            },
        )


@receiver([post_save, post_delete], sender=SiteSetting)
@receiver([post_save, post_delete], sender=UserPreferences)
def invalidate_settings_cache(sender, instance, **kwargs):
    # on_commit, not inline: firing inside the atomic block would let a racing
    # thread re-cache the old value, or cache a rolled-back phantom.
    #
    # Known TTL-bounded gap: destroying a Device nulls a referencing
    # default_device via a bulk UPDATE that fires no UserPreferences signal, so a
    # per-user snapshot can serve the dangling id until the TTL lapses.
    transaction.on_commit(clear_settings_cache)


@receiver(m2m_changed, sender=Purchase.games.through)
def validate_purchase_game_ownership(sender, instance, action, model, pk_set, **kwargs):
    if action != "pre_add" or not pk_set:
        return
    if (
        model.objects.filter(pk__in=pk_set)
        .exclude(library_id=instance.library_id)
        .exists()
    ):
        raise ValidationError("Purchase and Game must belong to the same library.")


@receiver(m2m_changed, sender=Purchase.games.through)
def update_num_purchases(sender, instance, action, reverse, **kwargs):
    if not reverse and action.startswith("post_"):
        instance.num_purchases = instance.games.alive().count()
        instance.updated_at = now()
        instance.save(update_fields=["num_purchases", "updated_at"])


@receiver(pre_delete, sender=Game)
@receiver(pre_delete, sender=Platform)
@receiver(pre_delete, sender=Device)
@receiver(pre_delete, sender=Release)
def refuse_to_delete_a_row_an_event_references(sender, instance, **kwargs):
    """Stop a delete that strands a reference.

    Here, not in the views, so every call path is held to it.
    """
    refuse_to_delete_a_referenced_row(instance)


def recalculate_playtime(game: Game) -> None:
    """The sum over the live sessions."""
    total_playtime = game.sessions.alive().aggregate(
        total_playtime=Sum(F("duration_calculated") + F("duration_manual"))
    )["total_playtime"]
    game.playtime = total_playtime if total_playtime else timedelta(0)
    game.save(update_fields=["playtime"])


@receiver([post_save, post_delete], sender=Session)
def update_game_playtime(sender, instance, **kwargs):
    # A fixture carries its own playtime; recomputing it per loaded row costs an
    # aggregate and a write each, which is most of what a container's seed step
    # spends its time on.
    if kwargs.get("raw"):
        return
    # During cascade deletes the related Game may already have been removed.
    # Use the FK id to look up the Game safely and bail out if it no longer exists.
    game_id = getattr(instance, "game_id", None)
    if not game_id:
        return
    game = Game.objects.filter(pk=game_id).first()
    if not game:
        return

    recalculate_playtime(game)
