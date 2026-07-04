"""Regression test for issue #277: a request still in flight when a test body
returns must not break pytest-django's post-test flush of the shared-cache
in-memory SQLite database ("database table is locked").

The patched paginate holds an unfinished SELECT cursor open across a sleep —
exactly the state a slow CI request is in when teardown starts. Without the
network-quiescence fixture in conftest.py the flush's DELETEs then fail;
with it, teardown waits for the response before flushing.
"""

import time

import pytest
from django.urls import reverse
from playwright.sync_api import Page


@pytest.fixture
def authenticated_page(live_server, page: Page, django_user_model) -> Page:
    django_user_model.objects.create_user(username="tester", password="secret123")
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")
    return page


@pytest.mark.django_db
def test_flush_tolerates_inflight_request(
    authenticated_page: Page, live_server, monkeypatch
):
    import games.views.game as game_views
    from games.models import Game, Platform

    platform = Platform.objects.create(name="PC", icon="pc")
    Game.objects.bulk_create(
        Game(name=f"Game {i}", platform=platform) for i in range(10)
    )

    real_paginate = game_views.paginate

    def slow_paginate(request, queryset, per_page=10):
        from django.db import connection

        # Fetch one row of several, then sleep: the SELECT statement stays
        # active (mid-cursor) on the shared in-memory connection — the state
        # that makes a concurrent flush fail with "database table is locked".
        cursor = connection.cursor()
        cursor.execute("SELECT * FROM games_game")
        cursor.fetchone()
        time.sleep(1.5)
        cursor.fetchall()
        cursor.close()
        return real_paginate(request, queryset, per_page)

    monkeypatch.setattr(game_views, "paginate", slow_paginate)

    page = authenticated_page
    # Fire-and-forget, like the htmx refreshes real tests end with.
    page.evaluate(f"() => {{ fetch('{reverse('games:list_games')}'); }}")
    # Let the request reach the patched view and open its cursor before the
    # test returns and teardown begins.
    page.wait_for_timeout(300)
