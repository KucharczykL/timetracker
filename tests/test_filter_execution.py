import pytest
from django.contrib.messages.storage.fallback import FallbackStorage
from django.db import connection
from django.http import HttpResponse
from django.test import RequestFactory
from ninja.errors import HttpError

from common.filter_execution import (
    FilterQueryTimeout,
    regex_timeout_api,
    regex_timeout_view,
    run_with_regex_timeout,
)
from games.models import Game


@pytest.mark.django_db(transaction=True)
def test_regex_timeout_is_transaction_local_and_resets_after_callback():
    def callback():
        with connection.cursor() as cursor:
            cursor.execute("SHOW statement_timeout")
            return cursor.fetchone()[0]

    assert (
        run_with_regex_timeout('{"name":{"modifier":"MATCHES_REGEX"}}', callback)
        == "1s"
    )
    with connection.cursor() as cursor:
        cursor.execute("SHOW statement_timeout")
        assert cursor.fetchone()[0] == "0"


@pytest.mark.django_db(transaction=True)
def test_regex_timeout_translates_postgres_cancellation(monkeypatch):
    monkeypatch.setattr("common.filter_execution.FILTER_STATEMENT_TIMEOUT_MS", 1)

    def callback():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_sleep(0.05)")

    with pytest.raises(FilterQueryTimeout):
        run_with_regex_timeout('{"name":{"modifier":"MATCHES_REGEX"}}', callback)


def test_html_timeout_redirects_without_filter_or_page(monkeypatch):
    @regex_timeout_view
    def view(_request):
        return HttpResponse("unreachable")

    def timeout(_filter_json, _callback):
        raise FilterQueryTimeout

    monkeypatch.setattr("common.filter_execution.run_with_regex_timeout", timeout)
    request = RequestFactory().get("/games/?filter=regex&page=3&sort=name&per_page=100")
    request.session = {}
    request._messages = FallbackStorage(request)  # type: ignore[attr-defined]

    response = view(request)

    assert response.status_code == 302
    assert response.url == "/games/?sort=name&per_page=100"


def test_api_timeout_becomes_a_bad_request(monkeypatch):
    @regex_timeout_api
    def endpoint(_request):
        return {"unreachable": True}

    def timeout(_filter_json, _callback):
        raise FilterQueryTimeout

    monkeypatch.setattr("common.filter_execution.run_with_regex_timeout", timeout)

    with pytest.raises(HttpError, match="filter took too long") as exc_info:
        endpoint(RequestFactory().get("/api/filter/count?filter=regex"))

    assert exc_info.value.status_code == 400


@pytest.mark.django_db
@pytest.mark.parametrize(
    "pattern, expected",
    [
        ("zelda", {"zelda"}),
        ("(mario|zelda)", {"mario", "zelda"}),
        ("(?i)^ZELDA$", {"zelda"}),
    ],
)
def test_postgresql_patterns_match_the_postgresql_orm(pattern, expected, owned_library):
    Game.objects.bulk_create(
        [
            Game(library=owned_library, name=name)
            for name in ("zelda", "mario", "metroid")
        ]
    )
    assert (
        set(Game.objects.filter(name__regex=pattern).values_list("name", flat=True))
        == expected
    )
