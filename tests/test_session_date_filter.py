"""Date-range filtering on session timestamps (issue #56, Component 2).

The navbar 'today' / 'last 7 days' links need SessionFilter to express date
ranges over the timestamp_start datetime column."""

from datetime import timedelta

import pytest
from django.utils.timezone import localtime
from django.utils.timezone import now as timezone_now

from games.filters import SessionFilter
from games.models import Game, Platform, Session


@pytest.fixture
def sessions_across_days(db):
    platform = Platform.objects.create(name="PC")
    game = Game.objects.create(name="Zelda", platform=platform)
    today = localtime(timezone_now())
    return {
        "today": Session.objects.create(game=game, timestamp_start=today),
        "three_days_ago": Session.objects.create(
            game=game, timestamp_start=today - timedelta(days=3)
        ),
        "ten_days_ago": Session.objects.create(
            game=game, timestamp_start=today - timedelta(days=10)
        ),
        "today_date": today.date(),
    }


def test_today_filter_matches_only_todays_sessions(sessions_across_days):
    today_iso = sessions_across_days["today_date"].isoformat()
    session_filter = SessionFilter.where(timestamp_start=today_iso)
    matched = list(Session.objects.filter(session_filter.to_q()))
    assert matched == [sessions_across_days["today"]]


def test_last_7_days_filter_matches_calendar_window(sessions_across_days):
    today_date = sessions_across_days["today_date"]
    session_filter = SessionFilter.where(
        timestamp_start__between=(
            (today_date - timedelta(days=6)).isoformat(),
            today_date.isoformat(),
        )
    )
    matched = set(
        Session.objects.filter(session_filter.to_q()).values_list("id", flat=True)
    )
    assert matched == {
        sessions_across_days["today"].id,
        sessions_across_days["three_days_ago"].id,
    }
