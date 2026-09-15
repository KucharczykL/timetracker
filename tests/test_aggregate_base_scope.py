"""An aggregate spec states its own scope."""

from datetime import timedelta

import pytest
from django.utils import timezone
from session_rows import session_row

from common.criteria import (
    AggregateCriterion,
    AggregateSpec,
    Modifier,
    StringCriterion,
    aggregate_to_q,
)
from games.filters import (
    GAME_SESSIONS,
    GameFilter,
    PlayerSessionFilter,
    PurchaseFilter,
    filter_query_context_for_library,
)
from games.models import Game, PlayerSession, Purchase
from games.removal import remove

pytestmark = pytest.mark.django_db


def _session(game, note: str) -> PlayerSession:
    """One hour-long session of this game."""
    started = timezone.now()
    return session_row(
        game,
        started_at=started,
        ended_at=started + timedelta(hours=1),
        note=note,
    )


def test_a_base_scope_narrows_every_reduction(owned_library):
    """The spec's own scope rides along."""
    counted = Game.objects.create(library=owned_library, name="Counted")
    ignored = Game.objects.create(library=owned_library, name="Ignored")
    _session(counted, "counted")
    _session(ignored, "ignored")

    spec = AggregateSpec(
        "count",
        GAME_SESSIONS,
        PlayerSessionFilter,
        base_scope=PlayerSessionFilter(
            note=StringCriterion(value="counted", modifier=Modifier.EQUALS)
        ),
    )
    matching = Game.objects.filter(
        aggregate_to_q(
            AggregateCriterion(value=1, modifier=Modifier.EQUALS),
            model=Game,
            spec=spec,
            context=filter_query_context_for_library(owned_library),
        )
    )

    assert list(matching) == [counted]


def test_a_base_scope_composes_with_the_criterion_scope(owned_library):
    """Both scopes narrow the same count."""
    game = Game.objects.create(library=owned_library, name="Both")
    _session(game, "counted")
    _session(game, "counted too")

    spec = AggregateSpec(
        "count",
        GAME_SESSIONS,
        PlayerSessionFilter,
        base_scope=PlayerSessionFilter(
            note=StringCriterion(value="counted", modifier=Modifier.INCLUDES)
        ),
    )
    criterion = AggregateCriterion(value=1, modifier=Modifier.EQUALS)
    #: `scope` is init=False: only `_aggregate_from_json` fills it.
    criterion.scope = PlayerSessionFilter(
        note=StringCriterion(value="too", modifier=Modifier.INCLUDES)
    )
    matching = Game.objects.filter(
        aggregate_to_q(
            criterion,
            model=Game,
            spec=spec,
            context=filter_query_context_for_library(owned_library),
        )
    )

    assert list(matching) == [game]


def test_a_base_scope_must_match_the_scope_filter():
    """A wrong-typed scope is refused at import."""
    with pytest.raises(TypeError, match="PlayerSessionFilter"):
        AggregateSpec(
            "count", GAME_SESSIONS, PlayerSessionFilter, base_scope=GameFilter()
        )


def _counted(library, spec: AggregateSpec, count: int):
    """The games whose unscoped reduction equals `count`."""
    return list(
        Game.objects.filter(
            aggregate_to_q(
                AggregateCriterion(value=count, modifier=Modifier.EQUALS),
                model=Game,
                spec=spec,
                context=filter_query_context_for_library(library),
            )
        )
    )


def test_an_unscoped_count_reads_the_library_scope(owned_library):
    """A removed row is in no count, scope or none."""
    game = Game.objects.create(library=owned_library, name="Counted")
    _session(game, "kept")
    PlayerSession.objects.filter(pk=_session(game, "removed").pk).update(
        removed_at=timezone.now()
    )

    spec = AggregateSpec("count", GAME_SESSIONS, PlayerSessionFilter)

    assert _counted(owned_library, spec, 1) == [game]
    assert _counted(owned_library, spec, 2) == []


def test_an_unscoped_purchase_count_omits_a_removed_purchase(owned_library):
    game = Game.objects.create(library=owned_library, name="Bought")
    for name in ("kept", "removed"):
        purchase = Purchase.objects.create(
            library=owned_library,
            name=name,
            price_currency="CZK",
            date_purchased=timezone.now().date(),
        )
        purchase.games.add(game)
    remove(Purchase.objects.get(name="removed"))

    spec = AggregateSpec("count", "purchases", PurchaseFilter)

    assert _counted(owned_library, spec, 1) == [game]
