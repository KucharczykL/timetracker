"""Shared error boundary for attacker-controllable ``?filter=`` input.

The list views parse a structured Stash-style filter from the ``?filter=`` query
parameter, a value any logged-in user can hand-edit. ``filter_from_json`` (and
the ``parse_*_filter`` wrappers in ``games/filters.py``) now raise ``FilterError``
on a malformed or semantically-invalid filter instead of letting a ``ValueError``
500 the page. This helper is the single place each list view routes that through,
mirroring the unknown-sort-field UX: drop the bad filter, warn, render unfiltered.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from django.contrib import messages
from django.http import HttpRequest

from common.criteria import FilterError, FilterType

logger = logging.getLogger("games")


def apply_structured_filter(
    request: HttpRequest,
    parse: Callable[[str], FilterType | None],
    filter_json: str,
) -> FilterType | None:
    """Parse + validate a ``?filter=`` blob; warn-and-ignore invalid input.

    Returns a fully-renderable filter (its ``to_q()`` cannot raise — eager
    validation happened at parse time) or ``None`` when there is no filter or the
    filter is invalid. On invalid input a ``messages.warning`` is queued, matching
    the existing unknown-sort-field treatment, so the page still renders the
    unfiltered list.

    SECURITY: returning ``None`` makes a bad filter fail *open* — the view drops
    the filter and renders the full list. This is safe **only** because the user
    filter is AND-composed onto a base queryset and can therefore only *narrow*
    it: any authorization scoping (e.g. ``owner=request.user``) must live on that
    base queryset, applied server-side, and must **never** be carried in the
    attacker-controllable ``?filter=`` payload. If an ownership constraint were
    ever expressed through the filter, dropping it here would leak other users'
    rows. Keep scoping out of the filter, or this fail-open becomes a fail-leak.
    """
    if not filter_json:
        return None
    try:
        return parse(filter_json)
    except FilterError as exc:
        entity = parse.__name__.removeprefix("parse_").removesuffix("_filter")
        logger.warning(
            "rejected invalid filter (entity=%s, user=%s, path=%s): %s",
            entity,
            request.user,
            request.path,
            exc,
        )
        messages.warning(request, f"Ignored invalid filter: {exc}")
        return None
