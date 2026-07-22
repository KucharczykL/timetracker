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

from django.http import HttpResponse
from django.test import override_settings
from django.urls import path, reverse
from playwright.sync_api import Page, expect

from common.components import FilterCount, FilterGroup
from common.components.core import Document
from common.date_time_presentation import date_time_presentation_for_request
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

    # Exactly ONE <filter-count> per page. Each badge auto-fetches the count on
    # load; two badges would fire two concurrent authenticated requests into the
    # live_server thread and contend on the SQLite connection (InterfaceError).
    # The badge's model comes from the query string so a single view serves both
    # the valid-count and the unknown-model (error-state) cases; the <filter-group>
    # stays "game" (it needs a real model for its field metadata) while the badge's
    # own model is what the endpoint receives.
    badge_model = request.GET.get("model", "game")
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
                FilterGroup(
                    model="game",
                    presentation=date_time_presentation_for_request(request),
                ),
                Div(id="count")[
                    FilterCount(
                        model=badge_model,
                        noun_singular="game",
                        noun_plural="games",
                        endpoint=COUNT_ENDPOINT,
                    )
                ],
            ],
        ]
    )
    return HttpResponse(page)


urlpatterns = [*base_urlpatterns, path("filter-count-test/", filter_count_view)]


def _login_and_open(page: Page, live_server, query: str = "") -> None:
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")
    page.goto(f"{live_server.url}/filter-count-test/{query}")


# NB: no ``@pytest.mark.django_db`` / ``db`` fixture here. ``live_server`` pulls in
# ``transactional_db`` (committed rows visible to the server thread); mixing the
# plain ``db`` fixture with it breaks the between-test table flush, which leaked a
# second "tester" user into the next test (User.MultipleObjectsReturned on login).
# Mirror the working ``test_widgets_e2e`` pattern: create rows in the test body.


@override_settings(ROOT_URLCONF="e2e.test_filter_count_e2e")
def test_badge_shows_total(live_server, page: Page, django_user_model):
    django_user_model.objects.create_user(username="tester", password="secret123")
    platform = Platform.objects.create(name="PC")
    for name in ("Hades", "Celeste", "Braid"):
        Game.objects.create(name=name, platform=platform)

    _login_and_open(page, live_server)

    # The valid badge counts all three games (plural noun).
    expect(page.locator("#count filter-count")).to_have_text("≈ 3 games")


@override_settings(ROOT_URLCONF="e2e.test_filter_count_e2e")
def test_badge_uses_singular_noun_for_one(live_server, page: Page, django_user_model):
    django_user_model.objects.create_user(username="tester", password="secret123")
    platform = Platform.objects.create(name="PC")
    Game.objects.create(name="Hades", platform=platform)

    _login_and_open(page, live_server)

    expect(page.locator("#count filter-count")).to_have_text("≈ 1 game")


@override_settings(ROOT_URLCONF="e2e.test_filter_count_e2e")
def test_badge_shows_error_state_on_bad_model(
    live_server, page: Page, django_user_model
):
    django_user_model.objects.create_user(username="tester", password="secret123")

    # The badge's model is unknown → the endpoint 400s → the badge must show an
    # explicit "count unavailable", never a bare 0.
    _login_and_open(page, live_server, query="?model=bogus")

    expect(page.locator("#count filter-count")).to_have_text("count unavailable")
