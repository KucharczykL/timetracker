from datetime import date

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse

from games.models import Game, Platform, Purchase, UserPreferences
from timetracker import settings_resolver
from timetracker.settings_commands import change_user_setting


class AddPurchaseDefaultsTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("u", "u@e.com", "pw")
        self.client.force_login(self.user)
        self.library = self.user.library
        self.platform = Platform.objects.create(name="PC", icon="pc", group="PC")
        self.game_a = Game.objects.create(
            library=self.library,
            name="Game A",
            platform=self.platform,
        )
        self.game_b = Game.objects.create(
            library=self.library,
            name="Game B",
            platform=self.platform,
        )

    def _base_data(self, **overrides):
        data = {
            "games": [self.game_a.id],
            "platform": "",
            "date_purchased": "2025-01-01",
            "price_currency": "",
            "ownership_type": Purchase.DIGITAL,
            "type": Purchase.GAME,
            "name": "",
        }
        data.update(overrides)
        return data

    @override_settings(DEFAULT_PURCHASE_CURRENCY="CZK")
    def test_empty_platform_and_currency_use_entry_defaults(self):
        data = self._base_data(pricing_mode="combined", price="30")

        response = self.client.post(reverse("games:add_purchase"), data)

        self.assertEqual(response.status_code, 302)
        purchase = Purchase.objects.get()
        self.assertIsNone(purchase.platform)
        self.assertEqual(purchase.price_currency, "CZK")

    @override_settings(DEFAULT_PURCHASE_CURRENCY="CZK")
    def test_per_game_path_uses_explicit_form_currency(self):
        data = self._base_data(
            games=[self.game_a.id, self.game_b.id],
            pricing_mode="per_game",
            **{
                f"price_for_game_{self.game_a.id}": "10",
                f"price_for_game_{self.game_b.id}": "20",
            },
        )

        response = self.client.post(reverse("games:add_purchase"), data)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Purchase.objects.count(), 2)
        for purchase in Purchase.objects.all():
            self.assertIsNone(purchase.platform)
            self.assertEqual(purchase.price_currency, "CZK")

    def test_user_purchase_currency_preselects_and_is_saved_explicitly(self):
        preferences = UserPreferences.objects.get(user=self.user)
        preferences.default_purchase_currency = "EUR"
        preferences.save(update_fields=["default_purchase_currency", "updated_at"])
        settings_resolver.clear_cache()

        response = self.client.post(
            reverse("games:add_purchase"),
            self._base_data(pricing_mode="combined", price="5"),
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Purchase.objects.get().price_currency, "EUR")

    def test_changing_purchase_default_never_rewrites_stored_purchase(self):
        purchase = Purchase.objects.create(
            library=self.library,
            date_purchased=date(2025, 1, 1),
            price=10,
            price_currency="USD",
        )

        change_user_setting(self.user, "DEFAULT_PURCHASE_CURRENCY", "EUR")
        purchase.refresh_from_db()

        self.assertEqual(purchase.price_currency, "USD")

    def test_purchase_save_rejects_missing_explicit_currency(self):
        purchase = Purchase(
            library=self.library,
            date_purchased=date(2025, 1, 1),
            price=10,
            price_currency="",
        )

        with self.assertRaises(ValidationError):
            purchase.save()
