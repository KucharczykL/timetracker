from datetime import datetime
from zoneinfo import ZoneInfo

from django.conf import settings
from django.test import TestCase

from games.models import Game, Purchase, Session
from games.formatting import session_time_range
from common.date_time_presentation import (
    DatePartSpec,
    DateTimeFormatProfile,
    DateTimePresentation,
)

ZONEINFO = ZoneInfo(settings.TIME_ZONE)


class FormatDurationTest(TestCase):
    def setUp(self) -> None:
        return super().setUp()

    def test_duration_format(self):
        g = Game(name="The Test Game")
        g.save()
        p = Purchase(date_purchased=datetime(2022, 9, 26, 14, 58, tzinfo=ZONEINFO))
        p.save()
        p.games.add(g)
        p.save()
        s = Session(
            game=g,
            timestamp_start=datetime(2022, 9, 26, 14, 58, tzinfo=ZONEINFO),
            timestamp_end=datetime(2022, 9, 26, 17, 38, tzinfo=ZONEINFO),
        )
        s.save()
        self.assertEqual(
            s.duration_formatted(),
            "2.7",
        )

    def test_session_range_uses_explicit_presentation(self):
        game = Game.objects.create(name="Range game")
        session = Session.objects.create(
            game=game,
            timestamp_start=datetime(2026, 7, 2, 17, 5, tzinfo=ZoneInfo("UTC")),
            timestamp_end=datetime(2026, 7, 2, 19, 15, tzinfo=ZoneInfo("UTC")),
        )
        presentation = DateTimePresentation(
            DateTimeFormatProfile(
                date_parts=(
                    DatePartSpec("year", "YYYY", 4),
                    DatePartSpec("month", "MM", 2),
                    DatePartSpec("day", "DD", 2),
                ),
                date_separator=".",
                segmented_date_separator="-",
                time_separator="h",
                date_time_separator=" @ ",
                hour_cycle="h12",
            ),
            "en-us",
            ZoneInfo("UTC"),
        )

        self.assertEqual(
            session_time_range(session, presentation),
            "2026.07.02 @ 05h05 PM — 07h15 PM",
        )
