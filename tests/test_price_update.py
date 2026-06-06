from datetime import date

from django.test import TestCase

from games.models import Game, Platform, Purchase
from games.tasks import convert_prices


class PurchaseNeedsPriceUpdateTest(TestCase):
    def setUp(self):
        self.platform = Platform.objects.create(name="PC", icon="pc", group="PC")
        self.game = Game.objects.create(name="Test Game", platform=self.platform)

    def test_new_purchase_has_needs_price_update_true(self):
        purchase = Purchase.objects.create(
            price=50.0,
            price_currency="USD",
            date_purchased=date(2025, 1, 1),
        )
        purchase.games.add(self.game)
        self.assertTrue(purchase.needs_price_update)

    def test_convert_prices_sets_flag_to_false(self):
        purchase = Purchase.objects.create(
            price=50.0,
            price_currency="USD",
            date_purchased=date(2025, 1, 1),
        )
        purchase.games.add(self.game)
        self.assertTrue(purchase.needs_price_update)

        convert_prices()

        purchase.refresh_from_db()
        self.assertFalse(purchase.needs_price_update)

    def test_price_change_sets_needs_price_update(self):
        purchase = Purchase.objects.create(
            price=50.0,
            price_currency="USD",
            date_purchased=date(2025, 1, 1),
        )
        purchase.games.add(self.game)
        purchase.converted_price = 1000
        purchase.converted_currency = "CZK"
        purchase.needs_price_update = False
        purchase.save()

        purchase.price = 60.0
        purchase.save()
        purchase.refresh_from_db()
        self.assertTrue(purchase.needs_price_update)

    def test_currency_change_sets_needs_price_update(self):
        purchase = Purchase.objects.create(
            price=50.0,
            price_currency="USD",
            date_purchased=date(2025, 1, 1),
        )
        purchase.games.add(self.game)
        purchase.converted_price = 1000
        purchase.converted_currency = "CZK"
        purchase.needs_price_update = False
        purchase.save()

        purchase.price_currency = "EUR"
        purchase.save()
        purchase.refresh_from_db()
        self.assertTrue(purchase.needs_price_update)

    def test_name_change_does_not_set_needs_price_update(self):
        purchase = Purchase.objects.create(
            price=50.0,
            price_currency="USD",
            date_purchased=date(2025, 1, 1),
        )
        purchase.games.add(self.game)
        purchase.converted_price = 1000
        purchase.converted_currency = "CZK"
        purchase.needs_price_update = False
        purchase.save()

        purchase.name = "New Name"
        purchase.save()
        purchase.refresh_from_db()
        self.assertFalse(purchase.needs_price_update)

    def test_convert_prices_skips_already_converted(self):
        purchase = Purchase.objects.create(
            price=50.0,
            price_currency="USD",
            date_purchased=date(2025, 1, 1),
        )
        purchase.games.add(self.game)
        purchase.converted_price = 1000
        purchase.converted_currency = "CZK"
        purchase.needs_price_update = False
        purchase.save()

        convert_prices()
        purchase.refresh_from_db()
        self.assertFalse(purchase.needs_price_update)
