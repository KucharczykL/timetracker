from datetime import UTC, date, datetime
from pathlib import Path
import re
from zoneinfo import ZoneInfo

import pytest
from django.urls import reverse
from django.utils import timezone

from common import date_time_presentation as presentation_module
from common.date_time_presentation import (
    DatePartSpec,
    DateTimeFormatProfile,
)
from games.models import (
    Device,
    Game,
    GameStatusChange,
    Platform,
    PlayEvent,
    Purchase,
    Session,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


ALTERNATE_PROFILE = DateTimeFormatProfile(
    date_parts=(
        DatePartSpec("year", "YYYY", 4),
        DatePartSpec("day", "DD", 2),
        DatePartSpec("month", "MM", 2),
    ),
    date_separator=".",
    segmented_date_separator="·",
    time_separator="h",
    date_time_separator=" @ ",
    hour_cycle="h23",
)


@pytest.mark.django_db
def test_non_default_presentation_reaches_every_server_display_path(
    client, django_user_model, monkeypatch
) -> None:
    monkeypatch.setattr(
        presentation_module,
        "DEFAULT_DATE_TIME_FORMAT_PROFILE",
        ALTERNATE_PROFILE,
    )
    user = django_user_model.objects.create_user(username="dates", password="pw")
    client.force_login(user)

    platform = Platform.objects.create(name="PC")
    device = Device.objects.create(name="Desktop")
    game = Game.objects.create(name="Calendar Game", platform=platform)
    purchase = Purchase.objects.create(
        date_purchased=date(2022, 9, 26),
        date_refunded=date(2022, 9, 27),
        platform=platform,
        num_purchases=1,
    )
    purchase.games.add(game)
    session = Session.objects.create(
        game=game,
        device=device,
        timestamp_start=datetime(2022, 9, 26, 12, 58, tzinfo=UTC),
        timestamp_end=datetime(2022, 9, 26, 13, 58, tzinfo=UTC),
    )
    playevent = PlayEvent.objects.create(
        game=game,
        started=date(2022, 9, 24),
        ended=date(2022, 9, 25),
    )
    GameStatusChange.objects.create(
        game=game,
        old_status=Game.Status.UNPLAYED,
        new_status=Game.Status.PLAYED,
        timestamp=datetime(2022, 9, 23, 10, 30, tzinfo=UTC),
    )

    created_values = (
        (Game, game.pk, datetime(2022, 10, 1, tzinfo=UTC)),
        (Platform, platform.pk, datetime(2022, 10, 2, tzinfo=UTC)),
        (Device, device.pk, datetime(2022, 10, 3, tzinfo=UTC)),
        (Purchase, purchase.pk, datetime(2022, 10, 4, tzinfo=UTC)),
        (Session, session.pk, datetime(2022, 10, 5, tzinfo=UTC)),
        (PlayEvent, playevent.pk, datetime(2022, 10, 6, tzinfo=UTC)),
    )
    for model, pk, value in created_values:
        model.objects.filter(pk=pk).update(created_at=value)

    expected_by_route = {
        reverse("games:list_games"): "2022.01.10",
        reverse("games:list_platforms"): "2022.02.10",
        reverse("games:list_devices"): "2022.03.10",
        reverse("games:list_purchases"): "2022.04.10",
        reverse("games:list_sessions"): "2022.26.09 @ 12h58",
        reverse("games:list_playevents"): "2022.24.09",
        reverse("games:list_statuschanges"): "2022.23.09",
        reverse("games:view_purchase", args=[purchase.pk]): "Owned on 2022.26.09",
        reverse("games:stats_alltime"): "2022.26.09",
    }

    with timezone.override(ZoneInfo("UTC")):
        for url, expected in expected_by_route.items():
            html = client.get(url).content.decode()
            assert expected in html, url

        game_html = client.get(
            reverse("games:view_game", args=[game.pk])
        ).content.decode()
        for expected in (
            "2022.26.09 @ 12h58",
            "2022.26.09",
            "2022.24.09",
            "2022.23.09 @ 10h30",
        ):
            assert expected in game_html


def test_legacy_server_display_formatting_source_audit_is_clean() -> None:
    forbidden = re.compile(
        r"\b(?:dateformat|dateformat_hyphenated|datetimeformat|timeformat|"
        r"local_strftime|date_filter)\b|\bdate_parts\(|\.strftime\("
    )
    matches: list[str] = []

    for package in ("common", "games"):
        for path in (PROJECT_ROOT / package).rglob("*.py"):
            for line_number, line in enumerate(path.read_text().splitlines(), start=1):
                if forbidden.search(line):
                    matches.append(
                        f"{path.relative_to(PROJECT_ROOT)}:{line_number}: {line.strip()}"
                    )

    assert matches == []
