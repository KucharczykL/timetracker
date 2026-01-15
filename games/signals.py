import logging
from datetime import timedelta

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

from games.models import Game, GameStatusChange, Purchase, Session

logger = logging.getLogger("games")


@receiver(m2m_changed, sender=Purchase.games.through)
def update_num_purchases(sender, instance, action, reverse, **kwargs):
    if not reverse and action.startswith("post_"):
        instance.num_purchases = instance.games.count()
        instance.updated_at = now()
        instance.save(update_fields=["num_purchases", "updated_at"])


@receiver(pre_delete, sender=Game)
def update_purchase_counts_on_game_delete(sender, instance, **kwargs):
    """
    Update num_purchases on related Purchase objects when a Game is deleted.
    m2m_changed is not fired when a related object is deleted.
    """
    for purchase in instance.purchases.all():
        if purchase.num_purchases > 0:
            purchase.num_purchases -= 1
            if purchase.num_purchases == 0:
                purchase.delete()
            else:
                purchase.updated_at = now()
                purchase.save(update_fields=["num_purchases", "updated_at"])


@receiver([post_save, post_delete], sender=Session)
def update_game_playtime(sender, instance, **kwargs):
    # During cascade deletes the related Game may already have been removed.
    # Use the FK id to look up the Game safely and bail out if it no longer exists.
    game_pk = getattr(instance, "game_id", None)
    if not game_pk:
        return
    game = Game.objects.filter(pk=game_pk).first()
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
    try:
        old_instance = sender.objects.get(pk=instance.pk)
        old_status = old_instance.status
        logger.info("[game_status_changed]: Previous status exists.")
    except sender.DoesNotExist:
        # Handle the case where the instance was deleted before the signal was sent
        logger.info("[game_status_changed]: Previous status does not exist.")
        return

    if old_status != instance.status:
        logger.info(
            "[game_status_changed]: Status changed from {} to {}".format(
                old_status, instance.status
            )
        )
        GameStatusChange.objects.create(
            game=instance,
            old_status=old_status,
            new_status=instance.status,
            timestamp=now(),
        )
    else:
        logger.info("[game_status_changed]: Status has not changed")
