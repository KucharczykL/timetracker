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
    StyledButton,
)
from common.layout import render_page
from games.forms import LoginForm


def _login_content(form, request) -> Node:
    return Div(class_="flex items-center flex-col")[
        H2(class_="text-3xl text-white mb-8")["Please log in to continue"],
        Form(
            method="post", class_=f"flex flex-col gap-3 w-full {FORM_MAX_WIDTH_CLASS}"
        )[
            CsrfInput(request),
            FormFields(form),
            StyledButton(type="submit")["Login"],
        ],
    ]


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
