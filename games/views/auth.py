"""Authentication views rendered with the Python layout (replaces
registration/login.html)."""

from django.contrib.auth import views as auth_views
from django.http import HttpResponse

from common.components import (
    CONTENT_MAX_WIDTH_CLASS,
    CsrfInput,
    Div,
    Element,
    FormFields,
    Node,
    StyledButton,
)
from common.layout import render_page
from games.forms import LoginForm


def _login_content(form, request) -> Node:
    return Div(
        [("class", "flex items-center flex-col")],
        [
            Element(
                "h2",
                attributes=[("class", "text-3xl text-white mb-8")],
                children=["Please log in to continue"],
            ),
            Element(
                "form",
                attributes=[
                    ("method", "post"),
                    ("class", f"flex flex-col gap-3 w-full {CONTENT_MAX_WIDTH_CLASS}"),
                ],
                children=[
                    CsrfInput(request),
                    FormFields(form),
                    StyledButton([], "Login", type="submit"),
                ],
            ),
        ],
    )


class LoginView(auth_views.LoginView):
    """Django's LoginView, but the page body is built in Python and the form is
    our `LoginForm` so its inputs self-style like every other form."""

    authentication_form = LoginForm

    def render_to_response(self, context, **response_kwargs) -> HttpResponse:
        return render_page(
            self.request,
            _login_content(context["form"], self.request),
            title="Login",
        )
