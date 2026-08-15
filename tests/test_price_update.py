from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase

from games.models import Game, Platform, Purchase, PurchaseConversionState
from games.tasks import convert_library_prices


class PurchaseNeedsPriceUpdateTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="price-update")
        self.platform = Platform.objects.create(name="PC", icon="pc", group="PC")
        self.game = Game.objects.create(
            library=self.user.library, name="Test Game", platform=self.platform
        )

    def run_latest_conversion(self):
        state = PurchaseConversionState.objects.get(library=self.user.library)
        convert_library_prices(str(self.user.library.pk), state.requested_version)

    def test_new_purchase_has_needs_price_update_true(self):
        purchase = Purchase.objects.create(
            price=50.0,
            price_currency="USD",
            library=self.user.library,
            date_purchased=date(2025, 1, 1),
        )
        purchase.games.add(self.game)
        self.assertTrue(purchase.needs_price_update)

    def test_convert_prices_sets_flag_to_false(self):
        purchase = Purchase.objects.create(
            price=50.0,
            price_currency="CZK",
            library=self.user.library,
            date_purchased=date(2025, 1, 1),
        )
        purchase.games.add(self.game)
        self.assertTrue(purchase.needs_price_update)

        self.run_latest_conversion()

        purchase.refresh_from_db()
        self.assertFalse(purchase.needs_price_update)

    def test_price_change_sets_needs_price_update(self):
        purchase = Purchase.objects.create(
            price=50.0,
            price_currency="USD",
            date_purchased=date(2025, 1, 1),
            library=self.user.library,
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
            library=self.user.library,
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
            library=self.user.library,
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
            price_currency="CZK",
            date_purchased=date(2025, 1, 1),
            library=self.user.library,
        )
        purchase.games.add(self.game)
        purchase.converted_price = 1000
        purchase.converted_currency = "CZK"
        purchase.needs_price_update = False
        purchase.save()

        self.run_latest_conversion()
        purchase.refresh_from_db()
        self.assertFalse(purchase.needs_price_update)
