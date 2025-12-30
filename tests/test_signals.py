import os
from datetime import datetime
from zoneinfo import ZoneInfo

import django
from django.test import TestCase

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "timetracker.settings")
django.setup()
from django.conf import settings

from games.models import Game, Session

ZONEINFO = ZoneInfo(settings.TIME_ZONE)


class SignalsTest(TestCase):
    def test_deleting_game_with_sessions_does_not_raise(self):
        # Create a game and attach a session to it
        g = Game(name="Signal Test Game")
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

        # Deleting the game should not raise (signals run during cascade)
        g.delete()

        # After deletion, the Game should be gone and no sessions remain
        self.assertFalse(Game.objects.filter(pk=g.pk).exists())
        self.assertEqual(Session.objects.filter(pk=s.pk).count(), 0)
