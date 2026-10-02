"""An unmigrated model for comparison-group tests."""

from django.db import models
from django.db.models import F
from django.db.models.functions import Coalesce, NullIf
from django.test.utils import isolate_apps

from games.models import Game, Platform


def _declare() -> type[models.Model]:
    """Declared in its own registry, never migrated."""
    with isolate_apps("games"):

        class Bundle(models.Model):
            games = models.ManyToManyField(Game, related_name="+")
            platform = models.ForeignKey(
                Platform, on_delete=models.SET_NULL, null=True, related_name="+"
            )
            related_game = models.ForeignKey(
                Game,
                on_delete=models.SET_NULL,
                null=True,
                related_name="+",
                verbose_name="Base game",
            )
            date_purchased = models.DateField()
            date_refunded = models.DateField(null=True)
            name = models.CharField(max_length=255, blank=True, default="")
            price = models.FloatField(default=0)
            converted_price = models.FloatField(null=True)
            infinite = models.BooleanField(default=False)
            needs_price_update = models.BooleanField(default=True)
            price_currency = models.CharField(max_length=3, blank=True, default="")
            converted_currency = models.CharField(max_length=3, blank=True, default="")
            num_purchases = models.IntegerField(default=0)
            price_per_game = models.GeneratedField(
                expression=Coalesce(F("price"), 0) / NullIf(F("num_purchases"), 0),
                output_field=models.FloatField(),
                db_persist=True,
            )

            class Meta:
                app_label = "games"
                verbose_name = "purchase"

    return Bundle


Bundle = _declare()
