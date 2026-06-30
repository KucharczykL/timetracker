"""timetracker URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.conf import settings
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from django.views.generic import RedirectView

from games.api import api
from games.views.auth import LoginView

urlpatterns = [
    path("", RedirectView.as_view(url="/tracker")),
    path("api/", api.urls),
    path("login/", LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("tracker/", include("games.urls")),
]

if settings.DEBUG:
    urlpatterns.append(path("admin/", admin.site.urls))
    urlpatterns.append(path("__debug__/", include("debug_toolbar.urls")))

    # DEBUG-only eyeball page for the #189 <filter-group> shell — bare element,
    # no auth/navbar, not linked from nav. Visit /filter-group-demo/ under
    # `make dev`. The route registers only when DEBUG is on, so it cannot leak
    # into production. Assets are resolved through static() so they load under
    # the dev server's /static/ prefix (the element's own module imports resolve
    # relative to its URL). The "Toggle dark" button flips the dark-mode class.
    from django.http import HttpResponse
    from django.templatetags.static import static

    from common.components import FilterGroup

    def filter_group_demo(_request: object) -> HttpResponse:
        stylesheet = static("base.css")
        module = static("js/dist/elements/filter-group.js")
        html = (
            "<!DOCTYPE html><html><head><meta charset='utf-8'>"
            "<title>filter-group demo</title>"
            f'<link rel="stylesheet" href="{stylesheet}">'
            f'<script type="module" src="{module}"></script>'
            "</head><body class='bg-white p-6 dark:bg-gray-900'>"
            '<button type="button" onclick="document.documentElement.classList.toggle(\'dark\')" '
            'class="mb-4 rounded border border-gray-300 px-3 py-1 text-sm '
            'dark:border-gray-600 dark:text-white">Toggle dark</button>'
            f'<div style="max-width:760px">{FilterGroup(model="game")}</div>'
            "</body></html>"
        )
        return HttpResponse(html)

    urlpatterns.append(path("filter-group-demo/", filter_group_demo))
