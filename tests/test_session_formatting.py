from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from django.test import TestCase

from common.date_time_presentation import (
    DatePartSpec,
    DateTimeFormatProfile,
    DateTimePresentation,
    date_time_format_profile,
)
from games.formatting import session_time_range
from games.models import Game, Purchase, Session

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
                    DatePartSpec("year", "YYYY", input_length=4, display_min_digits=4),
                    DatePartSpec("month", "MM", input_length=2, display_min_digits=2),
                    DatePartSpec("day", "DD", input_length=2, display_min_digits=2),
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


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("profile_id", "expected"),
    [
        ("iso_8601", "2026-07-02 19:05 — 21:15"),
        ("dmy_24h", "02/07/2026 19:05 — 21:15"),
        ("mdy_12h", "07/02/2026 07:05 PM — 09:15 PM"),
    ],
)
def test_registered_profiles_match_browser_session_range_literals(
    profile_id: str, expected: str
) -> None:
    game = Game.objects.create(name=f"Range {profile_id}")
    session = Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 7, 2, 19, 5, tzinfo=ZoneInfo("UTC")),
        timestamp_end=datetime(2026, 7, 2, 21, 15, tzinfo=ZoneInfo("UTC")),
    )
    presentation = DateTimePresentation(
        date_time_format_profile(profile_id),
        "en-us",
        ZoneInfo("UTC"),
    )

    assert session_time_range(session, presentation) == expected


@pytest.mark.django_db
def test_mdy_12h_session_range_uses_localized_client_contract_day_periods() -> None:
    game = Game.objects.create(name="Localized range")
    session = Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 7, 2, 0, 5, tzinfo=ZoneInfo("UTC")),
        timestamp_end=datetime(2026, 7, 2, 12, 15, tzinfo=ZoneInfo("UTC")),
    )
    presentation = DateTimePresentation(
        date_time_format_profile("mdy_12h"),
        "cs",
        ZoneInfo("UTC"),
    )
    day_periods = presentation.to_client_config()["day_periods"]

    assert day_periods != {"am": "AM", "pm": "PM"}
    assert session_time_range(session, presentation) == (
        f"07/02/2026 12:05 {day_periods['am']} — 12:15 {day_periods['pm']}"
    )
