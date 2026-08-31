"""One confirm-then-act flow: GET renders the confirmation, POST performs it.

Both live on the same URL, so the ``?origin=`` value rides through the
confirmation into the POST with nothing to thread by hand.

Removing is the common case and keeps its own wrapper, but the flow itself is
indifferent to what the POST does — reset uses it too.
"""

from collections.abc import Callable, Sequence
from functools import partial
from typing import Any

from django.core.exceptions import ValidationError
from django.db.models import Model
from django.http import HttpRequest, HttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import redirect

from common.components import ConfirmPage
from common.components.core import Children
from common.layout import render_page
from common.returns import UrlName
from games.removal import remove
from games.views.returns import return_url


def confirm_and_apply(
    request: HttpRequest,
    *,
    #: `object`, because the return is discarded.
    action: Callable[[], object],
    title: str,
    message: str,
    confirm_label: str,
    fallback: UrlName,
    fallback_args: Sequence[Any] = (),
    details: Children = None,
    reject: str | None = None,
) -> HttpResponse:
    """Confirm on GET, run ``action`` on POST, then return to the origin.

    ``reject`` names a page the action invalidates — the acted-on object's own
    detail page, say — so an origin pointing there is refused rather than
    followed into a 404.

    An ``action`` that refuses puts its sentence back on the confirmation.
    """

    def confirmation(refusal: str = "", status: int = 200) -> HttpResponse:
        return render_page(
            request,
            ConfirmPage(
                title=title,
                message=f"{refusal} {message}" if refusal else message,
                details=details,
                post_url=request.get_full_path(),
                csrf_token=get_token(request),
                cancel_url=return_url(
                    request, fallback=fallback, fallback_args=fallback_args
                ),
                confirm_label=confirm_label,
            ),
            title=title,
            status=status,
        )

    if request.method != "POST":
        return confirmation()
    try:
        action()
    except ValidationError as refusal:
        #: The service refuses on state, and state moves: another tab
        #: may have taken the sibling this removal counted on. A 500
        #: would read as our fault rather than as a stale page.
        return confirmation(refusal.messages[0], status=409)
    return redirect(
        return_url(
            request,
            fallback=fallback,
            fallback_args=fallback_args,
            reject=reject,
        )
    )


def confirm_and_remove(
    request: HttpRequest,
    instance: Model,
    *,
    title: str,
    message: str,
    fallback: UrlName,
    fallback_args: Sequence[Any] = (),
    details: Children = None,
    detail_url: str | None = None,
    action: Callable[[], object] | None = None,
) -> HttpResponse:
    """Confirm on GET, remove on POST, return.

    ``detail_url`` is the removed row's own page: an origin naming it
    would turn a successful removal into a 404, so it is refused.

    ``action`` is for a record whose removal is more than a stamp: a
    game states a fact to its projection first.
    """
    return confirm_and_apply(
        request,
        action=action or partial(remove, instance),
        title=title,
        message=message,
        confirm_label="Remove",
        fallback=fallback,
        fallback_args=fallback_args,
        details=details,
        reject=detail_url,
    )
