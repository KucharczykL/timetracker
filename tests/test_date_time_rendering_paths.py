import re
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from pathlib import Path

import pytest
from django.urls import reverse

import common.layout
from common import date_time_presentation as presentation_module
from common.date_time_presentation import build_format_profile
from games.models import (
    Device,
    Game,
    GameStatusChange,
    Platform,
    PlayEvent,
    Purchase,
    Session,
)
from timetracker.settings_commands import change_user_setting

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class _TitleParser(HTMLParser):
    title = ""
    _in_title = False
    _document_title_seen = False

    def handle_starttag(self, tag, attrs) -> None:
        if tag == "title" and not self._document_title_seen:
            self._in_title = True
            self._document_title_seen = True

    def handle_endtag(self, tag) -> None:
        if tag == "title":
            self._in_title = False

    def handle_data(self, data) -> None:
        if self._in_title:
            self.title += data


class _DatePartParser(HTMLParser):
    parts: list[str]

    def __init__(self) -> None:
        super().__init__()
        self.parts = []

    def handle_starttag(self, tag, attrs) -> None:
        if tag != "input":
            return
        attributes = dict(attrs)
        if part := attributes.get("data-date-part"):
            self.parts.append(part)


ALTERNATE_PROFILE = build_format_profile(
    ("year", "day", "month"),
    hour_cycle="h23",
    display_separator=".",
    segmented_separator="·",
    time_separator="h",
    date_time_separator=" @ ",
)


@pytest.mark.django_db
def test_non_default_presentation_reaches_every_server_display_path(
    client, django_user_model, monkeypatch, django_capture_on_commit_callbacks
) -> None:
    monkeypatch.setattr(
        presentation_module,
        "date_time_format_profile",
        lambda _profile_id: ALTERNATE_PROFILE,
    )
    monkeypatch.setattr(
        common.layout,
        "version_modified_at",
        lambda: datetime(2022, 7, 22, 12, 5, tzinfo=UTC),
    )
    user = django_user_model.objects.create_user(username="dates", password="pw")
    with django_capture_on_commit_callbacks(execute=True):
        change_user_setting(user, "DISPLAY_TIME_ZONE", "UTC")
        change_user_setting(user, "DATE_FORMAT_LOCALE", "cs")
    client.force_login(user)

    platform = Platform.objects.create(library=user.library, name="PC")
    device = Device.objects.create(library=user.library, name="Desktop")
    game = Game.objects.create(
        library=user.library, name="Calendar Game", platform=platform
    )
    purchase = Purchase.objects.create(
        price_currency="CZK",
        library=user.library,
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
        reverse("games:list_games"): ("2022.01.10",),
        reverse("games:list_platforms"): ("2022.02.10",),
        reverse("games:list_devices"): ("2022.03.10",),
        reverse("games:list_purchases"): (
            "2022.26.09",
            "2022.25.09",
            "2022.27.09",
            "2022.04.10",
            'data-date-part="year"',
            "·",
        ),
        reverse("games:list_sessions"): (
            "2022.26.09 @ 12h58",
            "13h58",
            "2022.05.10",
        ),
        reverse("games:list_playevents"): (
            "2022.24.09",
            "2022.25.09",
            "2022.06.10",
        ),
        reverse("games:list_statuschanges"): ("2022.23.09",),
        reverse("games:stats_alltime"): ("2022.26.09",),
        reverse("games:stats_by_year", args=[2022]): (
            "září",
            "2022.25.09",
        ),
    }

    for url, expected_values in expected_by_route.items():
        html = client.get(url).content.decode()
        for expected in expected_values:
            assert expected in html, url
        assert "dev (2022.22.07 @ 12h05)" in html, url

        if url == reverse("games:list_purchases"):
            date_part_parser = _DatePartParser()
            date_part_parser.feed(html)
            assert date_part_parser.parts[:3] == ["year", "day", "month"]
        if url == reverse("games:stats_by_year", args=[2022]):
            assert "září 2022" not in html

    purchase_html = client.get(
        reverse("games:view_purchase", args=[purchase.pk])
    ).content.decode()
    assert "Owned on 2022.26.09" in purchase_html
    title_parser = _TitleParser()
    title_parser.feed(purchase_html)
    assert "2022.26.09" in title_parser.title
    assert "2022-09-26" not in title_parser.title

    game_html = client.get(game.get_absolute_url()).content.decode()
    for expected in (
        "2022.26.09 @ 12h58",
        "2022.26.09",
        "2022.24.09",
        "2022.23.09 @ 10h30",
        "září 2022",
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


def test_calendar_client_presentation_source_audit_is_clean() -> None:
    path = PROJECT_ROOT / "ts" / "elements" / "date-range-picker.ts"
    forbidden = re.compile(r"\bWEEKDAY_LABELS\b|toLocaleDateString\(undefined")

    matches = [
        f"{path.relative_to(PROJECT_ROOT)}:{line_number}: {line.strip()}"
        for line_number, line in enumerate(path.read_text().splitlines(), start=1)
        if forbidden.search(line)
    ]

    assert matches == []
