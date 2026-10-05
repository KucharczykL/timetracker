"""A redirect in dialog mode becomes a result."""

from urllib.parse import urlsplit

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.urls import Resolver404, resolve
from django.utils.cache import patch_vary_headers

from common.components.form_dialog import ContinueAnswer, DoneAnswer
from common.form_dialog import FORM_DIALOG_HEADER, is_form_dialog
from common.notices import toast_payloads
from games.views.returns import READ_ONLY

#: Redirects that carry a `Location`.
_REDIRECTS = frozenset({301, 302, 303, 307, 308})


def dialog_result(
    request: HttpRequest, location: str
) -> DoneAnswer | ContinueAnswer | None:
    """`done` on a read-only page; else `continue`.

    None off-origin: the browser follows it.
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
        if answer is None:
            return response
        result = JsonResponse(answer)
        result["Cache-Control"] = "no-store"
        patch_vary_headers(result, (FORM_DIALOG_HEADER,))
        for cookie in response.cookies.values():
            result.cookies[cookie.key] = cookie
        return result
