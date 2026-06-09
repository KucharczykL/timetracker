"""Authentication views rendered with the Python layout (replaces
registration/login.html)."""

from django.contrib.auth import views as auth_views
from django.http import HttpResponse
from django.utils.safestring import SafeText, mark_safe

from common.components import Component, CsrfInput, Div, Input
from common.components.primitives import Td, Tr
from common.layout import render_page


def _login_content(form, request) -> SafeText:
    table = Component(
        tag_name="table",
        children=[
            CsrfInput(request),
            mark_safe(str(form.as_table())),
            Tr(
                children=[
                    Td(),
                    Td(
                        children=[
                            Input(type="submit", attributes=[("value", "Login")])
                        ],
                    ),
                ],
            ),
        ],
    )
    return Div(
        [("class", "flex items-center flex-col")],
        [
            Component(
                tag_name="h2",
                attributes=[("class", "text-3xl text-white mb-8")],
                children=["Please log in to continue"],
            ),
            Component(
                tag_name="form",
                attributes=[("method", "post")],
                children=[table],
            ),
        ],
    )


class LoginView(auth_views.LoginView):
    """Django's LoginView, but the page body is built in Python."""

    def render_to_response(self, context, **response_kwargs) -> HttpResponse:
        return render_page(
            self.request,
            _login_content(context["form"], self.request),
            title="Login",
        )
