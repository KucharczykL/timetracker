"""Confirm-then-retire: the delete affordance for a row an event may reference.

A sibling of :func:`games.views.deletion.confirm_and_delete`, built on the same
``confirm_and_apply``. The only difference is that it asks the retention policy
what the POST will actually do, so the confirmation page can say so. Promising
a permanent delete and then archiving would be the one thing worse than either.
"""

from collections.abc import Sequence
from functools import partial
from typing import Any

from django.db.models import Model
from django.http import HttpRequest, HttpResponse

from common.components.core import Children
from common.returns import UrlName
from games.retention import archive_or_delete, reference_count
from games.views.deletion import confirm_and_apply


def retention_message(noun: str, label: str, count: int) -> str:
    """What the confirmation says when the row is going to be kept."""
    return (
        f"{count} recorded event(s) reference {label}, and their history has to "
        f"stay readable. The {noun} will be removed from your library along "
        "with everything below, but the record itself is kept out of sight "
        "rather than deleted:"
    )


def confirm_and_retire(
    request: HttpRequest,
    instance: Model,
    *,
    title: str,
    noun: str,
    label: str,
    message: str,
    fallback: UrlName,
    fallback_args: Sequence[Any] = (),
    details: Children = None,
    detail_url: str | None = None,
) -> HttpResponse:
    """Confirm on GET, retire on POST, then return to the origin.

    ``message`` is the copy for the ordinary case, where the row really is
    deleted. When an event references it, :func:`retention_message` replaces
    that copy; ``noun`` and ``label`` are what it needs to name the row.
    """
    referencing = reference_count(instance)
    return confirm_and_apply(
        request,
        action=partial(archive_or_delete, instance),
        title=title,
        message=(
            retention_message(noun, label, referencing) if referencing else message
        ),
        confirm_label="Delete",
        fallback=fallback,
        fallback_args=fallback_args,
        details=details,
        reject=detail_url,
    )
