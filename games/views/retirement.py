"""The removal affordance for a referenceable row.

A sibling of `confirm_and_delete`, for a row whose removal is a
stamp rather than a destroying delete.
"""

from collections.abc import Sequence
from functools import partial
from typing import Any

from django.db.models import Model
from django.http import HttpRequest, HttpResponse

from common.components.core import Children
from common.returns import UrlName
from games.removal import remove
from games.views.deletion import confirm_and_apply


def confirm_and_retire(
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
    """Confirm on GET, remove on POST."""
    return confirm_and_apply(
        request,
        action=partial(remove, instance),
        title=title,
        message=message,
        confirm_label="Remove",
        fallback=fallback,
        fallback_args=fallback_args,
        details=details,
        reject=detail_url,
    )
