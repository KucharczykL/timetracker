"""Which routes mutate, how each answers when it is done, and where a user may
be sent back to.

tests/test_returns_classification.py fails until a newly routed name appears in
exactly one bucket, so a new view cannot slip in unclassified.
"""

from collections.abc import Sequence
from typing import Any

from django.http import HttpRequest
from django.urls import reverse

from common.returns import OriginUrl, UrlName, parse_origin

# Renders a page and changes nothing. The only URLs a mutation may return to.
READ_ONLY: frozenset[UrlName] = frozenset(
    {
        "games:admin_settings",
        "games:export_admin_settings_ini",
        "games:filter_builder",
        "games:index",
        "games:library",
        "games:list_devices",
        "games:list_games",
        "games:list_platforms",
        "games:list_playevents",
        "games:list_purchases",
        "games:list_sessions",
        "games:settings",
        "games:settings_kit_preview",
        "games:stats_alltime",
        "games:stats_by_year",
        "games:view_game",
        "games:view_purchase",
    }
)

# Mutates, then redirects (or sends HX-Redirect); consumes an origin.
ORIGIN_AWARE: frozenset[UrlName] = frozenset(
    {
        "games:add_device",
        "games:add_game",
        "games:add_platform",
        "games:add_playevent",
        "games:add_playevent_for_game",
        "games:add_purchase",
        "games:add_purchase_for_game",
        "games:add_session",
        "games:add_session_for_game",
        "games:delete_device",
        "games:delete_game",
        "games:delete_platform",
        "games:delete_playevent",
        "games:delete_purchase",
        "games:delete_session",
        "games:edit_device",
        "games:edit_game",
        "games:edit_platform",
        "games:edit_playevent",
        "games:edit_purchase",
        "games:edit_session",
        "games:finish_session",
        "games:list_sessions_start_session_from_session",
        "games:reset_session",
        "games:split_purchase",
    }
)

# GET only: renders a confirmation and forwards the origin to the form it draws.
CONFIRMATION: frozenset[UrlName] = frozenset(
    {
        "games:refund_purchase_confirmation",
        "games:split_purchase_confirmation",
    }
)

# Mutates and answers with a partial swap, leaving the user where they are.
IN_PLACE: frozenset[UrlName] = frozenset(
    {
        "games:refund_purchase",
        "games:settings_kit_preview_patch",
    }
)

# Routed only when DEBUG was true at games/urls.py import time.
DEBUG_ONLY: frozenset[UrlName] = frozenset(
    {
        "games:settings_kit_preview",
        "games:settings_kit_preview_patch",
    }
)


def origin_from(request: HttpRequest, *, reject: str | None = None) -> OriginUrl | None:
    """The read-only page this request was launched from, if it carries one."""
    return parse_origin(request, returnable=READ_ONLY, reject=reject)


def return_url(
    request: HttpRequest,
    *,
    fallback: UrlName,
    fallback_args: Sequence[Any] = (),
    reject: str | None = None,
) -> str:
    """Where a finished mutation should send the user."""
    return origin_from(request, reject=reject) or reverse(
        fallback, args=list(fallback_args)
    )
