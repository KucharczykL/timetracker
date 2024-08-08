from django.urls import path

from games import purchaseviews, views

urlpatterns = [
    path("", views.index, name="index"),
    path("device/add", views.add_device, name="add_device"),
    path("edition/add", views.add_edition, name="add_edition"),
    path(
        "edition/add/for-game/<int:game_id>",
        views.add_edition,
        name="add_edition_for_game",
    ),
    path("edition/<int:edition_id>/edit", views.edit_edition, name="edit_edition"),
    path("game/add", views.add_game, name="add_game"),
    path("game/<int:game_id>/edit", views.edit_game, name="edit_game"),
    path("game/<int:game_id>/view", views.view_game, name="view_game"),
    path("game/<int:game_id>/delete", views.delete_game, name="delete_game"),
    path("platform/add", views.add_platform, name="add_platform"),
    path("platform/<int:platform_id>/edit", views.edit_platform, name="edit_platform"),
    path("purchase/add", views.add_purchase, name="add_purchase"),
    path("purchase/<int:purchase_id>/edit", views.edit_purchase, name="edit_purchase"),
    path(
        "purchase/<int:purchase_id>/delete",
        views.delete_purchase,
        name="delete_purchase",
    ),
    path(
        "purchase/list",
        purchaseviews.list_purchases,
        name="list_purchases",
    ),
    path(
        "purchase/related-purchase-by-edition",
        views.related_purchase_by_edition,
        name="related_purchase_by_edition",
    ),
    path(
        "purchase/add/for-edition/<int:edition_id>",
        views.add_purchase,
        name="add_purchase_for_edition",
    ),
    path("session/add", views.add_session, name="add_session"),
    path(
        "session/add/for-purchase/<int:purchase_id>",
        views.add_session,
        name="add_session_for_purchase",
    ),
    path(
        "session/add/from-game/<int:session_id>",
        views.new_session_from_existing_session,
        {"template": "view_game.html#session-info"},
        name="view_game_start_session_from_session",
    ),
    path(
        "session/add/from-list/<int:session_id>",
        views.new_session_from_existing_session,
        {"template": "list_sessions.html#session-row"},
        name="list_sessions_start_session_from_session",
    ),
    path("session/<int:session_id>/edit", views.edit_session, name="edit_session"),
    path(
        "session/<int:session_id>/delete",
        views.delete_session,
        name="delete_session",
    ),
    path(
        "session/end/from-game/<int:session_id>",
        views.end_session,
        {"template": "view_game.html#session-info"},
        name="view_game_end_session",
    ),
    path(
        "session/end/from-list/<int:session_id>",
        views.end_session,
        {"template": "list_sessions.html#session-row"},
        name="list_sessions_end_session",
    ),
    path("session/list", views.list_sessions, name="list_sessions"),
    path(
        "session/list/recent",
        views.list_sessions,
        {"filter": "recent"},
        name="list_sessions_recent",
    ),
    path(
        "session/list/by-purchase/<int:purchase_id>",
        views.list_sessions,
        {"filter": "purchase"},
        name="list_sessions_by_purchase",
    ),
    path(
        "session/list/by-platform/<int:platform_id>",
        views.list_sessions,
        {"filter": "platform"},
        name="list_sessions_by_platform",
    ),
    path(
        "session/list/by-game/<int:game_id>",
        views.list_sessions,
        {"filter": "game"},
        name="list_sessions_by_game",
    ),
    path(
        "session/list/by-edition/<int:edition_id>",
        views.list_sessions,
        {"filter": "edition"},
        name="list_sessions_by_edition",
    ),
    path(
        "session/list/by-ownership/<str:ownership_type>",
        views.list_sessions,
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
