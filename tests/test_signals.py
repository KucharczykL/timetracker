import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import serializers
from django.core.management import call_command
from django.test import TestCase

from games.models import Game, Session, UserLibrary

ZONEINFO = ZoneInfo(settings.TIME_ZONE)


class SignalsTest(TestCase):
    @pytest.mark.untracked_games
    def test_deleting_game_with_sessions_does_not_raise(self):
        library = get_user_model().objects.create_user(username="signals").library
        # Create a game and attach a session to it
        g = Game(library=library, name="Signal Test Game")
        g.save()

        s = Session(
            game=g,
            timestamp_start=datetime(2022, 9, 26, 14, 58, tzinfo=ZONEINFO),
            timestamp_end=datetime(2022, 9, 26, 17, 38, tzinfo=ZONEINFO),
        )
        s.save()

        # Sanity checks before delete
        self.assertTrue(Game.objects.filter(pk=g.pk).exists())
        self.assertEqual(g.sessions.count(), 1)

        # Destroying the game should not raise (signals run during cascade)
        g.delete()

        # After deletion, the Game should be gone and no sessions remain
        self.assertFalse(Game.objects.filter(pk=g.pk).exists())
        self.assertEqual(Session.objects.filter(pk=s.pk).count(), 0)


class RawFixtureLoadTest(TestCase):
    """A fixture is authoritative: loading one must not trigger the recomputes.

    Django flags fixture saves with ``raw=True`` for exactly this. Without the
    guards, seeding a container replays the whole signal stack per row — an
    extra query and write each — which dominates a cold container's startup.
    """

    def setUp(self):
        self.fixture_dir = self.enterContext(tempfile.TemporaryDirectory())

        self.library = (
            get_user_model().objects.create_user(username="raw-fixture").library
        )

    def _write_fixture(self, objects) -> str:
        path = Path(self.fixture_dir) / "fixture.json"
        path.write_text(serializers.serialize("json", objects))
        return str(path)

    def test_user_fixture_does_not_provision_a_library(self):
        user = get_user_model().objects.create_user(username="fixture-user")
        user_id = user.pk
        fixture = self._write_fixture([user])

        user.delete()
        call_command("loaddata", fixture, verbosity=0)

        restored_user = get_user_model().objects.get(pk=user_id)
        self.assertFalse(UserLibrary.objects.filter(user=restored_user).exists())
