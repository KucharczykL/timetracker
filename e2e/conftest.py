import os
import shutil
import sys
import uuid
from pathlib import Path

import pytest
from django.db.models.signals import post_save
from django.utils import timezone

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


@pytest.fixture
def e2e_user(django_user_model, live_server):
    """Provision the explicit owner used by ordinary authenticated E2E tests."""
    user, _created = django_user_model.objects.get_or_create(username="tester")
    if not user.check_password("secret123"):
        user.set_password("secret123")
        user.save(update_fields=["password"])
    return user


@pytest.fixture
def e2e_library(e2e_user):
    return e2e_user.library


@pytest.fixture(autouse=True)
def _track_created_games(request):
    """Give every game a test creates the projection row a read needs.

    games/views/game.py dispatches TrackGame, migration
    0033_playergame_baseline_backfill covers a restored dump, and
    load_sample_data calls backfill_library(). A test is the fourth source of a
    game and leaves no row, so the inner join in ``GameQuerySet.tracked_by()``
    would hide it.

    A direct write, not ``backfill_game()``: the backfill needs an actor and a
    run time, opens its own transaction and appends events. The row is what the
    join wants, so the row is what this writes. The divergence from production
    is real and deliberate; tests/test_playergame_write_path.py covers the
    event path.

    Duplicated from tests/conftest.py: the two suites share no conftest, and
    importing across them would make e2e depend on the unit suite's collection.
    """
    from games.models import Game, PlayerGame

    if "untracked_games" in request.keywords:
        yield
        return

    def track(sender, instance, created, raw, **kwargs):
        #: raw is a loaddata row: the library may not exist yet.
        if raw or not created or instance.library_id is None:
            return
        PlayerGame.objects.get_or_create(
            library_id=instance.library_id,
            game=instance,
            defaults={"pk": uuid.uuid7(), "tracked_at": timezone.now()},
        )

    post_save.connect(track, sender=Game, dispatch_uid="test-track-created-games")
    try:
        yield
    finally:
        post_save.disconnect(sender=Game, dispatch_uid="test-track-created-games")


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
