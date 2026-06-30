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

from common.components.core import Document
from common.components.primitives import (
    Body,
    Head,
    Html,
    Link,
    Meta,
    Script,
    StyledButton,
    Title,
)
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

    from common.components import FilterFieldPicker, FilterGroup
    from common.components.core import Safe
    from games.filters import GameFilter

    # Inline ES module: log the picked field's reset leaf so the field picker
    # (#191) can be eyeballed standalone. Scoped to the [data-field-picker] marker
    # so it never trips on another <search-select> on the page.
    _picker_demo_script = (
        "import { parseFieldMeta, criterionForField } from "
        "'/static/js/dist/elements/filter-tree/operations.js';\n"
        "document.querySelector('[data-field-picker]')"
        ".addEventListener('search-select:change', (event) => {\n"
        "  const meta = parseFieldMeta(event.detail.last?.data?.meta ?? '');\n"
        "  if (meta) console.log('field-picker →', criterionForField(meta));\n"
        "});"
    )

    def filter_group_demo(_request: object) -> HttpResponse:
        page = Document(
            Html(lang="en")[
                Head()[
                    Title()["filter-group demo"],
                    Meta(charset="utf-8"),
                    Link(rel="stylesheet", href=static("base.css")),
                    Script(
                        type="module", src=static("js/dist/elements/filter-group.js")
                    ),
                    Script(
                        type="module", src=static("js/dist/elements/search-select.js")
                    ),
                ],
                Body(class_="bg-body p-6 dark:bg-gray-900")[
                    StyledButton(
                        onclick="document.documentElement.classList.toggle('dark')"
                    )["Toggle dark"],
                    FilterGroup(model="game"),
                    FilterFieldPicker(GameFilter, id="id_field_picker"),
                    Script(type="module")[Safe(_picker_demo_script)],
                ],
            ]
        )
        return HttpResponse(page)

    urlpatterns.append(path("filter-group-demo/", filter_group_demo))
