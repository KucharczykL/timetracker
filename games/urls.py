from django.conf import settings
from django.urls import path, register_converter

from games.views import (
    device,
    game,
    general,
    library,
    platform,
    playevent,
    purchase,
    session,
    statuschange,
)
from timetracker.uuidv7 import UUIDv7Converter

# Registered here rather than in the project URLconf: several tests import this
# module under a stripped ROOT_URLCONF, where the project's registration never
# runs and every catalog route would fail to build.
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
        "device/delete/<uuidv7:device_id>", device.delete_device, name="delete_device"
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
    path("game/<uuidv7:game_id>/delete", game.delete_game, name="delete_game"),
    path("game/list", game.list_games, name="list_games"),
    path("platform/add", platform.add_platform, name="add_platform"),
    path(
        "platform/<uuidv7:platform_id>/edit",
        platform.edit_platform,
        name="edit_platform",
    ),
    path(
        "platform/<uuidv7:platform_id>/delete",
        platform.delete_platform,
        name="delete_platform",
    ),
    path("platform/list", platform.list_platforms, name="list_platforms"),
    path("playevent/list", playevent.list_playevents, name="list_playevents"),
    path("playevent/add", playevent.add_playevent, name="add_playevent"),
    path(
        "playevent/add/for-game/<uuidv7:game_id>",
        playevent.add_playevent,
        name="add_playevent_for_game",
    ),
    path(
        "playevent/edit/<uuidv7:playevent_id>",
        playevent.edit_playevent,
        name="edit_playevent",
    ),
    path(
        "playevent/delete/<uuidv7:playevent_id>",
        playevent.delete_playevent,
        name="delete_playevent",
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
        "purchase/<uuidv7:purchase_id>/delete",
        purchase.delete_purchase,
        name="delete_purchase",
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
        "session/<uuidv7:session_id>/delete",
        session.delete_session,
        name="delete_session",
    ),
    path("session/list", session.list_sessions, name="list_sessions"),
    path(
        "statuschange/add",
        statuschange.add_statuschange,
        name="add_statuschange",
    ),
    path(
        "statuschange/edit/<uuidv7:statuschange_id>",
        statuschange.edit_statuschange,
        name="edit_statuschange",
    ),
    path(
        "statuschange/delete/<uuidv7:pk>",
        statuschange.delete_statuschange,
        name="delete_statuschange",
    ),
    path(
        "statuschange/list",
        statuschange.list_statuschanges,
        name="list_statuschanges",
    ),
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
