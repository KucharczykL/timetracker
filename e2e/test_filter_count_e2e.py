"""Browser test for the live result-count badge (<filter-count>, issue #195).

A synthetic page pairs a real ``<filter-group>`` with two ``<filter-count>``
badges and drives them against pytest-django's ``live_server``. The page's
``urlpatterns`` extend the real project URLs, so ``/api/filter/count`` and the
login route stay mounted under the ``override_settings(ROOT_URLCONF=...)`` swap.

The badge's ``connectedCallback`` kicks an initial count for the (empty) filter,
so the end-to-end endpoint→fetch→render path — including singular/plural nouns
and the "count unavailable" error state — is exercised on load without driving
the builder UI (the debounce/cancel/stale logic is unit-tested in vitest).
"""

import pytest
from django.http import HttpResponse
from django.test import override_settings
from django.urls import path, reverse
from playwright.sync_api import Page, expect

from common.components import FilterCount, FilterGroup
from common.components.core import Document
from common.components.primitives import (
    Body,
    Div,
    Head,
    Html,
    Link,
    Meta,
    Script,
    Title,
)
from games.models import Game, Platform
from timetracker.urls import urlpatterns as base_urlpatterns

COUNT_ENDPOINT = "/api/filter/count"


def filter_count_view(request):
    from django.templatetags.static import static

    page = Document(
        Html(lang="en")[
            Head()[
                Title()["filter-count demo"],
                Meta(charset="utf-8"),
                Link(rel="stylesheet", href=static("base.css")),
                Script(type="module", src=static("js/dist/elements/filter-group.js")),
                Script(type="module", src=static("js/dist/elements/search-select.js")),
                Script(
                    type="module", src=static("js/dist/elements/date-range-picker.js")
                ),
                Script(type="module", src=static("js/dist/elements/filter-count.js")),
            ],
            Body(class_="p-6")[
                FilterGroup(model="game"),
                Div(id="ok-count")[
                    FilterCount(
                        model="game",
                        noun_singular="game",
                        noun_plural="games",
                        endpoint=COUNT_ENDPOINT,
                    )
                ],
                # A deliberately unknown model → the endpoint 400s → the badge must
                # show "count unavailable", never a bare 0.
                Div(id="bad-count")[
                    FilterCount(
                        model="bogus",
                        noun_singular="thing",
                        noun_plural="things",
                        endpoint=COUNT_ENDPOINT,
                    )
                ],
            ],
        ]
    )
    return HttpResponse(page)


urlpatterns = [*base_urlpatterns, path("filter-count-test/", filter_count_view)]


def _login_and_open(page: Page, live_server) -> None:
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")
    page.goto(f"{live_server.url}/filter-count-test/")


@pytest.fixture
def platform(db):
    return Platform.objects.create(name="PC")


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_filter_count_e2e")
def test_badge_shows_total_and_error_state(
    live_server, page: Page, django_user_model, platform
):
    django_user_model.objects.create_user(username="tester", password="secret123")
    for name in ("Hades", "Celeste", "Braid"):
        Game.objects.create(name=name, platform=platform)

    _login_and_open(page, live_server)

    # The valid badge counts all three games (plural noun).
    expect(page.locator("#ok-count filter-count")).to_have_text("≈ 3 games")
    # The unknown-model badge degrades to an explicit error, not "0".
    expect(page.locator("#bad-count filter-count")).to_have_text("count unavailable")


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_filter_count_e2e")
def test_badge_uses_singular_noun_for_one(
    live_server, page: Page, django_user_model, platform
):
    django_user_model.objects.create_user(username="tester", password="secret123")
    Game.objects.create(name="Hades", platform=platform)

    _login_and_open(page, live_server)

    expect(page.locator("#ok-count filter-count")).to_have_text("≈ 1 game")
