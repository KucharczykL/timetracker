"""Fail closed when ownership-cutover companion records are incomplete."""

import logging

from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.db.models import Exists, OuterRef

from games.models import (
    PurchaseConversionState,
    UserLibrary,
    UserLibraryPreferences,
    UserPreferences,
)

logger = logging.getLogger("games")


def assert_library_structure() -> None:
    """Ensure every user and library has its required companion records.

    This is deliberately diagnostic-only: deployment and repair flows must fix
    incomplete historical data explicitly instead of startup silently mutating it.
    """
    user_model = get_user_model()
    missing_libraries = list(
        user_model.objects.filter(
            ~Exists(UserLibrary.objects.filter(user_id=OuterRef("pk")))
        ).values_list("pk", flat=True)
    )
    missing_user_preferences = list(
        user_model.objects.filter(
            ~Exists(UserPreferences.objects.filter(user_id=OuterRef("pk")))
        ).values_list("pk", flat=True)
    )
    missing_library_preferences = list(
        UserLibrary.objects.filter(
            ~Exists(UserLibraryPreferences.objects.filter(library_id=OuterRef("pk")))
        ).values_list("pk", flat=True)
    )
    missing_conversion_states = list(
        UserLibrary.objects.filter(
            ~Exists(PurchaseConversionState.objects.filter(library_id=OuterRef("pk")))
        ).values_list("pk", flat=True)
    )
    missing = [
        *(f"UserLibrary(user={user_id})" for user_id in missing_libraries),
        *(f"UserPreferences(user={user_id})" for user_id in missing_user_preferences),
        *(
            f"UserLibraryPreferences(library={library_id})"
            for library_id in missing_library_preferences
        ),
        *(
            f"PurchaseConversionState(library={library_id})"
            for library_id in missing_conversion_states
        ),
    ]
    if missing:
        detail = ", ".join(missing)
        logger.critical("Library structure readiness failed: %s", detail)
        raise ImproperlyConfigured(f"Library structure readiness failed: {detail}")
