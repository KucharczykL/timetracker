"""Legacy purchase rows on the historical model."""

# conversion-tooling

from typing import Any

import pytest
from django.db import connection
from django.db.models import Model

from games.backfill.legacy_model import legacy_purchase_model


class LegacyCodes:
    """The historical model's stored words."""

    PHYSICAL = "ph"
    DIGITAL = "di"
    DIGITALUPGRADE = "du"
    RENTED = "re"
    BORROWED = "bo"
    TRIAL = "tr"
    DEMO = "de"
    PIRATED = "pi"
    GAME = "game"
    DLC = "dlc"
    SEASONPASS = "season_pass"
    BATTLEPASS = "battle_pass"


#: Instances the historical model takes as keys.
_RELATIONS = ("library", "platform", "related_game")


def legacy_row(library: Model, *games: Model, **facts: Any) -> Any:
    """One row; `num_purchases` counts its games."""
    stated: dict[str, Any] = {"library": library, **facts}
    for relation in _RELATIONS:
        if relation in stated:
            target = stated.pop(relation)
            stated[f"{relation}_id"] = None if target is None else target.pk
    stated.setdefault("num_purchases", len(games))
    row: Any = legacy_purchase_model()._default_manager.create(**stated)
    row.games.add(*(game.pk for game in games))
    return row


def link_game(row: Any, game: Model) -> None:
    """Link one more game; recount."""
    row.games.add(game.pk)
    type(row)._default_manager.filter(pk=row.pk).update(num_purchases=row.games.count())


@pytest.fixture
def legacy_purchase(db):
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
