from django.urls import path

from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("add-game/", views.add_game, name="add_game"),
    path("add-platform/", views.add_platform, name="add_platform"),
    path("add-session/", views.add_session, name="add_session"),
    path("add-purchase/", views.add_purchase, name="add_purchase"),
    path("list-sessions/", views.list_sessions, name="list_sessions"),
    path(
        "list-sessions/by-purchase/<int:purchase_id>",
        views.list_sessions,
        name="list_sessions",
    ),
]
