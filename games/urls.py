from django.urls import path

from games import (
    deviceviews,
    editionviews,
    gameviews,
    platformviews,
    purchaseviews,
    sessionviews,
    views,
)

urlpatterns = [
    path("", views.index, name="index"),
    path("device/add", deviceviews.add_device, name="add_device"),
    path(
        "device/delete/<int:device_id>", deviceviews.delete_device, name="delete_device"
    ),
    path("device/edit/<int:device_id>", deviceviews.edit_device, name="edit_device"),
    path("device/list", deviceviews.list_devices, name="list_devices"),
    path("edition/add", editionviews.add_edition, name="add_edition"),
    path(
        "edition/add/for-game/<int:game_id>",
        editionviews.add_edition,
        name="add_edition_for_game",
    ),
    path(
        "edition/<int:edition_id>/edit", editionviews.edit_edition, name="edit_edition"
    ),
    path("edition/list", editionviews.list_editions, name="list_editions"),
    path(
        "edition/<int:edition_id>/delete",
        editionviews.delete_edition,
        name="delete_edition",
    ),
    path("game/add", gameviews.add_game, name="add_game"),
    path("game/<int:game_id>/edit", gameviews.edit_game, name="edit_game"),
    path("game/<int:game_id>/view", gameviews.view_game, name="view_game"),
    path("game/<int:game_id>/delete", gameviews.delete_game, name="delete_game"),
    path("game/list", gameviews.list_games, name="list_games"),
    path("platform/add", platformviews.add_platform, name="add_platform"),
    path(
        "platform/<int:platform_id>/edit",
        platformviews.edit_platform,
        name="edit_platform",
    ),
    path(
        "platform/<int:platform_id>/delete",
        platformviews.delete_platform,
        name="delete_platform",
    ),
    path("platform/list", platformviews.list_platforms, name="list_platforms"),
    path("purchase/add", purchaseviews.add_purchase, name="add_purchase"),
    path(
        "purchase/<int:purchase_id>/edit",
        purchaseviews.edit_purchase,
        name="edit_purchase",
    ),
    path(
        "purchase/<int:purchase_id>/delete",
        purchaseviews.delete_purchase,
        name="delete_purchase",
    ),
    path(
        "purchase/list",
        purchaseviews.list_purchases,
        name="list_purchases",
    ),
    path(
        "purchase/related-purchase-by-edition",
        purchaseviews.related_purchase_by_edition,
        name="related_purchase_by_edition",
    ),
    path(
        "purchase/add/for-edition/<int:edition_id>",
        purchaseviews.add_purchase,
        name="add_purchase_for_edition",
    ),
    path("session/add", sessionviews.add_session, name="add_session"),
    path(
        "session/add/for-purchase/<int:purchase_id>",
        sessionviews.add_session,
        name="add_session_for_purchase",
    ),
    path(
        "session/add/from-game/<int:session_id>",
        sessionviews.new_session_from_existing_session,
        {"template": "view_game.html#session-info"},
        name="view_game_start_session_from_session",
    ),
    path(
        "session/add/from-list/<int:session_id>",
        sessionviews.new_session_from_existing_session,
        {"template": "list_sessions.html#session-row"},
        name="list_sessions_start_session_from_session",
    ),
    path(
        "session/<int:session_id>/edit", sessionviews.edit_session, name="edit_session"
    ),
    path(
        "session/<int:session_id>/delete",
        sessionviews.delete_session,
        name="delete_session",
    ),
    path(
        "session/end/from-game/<int:session_id>",
        sessionviews.end_session,
        {"template": "view_game.html#session-info"},
        name="view_game_end_session",
    ),
    path(
        "session/end/from-list/<int:session_id>",
        sessionviews.end_session,
        {"template": "list_sessions.html#session-row"},
        name="list_sessions_end_session",
    ),
    path("session/list", sessionviews.list_sessions, name="list_sessions"),
    path(
        "session/list/by-purchase/<int:purchase_id>",
        sessionviews.list_sessions,
        {"filter": "purchase"},
        name="list_sessions_by_purchase",
    ),
    path(
        "session/list/by-platform/<int:platform_id>",
        sessionviews.list_sessions,
        {"filter": "platform"},
        name="list_sessions_by_platform",
    ),
    path(
        "session/list/by-game/<int:game_id>",
        sessionviews.list_sessions,
        {"filter": "game"},
        name="list_sessions_by_game",
    ),
    path(
        "session/list/by-edition/<int:edition_id>",
        sessionviews.list_sessions,
        {"filter": "edition"},
        name="list_sessions_by_edition",
    ),
    path(
        "session/list/by-ownership/<str:ownership_type>",
        sessionviews.list_sessions,
        {"filter": "ownership_type"},
        name="list_sessions_by_ownership_type",
    ),
    path("stats/", views.stats_alltime, name="stats_alltime"),
    path(
        "stats/<int:year>",
        views.stats,
        name="stats_by_year",
    ),
]
