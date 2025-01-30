from django.db.models.signals import m2m_changed
from django.dispatch import receiver
from django.utils.timezone import now

from games.models import Purchase


@receiver(m2m_changed, sender=Purchase.games.through)
def update_num_purchases(sender, instance, **kwargs):
    instance.num_purchases = instance.games.count()
    instance.updated_at = now()
    instance.save(update_fields=["num_purchases"])
