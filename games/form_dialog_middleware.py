"""A redirect in dialog mode becomes a result."""

import logging
from urllib.parse import urlsplit

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.urls import Resolver404, resolve
from django.utils.cache import patch_vary_headers

from common.components.form_dialog import (
    ContinueAnswer,
    CreatedAnswer,
    DoneAnswer,
    RedirectAnswer,
)
from common.form_dialog import FORM_DIALOG_HEADER, CreatedRedirect, is_form_dialog
from common.notices import toast_payloads
from games.views.returns import READ_ONLY

logger = logging.getLogger(__name__)

type HttpStatus = int  # e.g. 302
type LocationHeader = str  # relative or absolute

#: Redirects that carry a `Location`.
_REDIRECTS: frozenset[HttpStatus] = frozenset({301, 302, 303, 307, 308})


def dialog_result(
    request: HttpRequest, location: LocationHeader
) -> RedirectAnswer | None:
    """`done` on a read-only page; else `continue`.

    `done` consumes the message queue. None off-origin:
    the element then follows the link.
    """
    url = request.build_absolute_uri(location)
    target = urlsplit(url)
    here = urlsplit(request.build_absolute_uri())
    if (target.scheme, target.netloc) != (here.scheme, here.netloc):
        return None
    try:
        view_name = resolve(target.path, urlconf=settings.ROOT_URLCONF).view_name
    except Resolver404:
        view_name = None
    if view_name in READ_ONLY:
        return DoneAnswer(kind="done", url=url, messages=toast_payloads(request))
    return ContinueAnswer(kind="continue", url=url)


def _with_created_row(
    request: HttpRequest, answer: RedirectAnswer | None, response: CreatedRedirect
) -> RedirectAnswer | None:
    """`done` becomes `created`; elsewhere the row drops."""
    if answer is not None and answer["kind"] == "done":
        return CreatedAnswer(
            kind="created",
            url=answer["url"],
            messages=answer["messages"],
            option=response.option,
        )
    logger.warning(
        "%s made row %s, but its redirect to %s hands it to no picker",
        request.path,
        response.option["value"],
        response["Location"],
    )
    return answer


class FormDialogResultMiddleware:
    """Answers a dialog's redirect as JSON."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        if (
            not is_form_dialog(request)
            or response.status_code not in _REDIRECTS
            or "Location" not in response
        ):
            return response
        answer = dialog_result(request, response["Location"])
        if isinstance(response, CreatedRedirect):
            answer = _with_created_row(request, answer, response)
        if answer is None:
            return response
        result = JsonResponse(answer)
        result["Cache-Control"] = "no-store"
        patch_vary_headers(result, (FORM_DIALOG_HEADER,))
        for cookie in response.cookies.values():
            result.cookies[cookie.key] = cookie
        return result
