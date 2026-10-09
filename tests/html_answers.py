"""Every HTML answer a test client reads is checked."""

import json
import re
from html.parser import HTMLParser
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
#: Dropdown sheet attribute; not the behavior's.
DROPDOWN_SHEET_ATTRIBUTE: Final = "data-dropdown-sheet"
SHEET_BEHAVIOR: Final = "sheet"

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


class _OpenDropdown:
    """A ``<drop-down>`` open while parsing."""

    def __init__(self, behavior: str, label: str) -> None:
        self.behavior = behavior
        self.label = label
        self.owns_sheet = False


class _SheetOwners(HTMLParser):
    """Each ``<drop-down>``; whether it owns a sheet."""

    def __init__(self) -> None:
        super().__init__()
        self.open: list[_OpenDropdown] = []
        self.sheetless: list[_OpenDropdown] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        named = {name: value or "" for name, value in attrs}
        if tag == "drop-down":
            self.open.append(
                _OpenDropdown(named.get("behavior", ""), named.get("aria-label", ""))
            )
        elif tag == "dialog" and DROPDOWN_SHEET_ATTRIBUTE in named and self.open:
            #: Innermost open drop-down owns the sheet.
            self.open[-1].owns_sheet = True
        elif tag != "drop-down" and self.open and not self.open[-1].label:
            #: Trigger names the dropdown.
            self.open[-1].label = named.get("aria-label", "")

    def handle_endtag(self, tag: str) -> None:
        if tag == "drop-down" and self.open:
            dropdown = self.open.pop()
            if dropdown.behavior != SHEET_BEHAVIOR and not dropdown.owns_sheet:
                self.sheetless.append(dropdown)


def sheetless_dropdown_faults(content: Markup) -> list[Fault]:
    """Each ``<drop-down>`` lacking its own sheet."""
    owners = _SheetOwners()
    owners.feed(content)
    owners.close()
    return [
        f"drop-down without its own sheet: behavior={dropdown.behavior!r}, "
        f"aria-label={dropdown.label!r}"
        for dropdown in owners.sheetless
    ]


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
    faults.extend(sheetless_dropdown_faults(content))
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
