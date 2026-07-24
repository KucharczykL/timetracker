"""Regression test for issue #476: the e2e suite's concurrent live_server
requests must not run against a shared-cache in-memory database.

Django names an in-memory test database
``file:memorydb_default?mode=memory&cache=shared``, and pytest-django's
``live_server`` serves every request on its own thread
(``ThreadedWSGIServer``), alongside the test thread's own ORM calls. Against
shared-cache SQLite that produces two distinct failure modes, both seen in the
intermittent full-suite failures:

* separate connections sharing the cache lock at *table* granularity, raising
  SQLITE_LOCKED ("database table is locked") — which the ``timeout`` option
  cannot wait out, because SQLite never invokes the busy handler for it;
* and when ``live_server`` is constructed after the test database exists,
  pytest-django detects the in-memory name and hands the test thread's
  connection *object* to the server thread, so request threads interleave
  statements and transactions on one connection (``IndexError`` in
  ``apply_converters``, sessions that read back empty and log the browser out).

Both disappear with an on-disk test database: one connection per thread, WAL
locking, and contention that degrades to plain SQLITE_BUSY.
"""

import concurrent.futures
import json
import urllib.request

import pytest
from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY
from django.contrib.sessions.backends.db import SessionStore

WRITER_THREADS = 8
READER_THREADS = 8
REQUESTS_PER_THREAD = 12


def _authenticated_session_key(user) -> str:
    """Build a logged-in session row directly, skipping the login round-trip."""
    session = SessionStore()
    session[SESSION_KEY] = str(user.pk)
    session[BACKEND_SESSION_KEY] = "django.contrib.auth.backends.ModelBackend"
    session[HASH_SESSION_KEY] = user.get_session_auth_hash()
    session.create()
    session_key = session.session_key
    assert session_key is not None  # set by create()
    return session_key


def _csrf_token(session_key: str, live_server) -> str:
    request = urllib.request.Request(
        f"{live_server.url}/tracker/game/list",
        headers={"Cookie": f"sessionid={session_key}"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        cookies = response.headers.get_all("Set-Cookie") or []
    for cookie in cookies:
        if cookie.startswith("csrftoken="):
            return cookie.split(";", 1)[0].removeprefix("csrftoken=")
    raise AssertionError(f"no csrftoken cookie in {cookies!r}")


@pytest.mark.django_db(transaction=True)
def test_test_database_is_on_disk():
    """The structural half of the bug: an in-memory test database is what makes
    both failure modes possible, so assert it directly. ``live_server`` is not
    requested here — whether it shares the test thread's connection depends on
    the order pytest happens to build the two session fixtures in, and this
    invariant must hold either way."""
    from django.db import connections

    connection = connections["default"]
    assert not connection.is_in_memory_db(), connection.settings_dict["NAME"]


@pytest.mark.django_db(transaction=True)
def test_concurrent_live_server_requests_all_succeed(live_server, django_user_model):
    """Hammer the live server with interleaved reads and transactional writes.

    The writes go through ``PATCH /api/settings/user/THEME``, which runs inside
    ``transaction.atomic()`` — the code path the flaky settings e2e exercises.
    Against the in-memory database this fails within seconds; on disk, with one
    connection per thread, every request succeeds.
    """
    from games.models import Game, Platform

    user = django_user_model.objects.create_user(username="tester", password="secret")
    platform = Platform.objects.create(name="PC", icon="pc")
    Game.objects.bulk_create(
        Game(name=f"Game {index}", platform=platform) for index in range(60)
    )

    session_key = _authenticated_session_key(user)
    csrf_token = _csrf_token(session_key, live_server)
    cookie = f"sessionid={session_key}; csrftoken={csrf_token}"

    def read_repeatedly() -> None:
        for _ in range(REQUESTS_PER_THREAD):
            request = urllib.request.Request(
                f"{live_server.url}/tracker/game/list",
                headers={"Cookie": cookie},
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                assert response.status == 200

    def write_repeatedly(worker: int) -> None:
        themes = ("light", "dark", "system")
        for index in range(REQUESTS_PER_THREAD):
            body = json.dumps({"value": themes[(worker + index) % len(themes)]})
            request = urllib.request.Request(
                f"{live_server.url}/api/settings/user/THEME",
                data=body.encode(),
                method="PATCH",
                headers={
                    "Cookie": cookie,
                    "Content-Type": "application/json",
                    "X-CSRFToken": csrf_token,
                    "Referer": live_server.url,
                },
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                assert response.status == 200

    workers = READER_THREADS + WRITER_THREADS
    with concurrent.futures.ThreadPoolExecutor(workers) as pool:
        futures = [pool.submit(read_repeatedly) for _ in range(READER_THREADS)]
        futures += [pool.submit(write_repeatedly, i) for i in range(WRITER_THREADS)]
        # Keep the test thread querying too — the real e2e tests do ORM work
        # while the browser has requests in flight.
        for _ in range(REQUESTS_PER_THREAD * 4):
            assert Game.objects.count() == 60
        errors = [future.exception() for future in futures]

    failures = [error for error in errors if error is not None]
    assert not failures, (
        f"{len(failures)}/{len(errors)} threads failed: {failures[0]!r}"
    )
