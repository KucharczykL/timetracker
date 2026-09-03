"""One confirm-then-act flow: GET renders the confirmation, POST performs it.

Both live on the same URL, so the ``?origin=`` value rides through the
confirmation into the POST with nothing to thread by hand.

Removing is the common case and keeps its own wrapper, but the flow itself is
indifferent to what the POST does — reset uses it too.
"""

from collections.abc import Callable, Sequence
from functools import partial
from typing import Any

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
from games.writes.answers import CommandFailed


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

    An ``action`` that refuses raises ``CommandFailed``, and its sentence goes
    back on the confirmation, above the question rather than inside it. Only
    that type is read as a refusal: a ``ValidationError`` from a model beneath
    the act is a defect, and it rises to the 500 handler where one belongs.
    """

    def confirmation(refusal: Sequence[str] = (), status: int = 200) -> HttpResponse:
        return render_page(
            request,
            ConfirmPage(
                title=title,
                message=message,
                refusal=refusal,
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
    except CommandFailed as refusal:
        #: A command refuses on state, and state moves: another tab
        #: may have taken the row this act counted on. A 500 would
        #: read as our fault rather than as a stale page. The status
        #: is the refusal's own, because the answers disagree about
        #: what a person should do next.
        return confirmation([refusal.message], status=refusal.status_code)
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
