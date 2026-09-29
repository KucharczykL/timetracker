"""metadata_lookup: the query path and the metadata path, declared apart."""

from dataclasses import dataclass, field
from typing import ClassVar
from zoneinfo import ZoneInfo

import pytest
from django.db.models import Q
from django.db.models.functions import TruncDate

from common.criteria import (
    ChoiceCriterion,
    DateCriterion,
    FilterField,
    FilterQueryContext,
    FilterQueryContextRequired,
    Modifier,
    OperatorFilter,
    calendar_day_handler,
    field_metadata,
)
from games.models import Game, PlayerGame, Playthrough


@dataclass
class _AliasedFilter(OperatorFilter):
    AND: list[_AliasedFilter] = field(default_factory=list)
    OR: list[_AliasedFilter] = field(default_factory=list)
    NOT: list[_AliasedFilter] = field(default_factory=list)

    status: ChoiceCriterion | None = None

    fields: ClassVar[dict[str, FilterField]] = {
        "status": FilterField("tracked__status", metadata_lookup="status"),
    }

    @classmethod
    def _comparison_model(cls):
        return PlayerGame


def test_metadata_resolves_the_declared_path():
    entry = next(
        meta for meta in field_metadata(_AliasedFilter) if meta["name"] == "status"
    )

    assert [choice["value"] for choice in entry["choices"]] == [
        "unplayed",
        "played",
        "completed",
        "retired",
        "shelved",
        "abandoned",
    ]


def test_the_query_still_uses_the_alias():
    criterion = ChoiceCriterion(value="played", modifier=Modifier.EQUALS)
    q = _AliasedFilter.fields["status"].to_q(
        "status", criterion, FilterQueryContext.for_validation()
    )

    assert "tracked__status" in str(q)


@dataclass
class _HandlerFilter(OperatorFilter):
    """A handler over two bounds names none."""

    AND: list[_HandlerFilter] = field(default_factory=list)
    OR: list[_HandlerFilter] = field(default_factory=list)
    NOT: list[_HandlerFilter] = field(default_factory=list)

    started: DateCriterion | None = None

    fields: ClassVar[dict[str, FilterField]] = {
        "started": FilterField(
            handler=lambda criterion, context: Q(),
            metadata_lookup="started_lower",
        ),
    }

    @classmethod
    def _comparison_model(cls):
        return Playthrough


def test_a_handler_field_states_its_widgets_column():
    """The field names the picker's column."""
    entry = next(
        meta for meta in field_metadata(_HandlerFilter) if meta["name"] == "started"
    )

    assert entry["kind"] == "date"
    assert entry["nullable"] is True


def test_a_handler_field_without_one_still_resolves_nothing():
    """Nothing invents a column for a handler."""

    @dataclass
    class _BareHandlerFilter(OperatorFilter):
        AND: list[_BareHandlerFilter] = field(default_factory=list)
        OR: list[_BareHandlerFilter] = field(default_factory=list)
        NOT: list[_BareHandlerFilter] = field(default_factory=list)

        started: DateCriterion | None = None

        fields: ClassVar[dict[str, FilterField]] = {
            "started": FilterField(handler=lambda criterion, context: Q()),
        }

        @classmethod
        def _comparison_model(cls):
            return Playthrough

    entry = next(
        meta for meta in field_metadata(_BareHandlerFilter) if meta["name"] == "started"
    )

    assert entry["nullable"] is False


@dataclass
class _DayFilter(OperatorFilter):
    """A day facet over a timestamp column."""

    AND: list[_DayFilter] = field(default_factory=list)
    OR: list[_DayFilter] = field(default_factory=list)
    NOT: list[_DayFilter] = field(default_factory=list)

    created_at: DateCriterion | None = None

    fields: ClassVar[dict[str, FilterField]] = {
        "created_at": FilterField(
            handler=calendar_day_handler("created_at"), metadata_lookup="created_at"
        ),
    }

    @classmethod
    def _comparison_model(cls):
        return Game


def test_a_day_field_reads_its_widget_from_the_column():
    entry = next(
        meta for meta in field_metadata(_DayFilter) if meta["name"] == "created_at"
    )

    assert entry["kind"] == "date"
    assert entry["nullable"] is False


def test_a_day_field_needs_a_context():
    day = _DayFilter(created_at=DateCriterion(value="2026-03-05"))

    with pytest.raises(FilterQueryContextRequired):
        day.to_q()


def test_a_day_field_compiles_in_the_contexts_zone():
    day = _DayFilter(created_at=DateCriterion(value="2026-03-05"))

    (lookup,) = day.to_q(FilterQueryContext.for_validation()).children

    assert isinstance(lookup.lhs, TruncDate)
    assert lookup.lhs.tzinfo == ZoneInfo("UTC")
