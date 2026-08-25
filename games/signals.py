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
    pre_save,
)
from django.dispatch import receiver
from django.utils.timezone import now

from games.models import (
    Device,
    Game,
    GameStatusChange,
    Platform,
    Purchase,
    PurchaseConversionState,
    Session,
    SiteSetting,
    UserLibrary,
    UserLibraryPreferences,
    UserPreferences,
)
from games.retention import (
    detach_game_from_purchases,
    refuse_to_delete_a_referenced_row,
)
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
    # Known TTL-bounded gap: deleting a Device nulls a referencing
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
        instance.num_purchases = instance.games.count()
        instance.updated_at = now()
        instance.save(update_fields=["num_purchases", "updated_at"])


@receiver(pre_delete, sender=Game)
def update_purchase_counts_on_game_delete(sender, instance, **kwargs):
    """Keep purchase counts right when a Game is deleted.

    The work lives in ``games.retention`` because retiring a referenced Game
    has to do the same thing without ever deleting the row, so this receiver
    never fires for it.
    """
    detach_game_from_purchases(instance)


@receiver(pre_delete, sender=Game)
@receiver(pre_delete, sender=Platform)
@receiver(pre_delete, sender=Device)
def refuse_to_delete_a_row_an_event_references(sender, instance, **kwargs):
    """Stop a hard delete that would strand a recorded reference.

    Connected here rather than left to the three delete views, so a shell, a
    script or a management command is held to the same promise. A whole-library
    purge is the documented exemption; see ``retention.purging_library``.
    """
    refuse_to_delete_a_referenced_row(instance)


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

    total_playtime = game.sessions.aggregate(
        total_playtime=Sum(F("duration_calculated") + F("duration_manual"))
    )["total_playtime"]
    game.playtime = total_playtime if total_playtime else timedelta(0)
    game.save(update_fields=["playtime"])


@receiver(pre_save, sender=Game)
def game_status_changed(sender, instance, **kwargs):
    """
    Signal handler to create a GameStatusChange record whenever a Game's status is updated.
    """
    # A fixture ships its own GameStatusChange rows; loading one is not a status
    # transition, and the lookup below would query once per row.
    if kwargs.get("raw"):
        return
    try:
        old_instance = sender.objects.get(pk=instance.pk)
        old_status = old_instance.status
        logger.debug("[game_status_changed]: Previous status exists.")
    except sender.DoesNotExist:
        # Handle the case where the instance was deleted before the signal was sent
        logger.debug("[game_status_changed]: Previous status does not exist.")
        return

    if old_status != instance.status:
        logger.debug(
            f"[game_status_changed]: Status changed from {old_status} to {instance.status}"
        )
        GameStatusChange.objects.create(
            game=instance,
            old_status=old_status,
            new_status=instance.status,
            timestamp=now(),
        )
    else:
        logger.debug("[game_status_changed]: Status has not changed")
