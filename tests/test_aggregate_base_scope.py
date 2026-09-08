"""#1013: an aggregate spec states a scope of its own."""

from datetime import timedelta

import pytest
from django.utils import timezone

from common.criteria import (
    AggregateCriterion,
    AggregateSpec,
    Modifier,
    StringCriterion,
    aggregate_to_q,
)
from games.filters import (
    GameFilter,
    SessionFilter,
    filter_query_context_for_library,
)
from games.models import Game, Session

pytestmark = pytest.mark.django_db


def _session(game, note: str) -> Session:
    """One session of this game, an hour long."""
    started = timezone.now()
    return Session.objects.create(
        game=game,
        timestamp_start=started,
        timestamp_end=started + timedelta(hours=1),
        note=note,
    )


def test_a_base_scope_narrows_every_reduction(owned_library):
    """The spec's own scope rides along, so a game whose only
    counted session matches reads exactly one."""
    counted = Game.objects.create(library=owned_library, name="Counted")
    ignored = Game.objects.create(library=owned_library, name="Ignored")
    _session(counted, "counted")
    _session(ignored, "ignored")

    spec = AggregateSpec(
        "count",
        "sessions",
        SessionFilter,
        base_scope=SessionFilter(
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
    """Both narrow: the count reads the sessions matching each."""
    game = Game.objects.create(library=owned_library, name="Both")
    _session(game, "counted")
    _session(game, "counted too")

    spec = AggregateSpec(
        "count",
        "sessions",
        SessionFilter,
        base_scope=SessionFilter(
            note=StringCriterion(value="counted", modifier=Modifier.INCLUDES)
        ),
    )
    criterion = AggregateCriterion(value=1, modifier=Modifier.EQUALS)
    #: `scope` is init=False: only `_aggregate_from_json` fills it.
    criterion.scope = SessionFilter(
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
    """A wrong-typed scope would build its Q in another model's
    namespace, so the table refuses it at import."""
    with pytest.raises(TypeError, match="SessionFilter"):
        AggregateSpec("count", "sessions", SessionFilter, base_scope=GameFilter())
