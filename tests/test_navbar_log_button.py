"""The navbar log split button (#419): the `recent_session_resumes` query and
the rendered navbar (present + auth-gated), plus confirmation that list pages no
longer carry the deleted `<caption>` action strip."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth.models import AnonymousUser, User
from django.test import RequestFactory, TestCase
from django.urls import reverse

from common.layout import recent_session_resumes
from games.models import Game, Platform, Session

ZONEINFO = ZoneInfo(settings.TIME_ZONE)
BASE = datetime(2025, 1, 1, 12, 0, tzinfo=ZONEINFO)


class RecentSessionResumesTest(TestCase):
    def setUp(self) -> None:
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username="u", password="p")
        self.platform = Platform.objects.create(name="PC", icon="pc")

    def _request(self, *, authenticated: bool):
        request = self.factory.get("/")
        request.user = self.user if authenticated else AnonymousUser()
        return request

    def _game(self, name: str) -> Game:
        return Game.objects.create(name=name, platform=self.platform)

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
        names = [s.game.name for s in resumes if s.game is not None]
        self.assertEqual(names, ["G5", "G4", "G3", "G2", "G1"])

    def test_excludes_null_game_sessions(self) -> None:
        Session.objects.create(game=None, timestamp_start=BASE + timedelta(days=2))
        game = self._game("A")
        self._session(game, BASE)
        resumes = recent_session_resumes(self._request(authenticated=True))
        names = [s.game.name for s in resumes if s.game is not None]
        self.assertEqual(names, ["A"])


class NavbarLogButtonRenderTest(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_superuser(
            username="testuser", email="t@e.com", password="pw"
        )
        self.platform = Platform.objects.create(name="PC", icon="pc")
        self.game = Game.objects.create(name="Zzq Unique Title", platform=self.platform)
        Session.objects.create(game=self.game, timestamp_start=BASE)

    def test_authenticated_navbar_has_log_button_and_recent_game(self) -> None:
        self.client.force_login(self.user)
        html = self.client.get(
            reverse("games:list_games"), follow=True
        ).content.decode()
        # Two breakpoint instances: mobile (beside the hamburger) + desktop
        # (inside the menu row, between playtime and Home).
        self.assertIn("navbar-log-mobile", html)
        self.assertIn("navbar-log-desktop", html)
        self.assertIn("Log game", html)
        self.assertIn("Zzq Unique Title", html)

    def test_list_pages_have_no_caption_strip(self) -> None:
        self.client.force_login(self.user)
        for url_name in (
            "games:list_games",
            "games:list_sessions",
            "games:list_purchases",
        ):
            html = self.client.get(reverse(url_name), follow=True).content.decode()
            self.assertNotIn("<caption", html, f"caption still present on {url_name}")

    def test_login_page_omits_log_button_and_recent_game_name(self) -> None:
        self.client.logout()
        html = self.client.get(reverse("login")).content.decode()
        self.assertNotIn("navbar-log", html)
        self.assertNotIn("Zzq Unique Title", html)
