"""The navbar log split button (#419): the `recent_session_resumes` query and
the rendered navbar (present + auth-gated), plus confirmation that the deleted
`<caption>` action strip stays deleted — a list page's only `<caption>` is the
screen-reader name its table's scroll region points at."""

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth.models import AnonymousUser, User
from django.db import connection
from django.test import RequestFactory, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from common.layout import recent_session_resumes
from games.models import Game, Platform, Session

ZONEINFO = ZoneInfo(settings.TIME_ZONE)
BASE = datetime(2025, 1, 1, 12, 0, tzinfo=ZONEINFO)


class RecentSessionResumesTest(TestCase):
    def setUp(self) -> None:
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username="u", password="p")
        self.platform = Platform.objects.create(
            library=self.user.library, name="PC", icon="pc"
        )

    def _request(self, *, authenticated: bool):
        request = self.factory.get("/")
        request.user = self.user if authenticated else AnonymousUser()
        return request

    def _game(self, name: str) -> Game:
        return Game.objects.create(
            library=self.user.library, name=name, platform=self.platform
        )

    def _session(self, game, when) -> Session:
        return Session.objects.create(game=game, timestamp_start=when)

    def test_anonymous_gets_empty_list(self) -> None:
        self._session(self._game("A"), BASE)
        self.assertEqual(recent_session_resumes(self._request(authenticated=False)), [])

    def test_deduplicated_by_game_keeping_latest_session(self) -> None:
        game = self._game("A")
        older = self._session(game, BASE)
        newer = self._session(game, BASE + timedelta(days=1))
        resumes = recent_session_resumes(self._request(authenticated=True))
        self.assertEqual([s.pk for s in resumes], [newer.pk])
        self.assertNotIn(older.pk, [s.pk for s in resumes])

    def test_ordered_by_latest_and_capped_at_limit(self) -> None:
        # Six games, each with one session, ascending in time.
        for index in range(6):
            self._session(self._game(f"G{index}"), BASE + timedelta(hours=index))
        resumes = recent_session_resumes(self._request(authenticated=True))
        self.assertEqual(len(resumes), 5)
        # Newest first: G5, G4, G3, G2, G1 (G0 falls off the limit).
        names = [s.game.name for s in resumes]
        self.assertEqual(names, ["G5", "G4", "G3", "G2", "G1"])

    def test_query_has_no_obsolete_nullable_game_guard(self) -> None:
        self._session(self._game("Required game"), BASE)

        with CaptureQueriesContext(connection) as queries:
            recent_session_resumes(self._request(authenticated=True))

        session_query = next(
            query["sql"] for query in queries if "games_session" in query["sql"]
        )
        self.assertNotIn('"games_session"."game_id" IS NOT NULL', session_query)


class NavbarLogButtonRenderTest(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_superuser(
            username="testuser", email="t@e.com", password="pw"
        )
        self.platform = Platform.objects.create(
            library=self.user.library, name="PC", icon="pc"
        )
        self.game = Game.objects.create(
            library=self.user.library, name="Zzq Unique Title", platform=self.platform
        )
        Session.objects.create(game=self.game, timestamp_start=BASE)

    def test_authenticated_navbar_has_log_button_and_recent_game(self) -> None:
        self.client.force_login(self.user)
        html = self.client.get(
            reverse("games:list_games"), follow=True
        ).content.decode()
        # The single direct control remains visible at every breakpoint.
        self.assertIn('id="navbar-log"', html)
        self.assertIn("Log game", html)
        self.assertIn("Zzq Unique Title", html)

    def test_authenticated_navbar_exposes_library_and_account_without_menu_or_hamburger(
        self,
    ) -> None:
        self.client.force_login(self.user)
        html = self.client.get(reverse("games:list_games")).content.decode()

        self.assertIn('href="/tracker/library"', html)
        self.assertIn('class="flex items-center gap-4 sm:gap-6"', html)
        self.assertIn("Open account menu for testuser", html)
        self.assertNotIn(">Home<", html)
        self.assertNotIn(">Menu<", html)
        self.assertNotIn("Open main menu", html)

    def test_list_page_captions_are_names_not_action_strips(self) -> None:
        """The deleted strip was a visible `<caption>` full of controls. A
        `<caption>` is back, but only as the scroll region's accessible name:
        screen-reader-only, and holding nothing clickable."""
        self.client.force_login(self.user)
        for url_name in (
            "games:list_games",
            "games:list_sessions",
            "games:list_purchases",
        ):
            html = self.client.get(reverse(url_name), follow=True).content.decode()
            captions = re.findall(r"<caption\b[^>]*>(.*?)</caption>", html, re.DOTALL)
            self.assertEqual(len(captions), 1, f"one caption expected on {url_name}")
            for tag in re.findall(r"<caption\b[^>]*>", html):
                self.assertIn("sr-only", tag, f"visible caption on {url_name}")
            for body in captions:
                for control in ("<a", "<button", "<form", "<input"):
                    self.assertNotIn(
                        control, body, f"caption holds {control} on {url_name}"
                    )

    def test_login_page_omits_log_button_and_recent_game_name(self) -> None:
        self.client.logout()
        html = self.client.get(reverse("login")).content.decode()
        self.assertNotIn("navbar-log", html)
        self.assertNotIn("Zzq Unique Title", html)
