"""Shared error boundary for attacker-controllable ``?filter=`` input.

The list views parse a structured Stash-style filter from the ``?filter=`` query
parameter, a value any logged-in user can hand-edit. ``filter_from_json`` (and
the ``parse_*_filter`` wrappers in ``games/filters.py``) now raise ``FilterError``
on a malformed or semantically-invalid filter instead of letting a ``ValueError``
500 the page. This helper is the single place each list view routes that through,
mirroring the unknown-sort-field UX: drop the bad filter, warn, render unfiltered.
"""

import logging
from collections.abc import Callable
from urllib.parse import quote

from django.contrib import messages
from django.http import HttpRequest
from django.urls import reverse

from common.components.custom_elements import FILTER_MODE_MODELS, FilterMode
from common.criteria import FilterError, OperatorFilter
from games.sorting import SortKey

logger = logging.getLogger("games")


# The modes whose model has a nested-builder page (games:filter_builder) — every
# filterable mode (#336). general.py derives the builder's model->mode table from
# this set + FILTER_MODE_MODELS.
BUILDER_MODES = frozenset(
    {"games", "sessions", "purchases", "playevents", "devices", "platforms"}
)


def builder_url_for(
    mode: FilterMode,
    filter_json: str,
    sort: str | None = None,
    per_page: int | None = None,
) -> str:
    """Build a filter-builder URL with persistent list state.

    ``None`` page size inherits; ``0`` is explicit. Page number is transient.
    """
    if mode not in BUILDER_MODES:
        raise LookupError(f"mode {mode!r} has no filter-builder page")
    url = reverse("games:filter_builder", args=[FILTER_MODE_MODELS[mode]])
    params: list[str] = []
    if filter_json:
        params.append(f"filter={quote(filter_json)}")
    if sort:
        params.append(f"sort={quote(sort)}")
    if per_page is not None:
        params.append(f"per_page={per_page}")
    if params:
        url = f"{url}?{'&'.join(params)}"
    return url


def apply_structured_filter[F: OperatorFilter](
    request: HttpRequest,
    parse: Callable[[str], F | None],
    filter_json: str,
) -> F | None:
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


def warn_unknown_sort(
    request: HttpRequest, unknown: list[SortKey], *, entity: str
) -> None:
    """Log + toast unknown ``?sort=`` keys, mirroring ``apply_structured_filter``.

    ``?sort=`` is attacker-controllable like ``?filter=``; each unknown key is
    dropped and the queryset orders by whatever valid keys remain (falling back to
    the trusted default sort only when none remain). A warning is both logged on
    the ``games`` logger — so operators can spot probing — and queued as a
    user-facing toast. ``entity`` is the singular noun
    (``"game"``/``"session"``/``"purchase"``), matching the filter log convention.

    The keys are ``repr()``-ed in the log message: they are raw user input and
    ``parse_sort_terms`` only strips outer whitespace, so an embedded newline would
    otherwise forge log lines (CWE-117).
    """
    if not unknown:
        return
    logger.warning(
        "rejected unknown sort field(s) (entity=%s, user=%s, path=%s): %s",
        entity,
        request.user,
        request.path,
        ", ".join(repr(key) for key in unknown),
    )
    for key in unknown:
        messages.warning(request, f"Unknown sort field '{key}' was ignored.")
