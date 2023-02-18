from django.urls import path

from games import views

urlpatterns = [
    path("", views.index, name="index"),
    path(
        "list-sessions/recent",
        views.list_sessions,
        {"filter": "recent"},
        name="list_sessions_recent",
    ),
    path("add-game/", views.add_game, name="add_game"),
    path("add-platform/", views.add_platform, name="add_platform"),
    path("add-session/", views.add_session, name="add_session"),
    path(
        "update-session/by-session/<int:session_id>",
        views.update_session,
        name="update_session",
    ),
    path(
        "start-session/<int:purchase_id>",
        views.start_session,
        name="start_session",
    ),
    path(
        "delete_session/by-id/<int:session_id>",
        views.delete_session,
        name="delete_session",
    ),
    path("add-purchase/", views.add_purchase, name="add_purchase"),
    path("add-edition/", views.add_edition, name="add_edition"),
    path("edit-session/<int:session_id>", views.edit_session, name="edit_session"),
    path("list-sessions/", views.list_sessions, name="list_sessions"),
    path(
        "list-sessions/by-purchase/<int:purchase_id>",
        views.list_sessions,
        {"filter": "purchase"},
        name="list_sessions_by_purchase",
    ),
    path(
        "list-sessions/by-platform/<int:platform_id>",
        views.list_sessions,
        {"filter": "platform"},
        name="list_sessions_by_platform",
    ),
    path(
        "list-sessions/by-edition/<int:edition_id>",
        views.list_sessions,
        {"filter": "edition"},
        name="list_sessions_by_edition",
    ),
]
