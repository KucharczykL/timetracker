from django.urls import path

from games.views import device, game, general, platform, purchase, session

urlpatterns = [
    path("", general.index, name="index"),
    path("device/add", device.add_device, name="add_device"),
    path("device/delete/<int:device_id>", device.delete_device, name="delete_device"),
    path("device/edit/<int:device_id>", device.edit_device, name="edit_device"),
    path("device/list", device.list_devices, name="list_devices"),
    path("game/add", game.add_game, name="add_game"),
    path("game/<int:game_id>/edit", game.edit_game, name="edit_game"),
    path("game/<int:game_id>/view", game.view_game, name="view_game"),
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
        "purchase/<int:purchase_id>/refund",
        purchase.refund_purchase,
        name="refund_purchase",
    ),
    path(
        "purchase/related-purchase-by-game",
        purchase.related_purchase_by_game,
        name="related_purchase_by_game",
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
        {"template": "view_game.html#session-info"},
        name="view_game_start_session_from_session",
    ),
    path(
        "session/add/from-list/<int:session_id>",
        session.new_session_from_existing_session,
        {"template": "list_sessions.html#session-row"},
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
        {"template": "view_game.html#session-info"},
        name="view_game_end_session",
    ),
    path(
        "session/end/from-list/<int:session_id>",
        session.end_session,
        {"template": "list_sessions.html#session-row"},
        name="list_sessions_end_session",
    ),
    path("session/list", session.list_sessions, name="list_sessions"),
    path("session/search", session.search_sessions, name="search_sessions"),
    path("stats/", general.stats_alltime, name="stats_alltime"),
    path(
        "stats/<int:year>",
        general.stats,
        name="stats_by_year",
    ),
]
