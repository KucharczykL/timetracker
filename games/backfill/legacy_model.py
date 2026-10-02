"""The legacy purchase, as migration state."""

# conversion-tooling

import functools
from typing import Final

from django.db.backends.base.base import BaseDatabaseWrapper
from django.db.migrations.loader import MigrationLoader
from django.db.models import Model

LEGACY_STATE: Final = ("games", "0034_conversion_review_hidden")
LEGACY_TABLE: Final = "games_legacypurchase"


class LegacyTableGone(Exception):
    """The drop already took the table."""


@functools.cache
def legacy_purchase_model() -> type[Model]:
    """The historical `LegacyPurchase`, rendered once."""
    state = MigrationLoader(None, ignore_no_migrations=True).project_state(LEGACY_STATE)
    return state.apps.get_model("games", "LegacyPurchase")


def require_legacy_table(connection: BaseDatabaseWrapper) -> type[Model]:
    """The historical model, while its table stands."""
    if LEGACY_TABLE not in connection.introspection.table_names():
        raise LegacyTableGone(LEGACY_TABLE)
    return legacy_purchase_model()
