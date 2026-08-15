"""Transactional entry points for per-library purchase-price conversion."""

from __future__ import annotations

from django.db import transaction
from django.db.models import Q
from django_q.tasks import async_task

from games.models import PurchaseConversionState, UserLibrary


def request_conversion(library: UserLibrary, target_currency: str) -> int:
    """Publish a new requested version and enqueue its worker after commit."""
    target_currency = target_currency.upper()
    if len(target_currency) != 3:
        raise ValueError("target_currency must be a three-letter currency code")

    with transaction.atomic():
        locked_library = UserLibrary.objects.select_for_update().get(pk=library.pk)
        state, _ = PurchaseConversionState.objects.get_or_create(library=locked_library)
        state.requested_version += 1
        state.requested_currency = target_currency
        state.status = PurchaseConversionState.Status.PENDING
        state.retry_at = None
        state.last_error = ""
        state.save(
            update_fields=[
                "requested_version",
                "requested_currency",
                "status",
                "retry_at",
                "last_error",
            ]
        )
        version = state.requested_version
        library_id = str(locked_library.pk)
        transaction.on_commit(
            lambda: async_task(
                "games.tasks.convert_library_prices", library_id, version
            )
        )
    return version


def request_inheriting_library_conversions(target_currency: str) -> None:
    """Request a site-default conversion only for users without an override."""
    libraries = UserLibrary.objects.filter(
        Q(user__preferences__default_display_currency__isnull=True)
        | Q(user__preferences__isnull=True)
    )
    for library in libraries:
        request_conversion(library, target_currency)
