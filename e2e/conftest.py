import os
import shutil
import time

import pytest
from playwright.sync_api import Request

# Playwright runs an async event loop in the background, which triggers
# Django's async safety checks when running synchronous tests. This allows
# synchronous operations inside the async context safely.
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")


@pytest.fixture(autouse=True)
def _flush_waits_for_inflight_requests(request: pytest.FixtureRequest):
    """Wait for browser network quiescence before the post-test DB flush (#277).

    pytest-django's teardown flush of the shared-cache in-memory SQLite
    database fails with "database table is locked" when a live_server request
    is still mid-read — an unfinished SELECT cursor blocks the flush's
    DELETEs, even on the shared connection. Tests legitimately end with
    fire-and-forget requests (htmx refreshes like the play-added /
    status-changed section reloads, filter-count GETs), so before the DB
    teardown runs we wait until no request is in flight and none starts for a
    short settle window (covering htmx chains that fetch again after a swap).
    """
    if "page" not in request.fixturenames or "live_server" not in request.fixturenames:
        yield
        return

    # Instantiate the DB fixture before this one so its teardown (the flush)
    # runs after ours (the wait). live_server tests always get transactional_db.
    request.getfixturevalue("transactional_db")
    page = request.getfixturevalue("page")

    inflight_requests: set[Request] = set()

    def track_request_start(started_request: Request) -> None:
        inflight_requests.add(started_request)

    def track_request_end(ended_request: Request) -> None:
        inflight_requests.discard(ended_request)

    context = page.context
    context.on("request", track_request_start)
    context.on("requestfinished", track_request_end)
    context.on("requestfailed", track_request_end)

    yield

    deadline = time.monotonic() + 10.0
    quiet_since: float | None = None
    while not page.is_closed() and time.monotonic() < deadline:
        if inflight_requests:
            quiet_since = None
        else:
            if quiet_since is None:
                quiet_since = time.monotonic()
            if time.monotonic() - quiet_since >= 0.1:
                break
        # Blocking playwright call: pumps the event loop so the request
        # events above keep being delivered while we wait.
        page.wait_for_timeout(25)


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):
    # Try to find a system-installed Google Chrome or Chromium to bypass Nix/NixOS shared library issues
    for browser_name in ["google-chrome-stable", "google-chrome", "chromium", "chrome"]:
        path = shutil.which(browser_name)
        if path:
            return {
                **browser_type_launch_args,
                "executable_path": path,
            }
    # Fallback to default Playwright behavior
    return browser_type_launch_args
