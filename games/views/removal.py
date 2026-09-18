"""One confirm-then-act flow: GET renders the confirmation, POST performs it.

Both live on the same URL, so the ``?origin=`` value rides through the
confirmation into the POST with nothing to thread by hand.

Removing is the common case and keeps its own wrapper, but the flow itself is
indifferent to what the POST does — reset uses it too.
"""

from collections.abc import Callable, Sequence
from functools import partial
from typing import Any, NamedTuple

from django.contrib import messages
from django.db.models import Model
from django.http import HttpRequest, HttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import redirect
from django.urls import reverse

from common.components import ConfirmPage
from common.components.core import Children
from common.layout import render_page
from common.notices import ToastAction, Undo, notify
from common.returns import UrlName
from games.events.dispatch import CommandOutcome, CommandResult
from games.removal import remove
from games.views.returns import return_url
from games.writes.answers import CONFLICT_STATUS, DEFECT_STATUS, CommandFailed


class UndoOffer(NamedTuple):
    """What the Undo toast says and where it posts."""

    sentence: str
    route: UrlName
    args: Sequence[Any] = ()


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
    undo: UndoOffer | None = None,
) -> HttpResponse:
    """Confirm on GET, run ``action`` on POST, then return to the origin.

    ``reject`` names a page the action invalidates — the acted-on object's own
    detail page, say — so an origin pointing there is refused rather than
    followed into a 404.

    An ``action`` that refuses raises ``CommandFailed``, and its sentence goes
    back on the confirmation, above the question rather than inside it. Only
    that type reads as a refusal; anything beneath the act is a defect.

    ``undo`` makes the answer a toast with Undo.
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
                #: A defect admits no second press.
                confirm_label=None if status == DEFECT_STATUS else confirm_label,
            ),
            title=title,
            status=status,
        )

    if request.method != "POST":
        return confirmation()
    try:
        action()
    except CommandFailed as refusal:
        #: The refusal's status: stale page 409, defect 500.
        return confirmation([refusal.message], status=refusal.status_code)
    if undo is not None:
        notify(
            request,
            undo.sentence,
            level=messages.SUCCESS,
            action=Undo(reverse(undo.route, args=list(undo.args))),
        )
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
    removed: str,
    undo: UrlName,
) -> HttpResponse:
    """Confirm on GET, remove on POST, return with Undo.

    ``detail_url`` is the removed row's own page: an origin naming it
    would turn a successful removal into a 404, so it is refused.

    ``action`` is for a record whose removal is more than a stamp: a
    game states a fact to its projection first.

    ``removed`` and ``undo``: the Undo toast's sentence and route.
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
        undo=UndoOffer(removed, undo, [instance.pk]),
    )


def restore_and_return(
    request: HttpRequest,
    *,
    action: Callable[[], CommandResult | None],
    restored: str,
    fallback: UrlName,
    fallback_args: Sequence[Any] = (),
    retry: bool = False,
    unchanged: str | None = None,
) -> HttpResponse:
    """Run ``action``, say so, return; a refusal is an error message.

    ``retry`` puts a "Try again" action on that message, posting to
    this same route: for a restore whose halfway a second press ends.
    A defect admits no second press.

    ``unchanged`` replaces ``restored`` when nothing was appended.
    """
    try:
        answer = action()
    except CommandFailed as refusal:
        offered = retry and refusal.status_code == CONFLICT_STATUS
        notify(
            request,
            refusal.message,
            level=messages.ERROR,
            action=ToastAction(label="Try again", url=request.path)
            if offered
            else None,
        )
    else:
        if (
            unchanged is not None
            and answer is not None
            and answer.outcome is CommandOutcome.UNCHANGED
        ):
            messages.info(request, unchanged)
        else:
            messages.success(request, restored)
    return redirect(return_url(request, fallback=fallback, fallback_args=fallback_args))
