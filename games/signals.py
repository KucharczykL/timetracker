from django.db.models.signals import m2m_changed, pre_save
from django.dispatch import receiver
from django.utils.timezone import now

from games.models import Game, GameStatusChange, Purchase


@receiver(m2m_changed, sender=Purchase.games.through)
def update_num_purchases(sender, instance, **kwargs):
    instance.num_purchases = instance.games.count()
    instance.updated_at = now()
    instance.save(update_fields=["num_purchases"])


@receiver(pre_save, sender=Game)
def game_status_changed(sender, instance, **kwargs):
    """
    Signal handler to create a GameStatusChange record whenever a Game's status is updated.
    """
    try:
        old_instance = sender.objects.get(pk=instance.pk)
        old_status = old_instance.status
        print("Got old instance")
    except sender.DoesNotExist:
        # Handle the case where the instance was deleted before the signal was sent
        print("Instance does not exist")
        return

    if old_status != instance.status:
        print("Status changed")
        GameStatusChange.objects.create(
            game=instance,
            old_status=old_status,
            new_status=instance.status,
            timestamp=instance.updated_at,
        )
    else:
        print("Status not changed")
        print(f"{old_instance.status}")
        print(f"{instance.status}")
