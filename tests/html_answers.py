"""Every HTML answer a test client reads is checked."""

import json
import re

import pytest
from django.http import HttpResponse
from django.test import Client

#: Opening tags of panels a script shows.
FLOATING_PANEL = re.compile(
    r"<(?!dialog\b)[a-z-]+\b[^>]*\b(?:data-menu|data-pop-over-panel)(?=[\s=>])[^>]*>"
)
NATIVE_SELECT = re.compile(r"<select(?=[\s/>])[^>]*>")
#: The settings kit shows the native look.
NATIVE_SELECT_SHOWN_AT = "/tracker/settings-kit-preview/"

type PagePath = str
type Markup = str


def _dialog_page(response: HttpResponse) -> Markup | None:
    """A form dialog's page answer, or none."""
    if "json" not in response.get("Content-Type", ""):
        return None
    answer = json.loads(response.content)
    if isinstance(answer, dict) and answer.get("kind") == "page":
        return answer["html"]
    return None


def _markup(response: HttpResponse, *, dialog: bool) -> Markup | None:
    if getattr(response, "streaming", False):
        return None
    if "html" in response.get("Content-Type", ""):
        return response.content.decode()
    return _dialog_page(response) if dialog else None


def html_answer_faults(
    path: PagePath, response: HttpResponse, *, dialog: bool = False
) -> list[str]:
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


@pytest.fixture(autouse=True, scope="session")
def html_answers_checked():
    """Patch every test client's request."""
    plain_request = Client.request

    def checked_request(self, **request):
        response = plain_request(self, **request)
        path = request.get("PATH_INFO", "")
        dialog = "HTTP_X_FORM_DIALOG" in request
        faults = html_answer_faults(path, response, dialog=dialog)
        assert not faults, f"{path}: {faults[:3]}"
        return response

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(Client, "request", checked_request)
        yield
