from django.urls import path

from . import views

urlpatterns = [
    path("", views.index, name="index"),
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
        "list-sessions/by-game/<int:game_id>",
        views.list_sessions,
        {"filter": "game"},
        name="list_sessions_by_game",
    ),
]
