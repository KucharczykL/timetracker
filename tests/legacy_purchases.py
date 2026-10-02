"""Legacy purchase rows on the historical model."""

# conversion-tooling

from datetime import date, datetime
from typing import Any, Final, TypedDict, Unpack

import pytest
from django.db import connection

from games.backfill.legacy_model import HistoricalModel, legacy_purchase_model
from games.backfill.purchase_plan import LegacyOwnership, LegacyType
from games.models import Game, Platform, UserLibrary
from games.projections import FieldName


class LegacyOwnershipCode:
    """The stored ownership words."""

    PHYSICAL: Final[LegacyOwnership] = "ph"
    DIGITAL: Final[LegacyOwnership] = "di"
    DIGITALUPGRADE: Final[LegacyOwnership] = "du"
    RENTED: Final[LegacyOwnership] = "re"
    BORROWED: Final[LegacyOwnership] = "bo"
    TRIAL: Final[LegacyOwnership] = "tr"
    DEMO: Final[LegacyOwnership] = "de"
    PIRATED: Final[LegacyOwnership] = "pi"


class LegacyTypeCode:
    """The stored purchase types."""

    GAME: Final[LegacyType] = "game"
    DLC: Final[LegacyType] = "dlc"
    SEASONPASS: Final[LegacyType] = "season_pass"
    BATTLEPASS: Final[LegacyType] = "battle_pass"


#: Untyped: the historical class has no stub.
type LegacyPurchaseRow = Any


class LegacyFacts(TypedDict, total=False):
    """The columns a test may state."""

    ownership_type: LegacyOwnership
    type: LegacyType
    name: str
    price: float
    price_currency: str
    converted_price: float | None
    converted_currency: str
    date_purchased: date
    date_refunded: date | None
    infinite: bool
    num_purchases: int
    removed_at: datetime | None
    platform: Platform | None
    related_game: Game | None


#: Taken as instances, stored as keys.
_RELATIONS: Final[tuple[FieldName, ...]] = ("platform", "related_game")


def legacy_row(
    library: UserLibrary, *games: Game, **facts: Unpack[LegacyFacts]
) -> LegacyPurchaseRow:
    """One row; `num_purchases` counts its games.

    A stated `num_purchases` wins, for a drifted row.
    """
    if "library" in facts:
        raise TypeError("The library is the first argument.")
    stated: dict[str, Any] = {"library_id": library.pk, **facts}
    for relation in _RELATIONS:
        if relation in stated:
            target = stated.pop(relation)
            stated[f"{relation}_id"] = None if target is None else target.pk
    stated.setdefault("num_purchases", len(games))
    row: LegacyPurchaseRow = legacy_purchase_model()._default_manager.create(**stated)
    row.games.add(*(game.pk for game in games))
    return row


def link_game(row: LegacyPurchaseRow, game: Game) -> None:
    """Link one more game; recount."""
    row.games.add(game.pk)
    row.num_purchases = row.games.count()
    row.save(update_fields=["num_purchases"])


@pytest.fixture
def legacy_purchase(db: None) -> HistoricalModel:
    """The historical model, tables made per test."""
    if not connection.in_atomic_block:
        pytest.fail(
            "legacy_purchase needs the test's own transaction: a flush "
            "would meet a table no model declares.",
            pytrace=False,
        )
    model = legacy_purchase_model()
    with connection.schema_editor() as editor:
        editor.create_model(model)
    return model
