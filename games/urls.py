from django.conf import settings
from django.urls import path, register_converter

from games.views import (
    device,
    game,
    general,
    library,
    platform,
    playthrough,
    purchase,
    session,
)
from timetracker.uuidv7 import UUIDv7Converter

# Registered here rather than in the project URLconf: several tests import this
# module under a stripped ROOT_URLCONF, where the project's registration never
# runs and every route with a uuidv7 argument would fail to build.
register_converter(UUIDv7Converter, "uuidv7")
from games.views import settings as settings_views

app_name = "games"

urlpatterns = [
    path("", general.index, name="index"),
    path("library", library.library, name="library"),
    path("settings", settings_views.user_settings, name="settings"),
    path(
        "admin-settings",
        settings_views.admin_settings,
        name="admin_settings",
    ),
    path(
        "admin-settings/export",
        settings_views.export_admin_settings_ini,
        name="export_admin_settings_ini",
    ),
    path("device/add", device.add_device, name="add_device"),
    path(
        "device/<uuidv7:device_id>/remove", device.remove_device, name="remove_device"
    ),
    path("device/edit/<uuidv7:device_id>", device.edit_device, name="edit_device"),
    path("device/list", device.list_devices, name="list_devices"),
    path("game/add", game.add_game, name="add_game"),
    path("game/<uuidv7:game_id>/edit", game.edit_game, name="edit_game"),
    path(
        "game/<uuidv7:game_id>/view",
        game.retired_game_view,
    ),
    path(
        "game/<uuidv7:game_id>/<slug:slug>/",
        game.view_game,
        name="view_game",
    ),
    path("game/<uuidv7:game_id>/remove", game.remove_game, name="remove_game"),
    path("game/list", game.list_games, name="list_games"),
    path("platform/add", platform.add_platform, name="add_platform"),
    path(
        "platform/<uuidv7:platform_id>/edit",
        platform.edit_platform,
        name="edit_platform",
    ),
    path(
        "platform/<uuidv7:platform_id>/remove",
        platform.remove_platform,
        name="remove_platform",
    ),
    path("platform/list", platform.list_platforms, name="list_platforms"),
    path("playthrough/list", playthrough.list_playthroughs, name="list_playthroughs"),
    path("playthrough/add", playthrough.add_playthrough, name="add_playthrough"),
    path(
        "playthrough/add/for-game/<uuidv7:game_id>",
        playthrough.add_playthrough,
        name="add_playthrough_for_game",
    ),
    path(
        "playthrough/edit/<uuidv7:playthrough_id>",
        playthrough.edit_playthrough,
        name="edit_playthrough",
    ),
    path(
        "playthrough/<uuidv7:playthrough_id>/remove",
        playthrough.remove_playthrough,
        name="remove_playthrough",
    ),
    path("purchase/add", purchase.add_purchase, name="add_purchase"),
    path(
        "purchase/add/for-game/<uuidv7:game_id>",
        purchase.add_purchase,
        name="add_purchase_for_game",
    ),
    path(
        "purchase/<uuidv7:purchase_id>/edit",
        purchase.edit_purchase,
        name="edit_purchase",
    ),
    path(
        "purchase/<uuidv7:purchase_id>/remove",
        purchase.remove_purchase,
        name="remove_purchase",
    ),
    path(
        "purchase/<uuidv7:purchase_id>/view",
        purchase.view_purchase,
        name="view_purchase",
    ),
    path(
        "purchase/list",
        purchase.list_purchases,
        name="list_purchases",
    ),
    path(
        "purchase/<uuidv7:purchase_id>/refund/confirm",
        purchase.refund_purchase_confirmation,
        name="refund_purchase_confirmation",
    ),
    path(
        "purchase/<uuidv7:purchase_id>/refund",
        purchase.refund_purchase,
        name="refund_purchase",
    ),
    path(
        "purchase/<uuidv7:purchase_id>/split/confirm",
        purchase.split_purchase_confirmation,
        name="split_purchase_confirmation",
    ),
    path(
        "purchase/<uuidv7:purchase_id>/split",
        purchase.split_purchase,
        name="split_purchase",
    ),
    path("session/add", session.add_session, name="add_session"),
    path(
        "session/add/for-game/<uuidv7:game_id>",
        session.add_session,
        name="add_session_for_game",
    ),
    path(
        "session/add/from-list/<uuidv7:session_id>",
        session.new_session_from_existing_session,
        name="list_sessions_start_session_from_session",
    ),
    path("session/<uuidv7:session_id>/edit", session.edit_session, name="edit_session"),
    path(
        "session/<uuidv7:session_id>/finish",
        session.finish_session,
        name="finish_session",
    ),
    path(
        "session/<uuidv7:session_id>/reset",
        session.reset_session,
        name="reset_session",
    ),
    path(
        "session/<uuidv7:session_id>/remove",
        session.remove_session,
        name="remove_session",
    ),
    path("session/list", session.list_sessions, name="list_sessions"),
    path("stats/", general.stats_alltime, name="stats_alltime"),
    path("stats/<int:year>", general.stats, name="stats_by_year"),
    path("<str:model>/filter", general.filter_builder, name="filter_builder"),
]


def _settings_kit_preview_urlpatterns():
    """Keep the developer gallery entirely absent from production routing."""

    if not settings.DEBUG:
        return []
    from games.views import settings_kit_preview

    return [
        path(
            "settings-kit-preview/",
            settings_kit_preview.settings_kit_preview,
            name="settings_kit_preview",
        ),
        path(
            "settings-kit-preview/patch/<str:key>/",
            settings_kit_preview.settings_kit_preview_patch,
            name="settings_kit_preview_patch",
        ),
    ]


urlpatterns += _settings_kit_preview_urlpatterns()
