import os
import shutil
import sys
import time
from pathlib import Path

import pytest
from playwright.sync_api import Request

from timetracker import config as config_module
from timetracker import settings_resolver

# Playwright runs an async event loop in the background, which triggers
# Django's async safety checks when running synchronous tests. This allows
# synchronous operations inside the async context safely.
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")


@pytest.fixture(autouse=True)
def _reset_settings_caches():
    """Isolate the settings resolver between e2e tests (flush teardown fires no
    SiteSetting commit signal), mirroring tests/conftest.py."""
    config_module.reset_caches()
    settings_resolver.clear_cache()
    yield
    config_module.reset_caches()
    settings_resolver.clear_cache()


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


def _find_system_chrome() -> str | None:
    """Locate a system Chrome/Chromium so e2e can drive the real browser instead
    of Playwright's bundled one (which hits shared-library issues under Nix/NixOS
    and is not downloaded on machines that never ran ``playwright install``).

    Resolution order:

    1. The ``E2E_CHROME`` env var — an explicit path (missing file is an error,
       so a typo fails loudly rather than silently falling back).
    2. An executable on ``PATH`` — the Linux/Nix/CI path, and the primary route
       anywhere Chrome is on ``PATH``. This runs on every OS and is unchanged
       from the original discovery.
    3. Well-known install locations for the current OS only — Windows/macOS
       desktop installs, where Chrome is normally *not* on ``PATH``. Gated by
       ``sys.platform`` so Linux never probes Windows/macOS paths.

    Returns ``None`` when nothing is found, leaving Playwright's default (bundled)
    behavior in place.
    """
    override = os.environ.get("E2E_CHROME")
    if override:
        if Path(override).is_file():
            return override
        raise RuntimeError(f"E2E_CHROME points to a missing file: {override!r}")

    for browser_name in ("google-chrome-stable", "google-chrome", "chromium", "chrome"):
        path = shutil.which(browser_name)
        if path:
            return path

    well_known_paths: list[Path] = []
    if sys.platform == "win32":
        program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        program_files_x86 = os.environ.get(
            "ProgramFiles(x86)", r"C:\Program Files (x86)"
        )
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        well_known_paths = [
            Path(program_files) / "Google/Chrome/Application/chrome.exe",
            Path(program_files_x86) / "Google/Chrome/Application/chrome.exe",
            Path(local_app_data or program_files)
            / "Google/Chrome/Application/chrome.exe",
        ]
    elif sys.platform == "darwin":
        well_known_paths = [
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
        ]
    for candidate in well_known_paths:
        if candidate.is_file():
            return str(candidate)
    return None


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):
    # Prefer a system-installed Chrome/Chromium to bypass Nix/NixOS shared
    # library issues (and to run without a `playwright install` download).
    chrome_path = _find_system_chrome()
    if chrome_path:
        return {
            **browser_type_launch_args,
            "executable_path": chrome_path,
        }
    # Fallback to default Playwright behavior
    return browser_type_launch_args
