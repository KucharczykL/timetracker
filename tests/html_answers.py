"""Every HTML answer a test client reads is checked."""

import json
import re
from typing import Final

import pytest
from django.http import HttpResponse
from django.test import AsyncClient, Client

#: Opening tags of panels a script shows.
FLOATING_PANEL = re.compile(
    r"<(?!dialog\b)[a-z][\w-]*\b[^>]*\b(?:data-menu|data-pop-over-panel)(?=[\s=>])[^>]*>",
    re.IGNORECASE,
)
NATIVE_SELECT = re.compile(r"<select(?=[\s/>])[^>]*>", re.IGNORECASE)

type PagePath = str
type Markup = str
type Fault = str

#: The settings kit shows the native look.
NATIVE_SELECT_SHOWN_AT: Final[PagePath] = "/tracker/settings-kit-preview/"


def _content_type(response: HttpResponse) -> str:
    return response.get("Content-Type", "").lower()


def _dialog_page(response: HttpResponse) -> Markup | None:
    """A form dialog's page answer, or none."""
    if "json" not in _content_type(response):
        return None
    answer = json.loads(response.content)
    if not (isinstance(answer, dict) and answer.get("kind") == "page"):
        return None
    html = answer["html"]
    assert isinstance(html, str), f"a dialog page's html is {type(html).__name__}"
    return html


def _markup(response: HttpResponse, *, dialog: bool) -> Markup | None:
    is_html = "html" in _content_type(response)
    if getattr(response, "streaming", False):
        assert not is_html, "a streamed HTML answer escapes the check"
        return None
    if is_html:
        return response.content.decode()
    return _dialog_page(response) if dialog else None


def html_answer_faults(
    path: PagePath, response: HttpResponse, *, dialog: bool = False
) -> list[Fault]:
    """What an HTML answer must not hold."""
    content = _markup(response, dialog=dialog)
    if content is None:
        return []
    faults = [
        f"floating panel without popover=manual: {tag}"
        for tag in FLOATING_PANEL.findall(content)
        if 'popover="manual"' not in tag
    ]
    if not path.startswith(NATIVE_SELECT_SHOWN_AT):
        faults.extend(f"native select: {tag}" for tag in NATIVE_SELECT.findall(content))
    return faults


def _asks_for_a_dialog(request: dict) -> bool:
    # WSGI environ, or an ASGI scope's header list.
    return "HTTP_X_FORM_DIALOG" in request or any(
        name.lower() == b"x-form-dialog" for name, _ in request.get("headers", ())
    )


def _assert_checked(request: dict, response: HttpResponse) -> None:
    path = request.get("PATH_INFO") or request.get("path", "")
    dialog = _asks_for_a_dialog(request)
    faults = html_answer_faults(path, response, dialog=dialog)
    assert not faults, f"{path}: {faults[:3]}"


@pytest.fixture(autouse=True, scope="session")
def html_answers_checked():
    """Patch every test client's request."""
    plain_request = Client.request
    plain_async_request = AsyncClient.request

    def checked_request(self, **request):
        response = plain_request(self, **request)
        _assert_checked(request, response)
        return response

    async def checked_async_request(self, **request):
        response = await plain_async_request(self, **request)
        _assert_checked(request, response)
        return response

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(Client, "request", checked_request)
        patch.setattr(AsyncClient, "request", checked_async_request)
        yield
