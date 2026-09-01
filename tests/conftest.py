import contextlib
import logging
import uuid
from typing import NamedTuple

import pytest
from django.db.models.signals import post_save
from django.utils import timezone

from games.catalog_writes import EditionState, ReleaseState, state_catalog_graph
from games.models import Edition, Game, Platform, Release, UserLibrary
from timetracker import config as config_module
from timetracker import settings_resolver
from timetracker.temporal import TemporalValue


@pytest.fixture
def owned_user(db, django_user_model):
    """Provision an explicit owner for legacy tests adapted to library scoping."""
    return django_user_model.objects.create_user(username="fixture-owner", password="p")


@pytest.fixture
def owned_library(owned_user):
    return owned_user.library


class DefaultGraph(NamedTuple):
    """One Game and the single default graph a test starts from."""

    game: Game
    edition: Edition
    release: Release


@pytest.fixture
def stated_graph():
    """A Game with one default Edition holding one default Release.

    The shape every page draws for a Game nobody has edited, and
    the shape a test wants before it states something else.
    """

    def state(
        game: Game,
        library: UserLibrary,
        *,
        platform: Platform | None = None,
        release_date: TemporalValue | None = None,
    ) -> DefaultGraph:
        game.save()
        written = state_catalog_graph(
            game=game,
            library=library,
            editions=[
                EditionState(
                    key="edition-0",
                    is_default=True,
                    releases=(
                        ReleaseState(
                            key="edition-0-release-0",
                            platform=platform,
                            release_date=release_date,
                            is_default=True,
                        ),
                    ),
                )
            ],
        )
        entry = written.editions[0]
        return DefaultGraph(written.game, entry.edition, entry.releases[0][1])

    return state


@pytest.fixture
def catalog_graph_post():
    """The Editions area's fields, the way a Game form posts them.

    Add Game hosts the whole graph since #969, so a POST stating no
    Edition states no game either. One block holding one marked row
    is the shape the page draws for a Game nobody has written yet.
    """
    from timetracker.temporal import temporal_input_name

    def fields(*, platform: str = "", year: str = "") -> dict[str, str]:
        posted = {
            "editions-count": "1",
            "edition-0-name": "",
            "edition-0-releases-count": "1",
            "edition-0-release-0-platform": platform,
            "in_library": "edition-0-release-0",
        }
        if year:
            row = "edition-0-release-0-release_date"
            posted[temporal_input_name(row, "kind")] = "date"
            posted[temporal_input_name(row, "start_year")] = year
        return posted

    return fields


@pytest.fixture(autouse=True)
def _reset_settings_caches():
    """Isolate the layered settings resolver between tests.

    TestCase transaction rollback fires no ``SiteSetting`` commit signal, so a
    written-then-rolled-back row would otherwise leak through the resolver's TTL
    snapshot into later tests. Also reset the parsed env/ini file caches so
    per-test ``ENV_FILE``/``INI_FILE`` fixtures don't bleed.
    """
    config_module.reset_caches()
    settings_resolver.clear_cache()
    yield
    config_module.reset_caches()
    settings_resolver.clear_cache()


@pytest.fixture
def debug_page_rendering(settings):
    """Render pages with ``settings.DEBUG`` on, the way a developer sees them.

    Needed because the page-level checks in ``common/layout.py`` (notably
    ``assert_unique_element_ids``) only run under DEBUG, which pytest-django
    forces off — so a DEBUG-only page crash passes CI and breaks the moment a
    human opens the page with ``make dev``.

    ``INTERNAL_IPS`` is cleared alongside it so debug_toolbar's middleware stays
    inert (``show_toolbar()`` reads both live). ``timetracker.urls`` appends the
    djdt route only when DEBUG is true at its first, whole-session import, which
    pytest-django has already forced false — so djdt is never reversible here and
    letting the toolbar render would 500 with ``NoReverseMatch`` depending on
    which test happened to run first.
    """
    settings.DEBUG = True
    settings.INTERNAL_IPS = []
    return settings


@pytest.fixture
def capture_games_logger(caplog):
    """Context manager that wires ``caplog`` to the ``games`` logger.

    The ``games`` logger sets ``propagate=False`` in settings
    (``timetracker/settings.py``), so caplog's root handler never sees its
    records. This attaches caplog's handler to the ``games`` logger directly for
    the duration of the block. Use as ``with capture_games_logger(): ...`` and
    then assert against ``caplog.records``.
    """

    @contextlib.contextmanager
    def _capture():
        games_logger = logging.getLogger("games")
        games_logger.addHandler(caplog.handler)
        caplog.set_level(logging.WARNING, logger="games")
        try:
            yield caplog
        finally:
            games_logger.removeHandler(caplog.handler)

    return _capture


@pytest.fixture
def capture_client_errors_logger(caplog):
    """Context manager wiring ``caplog`` to the ``client_errors`` logger.

    ``client_errors`` sets ``propagate=False`` (timetracker/settings.py), so
    caplog's root handler never sees its records; attach caplog's handler
    directly for the block. Mirrors ``capture_games_logger``.
    """

    @contextlib.contextmanager
    def _capture():
        client_logger = logging.getLogger("client_errors")
        client_logger.addHandler(caplog.handler)
        caplog.set_level(logging.ERROR, logger="client_errors")
        try:
            yield caplog
        finally:
            client_logger.removeHandler(caplog.handler)

    return _capture


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
    """
    from games.models import Game, PlayerGame
    from games.playergame_status import player_status_for

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
            defaults={
                "pk": uuid.uuid7(),
                "tracked_at": timezone.now(),
                "status": player_status_for(instance.status),
                "mastered": instance.mastered,
            },
        )

    post_save.connect(track, sender=Game, dispatch_uid="test-track-created-games")
    try:
        yield
    finally:
        post_save.disconnect(sender=Game, dispatch_uid="test-track-created-games")
