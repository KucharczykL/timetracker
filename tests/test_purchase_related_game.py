from datetime import date

from django.core.exceptions import ValidationError
from django.test import TestCase

from games.models import Game, Platform, Purchase


class PurchaseRelatedGameTest(TestCase):
    def setUp(self):
        self.platform = Platform.objects.create(name="PC", icon="pc", group="PC")
        self.base_game = Game.objects.create(name="Base Game", platform=self.platform)
        self.dlc_game = Game.objects.create(name="The DLC", platform=self.platform)

    def test_non_game_purchase_requires_related_game(self):
        purchase = Purchase(
            price=10.0,
            price_currency="USD",
            date_purchased=date(2025, 1, 1),
            type=Purchase.SEASONPASS,
            name="Season Pass",
        )
        with self.assertRaises(ValidationError):
            purchase.save()

    def test_non_game_purchase_saves_with_related_game(self):
        purchase = Purchase(
            price=10.0,
            price_currency="USD",
            date_purchased=date(2025, 1, 1),
            type=Purchase.SEASONPASS,
            name="Season Pass",
            related_game=self.base_game,
        )
        purchase.save()
        purchase.games.add(self.dlc_game)

        self.assertEqual(purchase.related_game, self.base_game)
        # Reverse accessor: the base game lists its add-on purchases.
        self.assertIn(purchase, self.base_game.addon_purchases.all())

    def test_plain_game_purchase_needs_no_related_game(self):
        purchase = Purchase(
            price=50.0,
            price_currency="USD",
            date_purchased=date(2025, 1, 1),
            type=Purchase.GAME,
        )
        purchase.save()  # must not raise
        self.assertIsNone(purchase.related_game)
