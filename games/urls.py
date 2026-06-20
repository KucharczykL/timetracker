from django.urls import path

from games.views import (
    device,
    filter_presets,
    game,
    general,
    platform,
    playevent,
    purchase,
    session,
    statuschange,
)

app_name = "games"

urlpatterns = [
    path("", general.index, name="index"),
    path("device/add", device.add_device, name="add_device"),
    path("device/delete/<int:device_id>", device.delete_device, name="delete_device"),
    path("device/edit/<int:device_id>", device.edit_device, name="edit_device"),
    path("device/list", device.list_devices, name="list_devices"),
    path("game/add", game.add_game, name="add_game"),
    path("game/<int:game_id>/edit", game.edit_game, name="edit_game"),
    path("game/<int:game_id>/view", game.view_game, name="view_game"),
    path(
        "game/<int:game_id>/delete/confirm",
        game.delete_game_confirmation,
        name="delete_game_confirmation",
    ),
    path("game/<int:game_id>/delete", game.delete_game, name="delete_game"),
    path("game/list", game.list_games, name="list_games"),
    path("platform/add", platform.add_platform, name="add_platform"),
    path(
        "platform/<int:platform_id>/edit",
        platform.edit_platform,
        name="edit_platform",
    ),
    path(
        "platform/<int:platform_id>/delete",
        platform.delete_platform,
        name="delete_platform",
    ),
    path("platform/list", platform.list_platforms, name="list_platforms"),
    path("playevent/list", playevent.list_playevents, name="list_playevents"),
    path("playevent/add", playevent.add_playevent, name="add_playevent"),
    path(
        "playevent/add/for-game/<int:game_id>",
        playevent.add_playevent,
        name="add_playevent_for_game",
    ),
    path(
        "playevent/edit/<int:playevent_id>",
        playevent.edit_playevent,
        name="edit_playevent",
    ),
    path(
        "playevent/delete/<int:playevent_id>",
        playevent.delete_playevent,
        name="delete_playevent",
    ),
    path("purchase/add", purchase.add_purchase, name="add_purchase"),
    path(
        "purchase/add/for-game/<int:game_id>",
        purchase.add_purchase,
        name="add_purchase_for_game",
    ),
    path(
        "purchase/<int:purchase_id>/edit",
        purchase.edit_purchase,
        name="edit_purchase",
    ),
    path(
        "purchase/<int:purchase_id>/drop",
        purchase.drop_purchase,
        name="drop_purchase",
    ),
    path(
        "purchase/<int:purchase_id>/delete",
        purchase.delete_purchase,
        name="delete_purchase",
    ),
    path(
        "purchase/<int:purchase_id>/view",
        purchase.view_purchase,
        name="view_purchase",
    ),
    path(
        "purchase/<int:purchase_id>/finish",
        purchase.finish_purchase,
        name="finish_purchase",
    ),
    path(
        "purchase/list",
        purchase.list_purchases,
        name="list_purchases",
    ),
    path(
        "purchase/<int:purchase_id>/refund/confirm",
        purchase.refund_purchase_confirmation,
        name="refund_purchase_confirmation",
    ),
    path(
        "purchase/<int:purchase_id>/refund",
        purchase.refund_purchase,
        name="refund_purchase",
    ),
    path(
        "purchase/<int:purchase_id>/split/confirm",
        purchase.split_purchase_confirmation,
        name="split_purchase_confirmation",
    ),
    path(
        "purchase/<int:purchase_id>/split",
        purchase.split_purchase,
        name="split_purchase",
    ),
    path("session/add", session.add_session, name="add_session"),
    path(
        "session/add/for-game/<int:game_id>",
        session.add_session,
        name="add_session_for_game",
    ),
    path(
        "session/add/from-game/<int:session_id>",
        session.new_session_from_existing_session,
        name="view_game_start_session_from_session",
    ),
    path(
        "session/add/from-list/<int:session_id>",
        session.new_session_from_existing_session,
        name="list_sessions_start_session_from_session",
    ),
    path("session/<int:session_id>/edit", session.edit_session, name="edit_session"),
    path(
        "session/<int:session_id>/delete",
        session.delete_session,
        name="delete_session",
    ),
    path(
        "session/end/from-game/<int:session_id>",
        session.end_session,
        name="view_game_end_session",
    ),
    path(
        "session/end/from-list/<int:session_id>",
        session.end_session,
        name="list_sessions_end_session",
    ),
    path(
        "session/start/reset-to-now/from-list/<int:session_id>",
        session.reset_session_start,
        name="list_sessions_reset_session_start",
    ),
    path("session/list", session.list_sessions, name="list_sessions"),
    path("session/search", session.search_sessions, name="search_sessions"),
    path(
        "statuschange/add",
        statuschange.add_statuschange,
        name="add_statuschange",
    ),
    path(
        "statuschange/edit/<int:statuschange_id>",
        statuschange.edit_statuschange,
        name="edit_statuschange",
    ),
    path(
        "statuschange/delete/<int:pk>",
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
    # Filter presets
    path("filter/presets/list", filter_presets.list_presets, name="list_presets"),
    path("filter/presets/save", filter_presets.save_preset, name="save_preset"),
    path(
        "filter/presets/<int:preset_id>/delete",
        filter_presets.delete_preset,
        name="delete_preset",
    ),
    path(
        "filter/presets/<int:preset_id>/load",
        filter_presets.load_preset,
        name="load_preset",
    ),
]
