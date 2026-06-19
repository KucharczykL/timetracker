from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from games.models import Game, Platform, Purchase


class AddPurchasePricingTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("u", "u@e.com", "pw")
        self.client.force_login(self.user)
        self.platform = Platform.objects.create(name="PC", icon="pc", group="PC")
        self.game_a = Game.objects.create(name="Game A", platform=self.platform)
        self.game_b = Game.objects.create(name="Game B", platform=self.platform)

    def _base_data(self, **overrides):
        data = {
            "games": [self.game_a.id, self.game_b.id],
            "platform": self.platform.id,
            "date_purchased": "2025-01-01",
            "price_currency": "USD",
            "ownership_type": Purchase.DIGITAL,
            "type": Purchase.GAME,
            "name": "",
        }
        data.update(overrides)
        return data

    def test_combined_creates_single_bundle(self):
        data = self._base_data(pricing_mode="combined", price="30")
        response = self.client.post(reverse("games:add_purchase"), data)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Purchase.objects.count(), 1)
        bundle = Purchase.objects.get()
        self.assertEqual(bundle.num_purchases, 2)
        self.assertEqual(bundle.price, 30)

    def test_per_game_creates_separate_single_game_purchases(self):
        data = self._base_data(
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
            self.assertEqual(purchase.num_purchases, 1)
        self.assertEqual(sorted(p.price for p in Purchase.objects.all()), [10.0, 20.0])
        linked_games = [
            list(p.games.values_list("id", flat=True)) for p in Purchase.objects.all()
        ]
        self.assertTrue(all(len(games) == 1 for games in linked_games))
        self.assertEqual(
            {games[0] for games in linked_games},
            {self.game_a.id, self.game_b.id},
        )


class SplitPurchaseTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("u", "u@e.com", "pw")
        self.client.force_login(self.user)
        self.platform = Platform.objects.create(name="PC", icon="pc", group="PC")
        self.game_a = Game.objects.create(name="Game A", platform=self.platform)
        self.game_b = Game.objects.create(name="Game B", platform=self.platform)

    def _bundle(self, games, price=30.0):
        bundle = Purchase.objects.create(
            price=price,
            price_currency="USD",
            date_purchased=date(2025, 1, 1),
            platform=self.platform,
            ownership_type=Purchase.DIGITAL,
            type=Purchase.GAME,
        )
        bundle.games.set(games)
        return bundle

    def test_split_creates_per_game_purchases_and_deletes_original(self):
        bundle = self._bundle([self.game_a, self.game_b], price=30.0)

        response = self.client.post(reverse("games:split_purchase", args=[bundle.id]))

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response["HX-Redirect"], reverse("games:list_purchases"))
        self.assertFalse(Purchase.objects.filter(id=bundle.id).exists())
        self.assertEqual(Purchase.objects.count(), 2)
        for purchase in Purchase.objects.all():
            self.assertEqual(purchase.num_purchases, 1)
            self.assertEqual(purchase.price, 15.0)  # 30 / 2, split evenly
            self.assertTrue(purchase.needs_price_update)

    def test_split_is_noop_for_single_game_purchase(self):
        single = self._bundle([self.game_a], price=10.0)

        response = self.client.post(reverse("games:split_purchase", args=[single.id]))

        self.assertEqual(response.status_code, 204)
        self.assertTrue(Purchase.objects.filter(id=single.id).exists())
        self.assertEqual(Purchase.objects.count(), 1)
