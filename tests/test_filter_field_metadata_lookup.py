"""metadata_lookup: the query path and the metadata path, declared apart."""

from dataclasses import dataclass, field
from typing import ClassVar

from django.db.models import Q

from common.criteria import (
    ChoiceCriterion,
    DateCriterion,
    FilterField,
    Modifier,
    OperatorFilter,
    field_metadata,
)
from games.models import PlayerGame, Playthrough


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
    q = _AliasedFilter.fields["status"].to_q("status", criterion)

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
            handler=lambda criterion: Q(),
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
            "started": FilterField(handler=lambda criterion: Q()),
        }

        @classmethod
        def _comparison_model(cls):
            return Playthrough

    entry = next(
        meta for meta in field_metadata(_BareHandlerFilter) if meta["name"] == "started"
    )

    assert entry["nullable"] is False
