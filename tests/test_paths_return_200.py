from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from entries import record_entry
from graphs import default_graph
from historical_playtime_rows import record_row
from purchases import record_purchase

from games.models import Game, ListColumnChoice, Platform, Playthrough
from timetracker.temporal import TemporalValue

ZONEINFO = ZoneInfo("Europe/Prague")


# DEBUG on turns every smoke test below into an id-uniqueness check: the page
# assembly in common/layout.py only runs assert_unique_element_ids under DEBUG,
# so with pytest-django's forced DEBUG=False a page that 500s the moment a
# developer opens it with `make dev` passes CI silently (issue #529). INTERNAL_IPS
# is cleared for the same reason tests/conftest.py's debug_page_rendering fixture
# clears it — debug_toolbar's show_toolbar() reads both live, and its URLs were
# never registered because timetracker.urls saw DEBUG=False at import time.
@override_settings(DEBUG=True, INTERNAL_IPS=[])
class PathWorksTest(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_superuser(
            username="testuser", email="test@example.com", password="testpass"
        )
        self.client.force_login(self.user)
        library = self.user.library
        self.platform = Platform.objects.create(
            library=library, name="Test Platform", icon="steam"
        )
        self.game = Game.objects.create(
            library=library, name="Test Game", platform=self.platform
        )
        copy = record_entry(library, default_graph(self.game, library).release)
        #: Two equal prices: their popovers must not collide.
        for day in ("2022-09-26", "2022-09-27"):
            record_purchase(
                copy,
                amount=Decimal(43),
                currency="CZK",
                purchased=TemporalValue.parse(day),
            )

    def test_index_redirects_to_tracker(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)

    def test_tracker_page_returns_200(self):
        response = self.client.get("/tracker/", follow=True)
        self.assertEqual(response.status_code, 200)

    def test_library_page_returns_200(self):
        response = self.client.get(reverse("games:library"))
        self.assertEqual(response.status_code, 200)

    def test_game_list_returns_200(self):
        response = self.client.get(reverse("games:list_games"), follow=True)
        self.assertEqual(response.status_code, 200)

    def test_library_tab_returns_200(self):
        response = self.client.get(reverse("games:list_library"))
        self.assertEqual(response.status_code, 200)

    def test_game_list_survives_a_wikidata_column_naming_no_entity(self):
        # A mirror key the pattern rejects renders.
        Game.objects.create(
            library=self.user.library, name="Unlinkable", wikidata="n/a"
        )
        ListColumnChoice.objects.create(
            user=self.user, mode="games", shown={"wikidata": True}
        )

        response = self.client.get(reverse("games:list_games"), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "n/a")
        self.assertNotContains(response, "wikidata.org/wiki/n")

    def test_view_game_returns_200(self):
        response = self.client.get(self.game.get_absolute_url())
        self.assertEqual(response.status_code, 200)

    def test_add_historical_playtime_returns_200(self):
        response = self.client.get(
            reverse("games:add_historical_playtime", args=[self.game.pk])
        )
        self.assertEqual(response.status_code, 200)

    def test_edit_historical_playtime_returns_200(self):
        record = record_row(
            [Playthrough.objects.get(player_game__game=self.game)],
            duration=timedelta(hours=100),
            when="2005",
        )
        response = self.client.get(
            reverse("games:edit_historical_playtime", args=[record.pk])
        )
        self.assertEqual(response.status_code, 200)

    def test_view_game_with_historical_playtime_returns_200(self):
        run = Playthrough.objects.get(player_game__game=self.game)
        record_row([run], when="2005")
        record_row([run])
        response = self.client.get(self.game.get_absolute_url())
        self.assertEqual(response.status_code, 200)

    def test_add_game_returns_200(self):
        response = self.client.get(reverse("games:add_game"))
        self.assertEqual(response.status_code, 200)

    def test_stats_returns_200(self):
        response = self.client.get(reverse("games:stats_alltime"))
        self.assertEqual(response.status_code, 200)

    def test_list_sessions_returns_200(self):
        response = self.client.get(reverse("games:list_sessions"))
        self.assertEqual(response.status_code, 200)

    def test_list_playthroughs_returns_200(self):
        response = self.client.get(reverse("games:list_playthroughs"))
        self.assertEqual(response.status_code, 200)

    def test_list_historical_playtime_returns_200(self):
        response = self.client.get(reverse("games:list_historical_playtime"))
        self.assertEqual(response.status_code, 200)

    def test_list_purchases_returns_200(self):
        response = self.client.get(reverse("games:list_purchases"))
        self.assertEqual(response.status_code, 200)

    def test_platform_groups_api_returns_200(self):
        # Distinct platform groups are returned as string-valued options.
        Platform.objects.create(name="Switch", icon="gog", group="Nintendo")
        response = self.client.get("/api/platforms/groups")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        groups = {item["value"] for item in body}
        self.assertIn("Nintendo", groups)

        filtered = self.client.get("/api/platforms/groups?q=nin")
        self.assertEqual(filtered.status_code, 200)
        self.assertEqual({item["value"] for item in filtered.json()}, {"Nintendo"})
