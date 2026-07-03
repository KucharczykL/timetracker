from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from games.models import Game, Platform, Purchase


class AddPurchaseDefaultsTest(TestCase):
    """Adding a purchase without a platform keeps it NULL (issue #290 removed
    the "Unspecified" sentinel); a missing currency falls back to
    DEFAULT_CURRENCY (issue #88)."""

    def setUp(self):
        self.user = User.objects.create_superuser("u", "u@e.com", "pw")
        self.client.force_login(self.user)
        self.platform = Platform.objects.create(name="PC", icon="pc", group="PC")
        self.game_a = Game.objects.create(name="Game A", platform=self.platform)
        self.game_b = Game.objects.create(name="Game B", platform=self.platform)

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

    @override_settings(DEFAULT_CURRENCY="CZK")
    def test_empty_platform_and_currency_use_defaults(self):
        data = self._base_data(pricing_mode="combined", price="30")
        response = self.client.post(reverse("games:add_purchase"), data)

        self.assertEqual(response.status_code, 302)
        purchase = Purchase.objects.get()
        self.assertIsNone(purchase.platform)
        self.assertEqual(purchase.price_currency, "CZK")

    @override_settings(DEFAULT_CURRENCY="CZK")
    def test_per_game_path_uses_defaults(self):
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

    @override_settings(DEFAULT_CURRENCY="EUR")
    def test_currency_default_follows_setting(self):
        data = self._base_data(pricing_mode="combined", price="5")
        self.client.post(reverse("games:add_purchase"), data)

        self.assertEqual(Purchase.objects.get().price_currency, "EUR")
