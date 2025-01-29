import os
from datetime import datetime
from zoneinfo import ZoneInfo

import django
from django.test import TestCase

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "timetracker.settings")
django.setup()
from django.conf import settings

from games.models import Game, Purchase, Session

ZONEINFO = ZoneInfo(settings.TIME_ZONE)


class FormatDurationTest(TestCase):
    def setUp(self) -> None:
        return super().setUp()

    def test_duration_format(self):
        g = Game(name="The Test Game")
        g.save()
        p = Purchase(
            game=g, date_purchased=datetime(2022, 9, 26, 14, 58, tzinfo=ZONEINFO)
        )
        p.save()
        s = Session(
            purchase=p,
            timestamp_start=datetime(2022, 9, 26, 14, 58, tzinfo=ZONEINFO),
            timestamp_end=datetime(2022, 9, 26, 17, 38, tzinfo=ZONEINFO),
        )
        s.save()
        self.assertEqual(
            s.duration_formatted(),
            "02:40",
        )
