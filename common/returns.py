"""Carrying the page a mutating action was launched from, and coming back to it.

The origin rides the query string and nowhere else — not the session, not a
form body — so it survives GET->POST (forms without an ``action`` re-post to the
current full path), multiple tabs, and bookmarking.

The parameter is ``origin`` rather than ``next`` because Django's auth views own
``next``: on /login/ it means "where to go after authenticating", and a mutating
view has no way to tell that apart from "where to go after this mutation".
"""

from collections.abc import Container
from typing import Any
from urllib.parse import urlencode, urlparse, urlunparse

from django.http import HttpRequest
from django.urls import Resolver404, resolve, reverse
from django.utils.http import url_has_allowed_host_and_scheme

type OriginUrl = str  # "/tracker/game/list?filter=%7B%22status%22%3A%5B%22p%22%5D%7D"
type UrlName = str  # "games:edit_game"

ORIGIN_PARAM = "origin"


def action_url(
    viewname: UrlName, *args: Any, origin: OriginUrl | None, **kwargs: Any
) -> str:
    """Link to a mutating view, carrying the page it is launched from.

    ``origin`` is keyword-only and has no default so a call site cannot drop it
    by accident; pass ``None`` only where there is genuinely nowhere to return.
    """
    url = reverse(viewname, args=args, kwargs=kwargs)
    if not origin:
        return url
    # reverse() never yields a query string, so "?" is unconditional.
    return f"{url}?{urlencode({ORIGIN_PARAM: origin})}"


def parse_origin(
    request: HttpRequest,
    *,
    returnable: Container[UrlName],
    reject: str | None = None,
) -> OriginUrl | None:
    """The origin this request carries, or None if absent or untrustworthy.

    ``returnable`` is the set of url names a user may be sent back to — read-only
    pages. Accepting any resolvable path instead would let a crafted origin turn
    the user's confirming POST into a server-issued GET redirect that mutates
    again, and would happily redirect a finished mutation at a JSON endpoint or
    the POST-only logout route.

    ``reject`` drops an origin naming a page that is about to stop existing — a
    delete view passes the detail URL of the object it is deleting. This narrows
    the 404-after-delete window but cannot close it: resolve() proves the route
    exists, never the object.
    """
    candidate = request.GET.get(ORIGIN_PARAM)
    if not candidate:
        return None
    # allowed_hosts=None admits root-relative URLs only, which also turns away
    # "//evil.example" and every non-http scheme.
    if not url_has_allowed_host_and_scheme(candidate, allowed_hosts=None):
        return None
    # Django validated the stripped form; anything else would smuggle control
    # characters into a Location header and 500 after the mutation committed.
    parts = urlparse(candidate.strip())
    # PATH_INFO, which is what resolve() wants. Identical to get_full_path()'s
    # path here because the /tracker prefix comes from the urlconf rather than
    # FORCE_SCRIPT_NAME; a sub-path deployment would need to strip SCRIPT_NAME.
    try:
        match = resolve(parts.path)
    except Resolver404:
        return None
    if f"{match.app_name}:{match.url_name}" not in returnable:
        return None
    if reject is not None and parts.path == reject:
        return None
    return urlunparse(parts)
