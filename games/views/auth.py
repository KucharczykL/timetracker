"""Authentication views rendered with the Python layout (replaces
registration/login.html)."""

from django.contrib.auth import views as auth_views
from django.http import HttpResponse

from common.components import (
    FORM_MAX_WIDTH_CLASS,
    CsrfInput,
    Div,
    Form,
    FormFields,
    H2,
    Node,
    ControlButton,
)
from common.layout import render_page
from games.dev_login import prefill_credentials
from games.forms import LoginForm


def _login_content(form, request) -> Node:
    return Div(class_="flex items-center flex-col")[
        H2(class_="text-3xl text-white mb-8")["Please log in to continue"],
        Form(
            method="post",
            class_=f"flex flex-col gap-3 w-full {FORM_MAX_WIDTH_CLASS} @container",
        )[
            CsrfInput(request),
            FormFields(form),
            ControlButton(type="submit")["Login"],
        ],
    ]


class LoginView(auth_views.LoginView):
    """Django's LoginView, but the page body is built in Python and the form is
    our `LoginForm` so its inputs self-style like every other form. When
    DEV_LOGIN_PREFILL is set, the form is pre-typed (dev/staging convenience);
    login still POSTs and authenticates normally."""

    authentication_form = LoginForm

    def get_initial(self) -> dict:
        initial = super().get_initial()
        credentials = prefill_credentials()
        if credentials:
            initial["username"], initial["password"] = credentials
        return initial

    def render_to_response(self, context, **response_kwargs) -> HttpResponse:
        response = render_page(
            self.request,
            _login_content(context["form"], self.request),
            title="Login",
        )
        if prefill_credentials():
            # Credentials are visible in the page HTML; keep the prefilled login
            # page out of search indexes on the public staging box.
            response["X-Robots-Tag"] = "noindex"
        return response
