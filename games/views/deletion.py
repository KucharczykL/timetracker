"""One delete flow: GET renders the confirmation, POST performs the delete.

Both live on the same URL, so the ``?origin=`` value rides through the
confirmation into the POST with nothing to thread by hand.
"""

from collections.abc import Sequence
from typing import Any

from django.db.models import Model
from django.http import HttpRequest, HttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import redirect

from common.components import ConfirmPage
from common.components.core import Children
from common.layout import render_page
from common.returns import UrlName
from games.views.returns import return_url


def confirm_and_delete(
    request: HttpRequest,
    instance: Model,
    *,
    title: str,
    message: str,
    fallback: UrlName,
    fallback_args: Sequence[Any] = (),
    details: Children = None,
    detail_url: str | None = None,
) -> HttpResponse:
    """Confirm on GET, delete on POST, then return to the origin.

    ``detail_url`` is the deleted object's own page: an origin naming it would
    turn a successful delete into a 404, so it is refused.
    """
    if request.method != "POST":
        return render_page(
            request,
            ConfirmPage(
                title=title,
                message=message,
                details=details,
                post_url=request.get_full_path(),
                csrf_token=get_token(request),
                cancel_url=return_url(
                    request, fallback=fallback, fallback_args=fallback_args
                ),
                confirm_label="Delete",
            ),
            title=title,
        )
    instance.delete()
    return redirect(
        return_url(
            request,
            fallback=fallback,
            fallback_args=fallback_args,
            reject=detail_url,
        )
    )
