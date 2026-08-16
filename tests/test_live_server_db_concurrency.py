"""Concurrent live-server reads, writes, and test-thread queries stay reliable."""

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
def test_concurrent_live_server_requests_all_succeed(live_server, django_user_model):
    """Exercise interleaved authenticated reads, atomic settings writes, and
    test-thread ORM queries."""
    from games.models import Game, Platform

    user = django_user_model.objects.create_user(username="tester", password="secret")
    platform = Platform.objects.create(name="PC", icon="pc")
    Game.objects.bulk_create(
        Game(library=user.library, name=f"Game {index}", platform=platform)
        for index in range(60)
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
        # Keep the test thread querying while request threads are in flight.
        for _ in range(REQUESTS_PER_THREAD * 4):
            assert Game.objects.count() == 60
        errors = [future.exception() for future in futures]

    failures = [error for error in errors if error is not None]
    assert not failures, (
        f"{len(failures)}/{len(errors)} threads failed: {failures[0]!r}"
    )
