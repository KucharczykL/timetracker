"""The legacy purchase, as migration state."""

# conversion-tooling

import functools
from typing import Final

from django.db.backends.base.base import BaseDatabaseWrapper
from django.db.migrations.exceptions import NodeNotFoundError
from django.db.migrations.loader import MigrationLoader
from django.db.models import Model

from games.identity_audit import TableName

type AppLabel = str  # e.g. "games"
type MigrationName = str  # e.g. "0034_conversion_review_hidden"
type MigrationKey = tuple[AppLabel, MigrationName]
#: Rendered from migration state; no custom managers.
type HistoricalModel = type[Model]

LEGACY_STATE: Final[MigrationKey] = ("games", "0034_conversion_review_hidden")
LEGACY_TABLE: Final[TableName] = "games_legacypurchase"


class LegacyTableGone(Exception):
    """The drop already took the table."""


@functools.cache
def legacy_purchase_model() -> HistoricalModel:
    """The historical `LegacyPurchase`, rendered once."""
    loader = MigrationLoader(None, ignore_no_migrations=True)
    try:
        state = loader.project_state(LEGACY_STATE)
    except (NodeNotFoundError, KeyError) as error:
        raise LegacyTableGone(f"Migration state {LEGACY_STATE} is gone.") from error
    return state.apps.get_model("games", "LegacyPurchase")


def require_legacy_table(connection: BaseDatabaseWrapper) -> HistoricalModel:
    """The historical model, while its table stands."""
    if LEGACY_TABLE not in connection.introspection.table_names():
        raise LegacyTableGone(LEGACY_TABLE)
    return legacy_purchase_model()
