"""metadata_lookup: the query path and the metadata path, declared apart."""

from dataclasses import dataclass, field
from typing import ClassVar

import pytest

from common.criteria import (
    ChoiceCriterion,
    FilterField,
    Modifier,
    OperatorFilter,
    field_metadata,
)
from games.models import PlayerGame


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


def test_a_handler_refuses_a_metadata_lookup():
    with pytest.raises(ValueError, match="metadata_lookup"):
        FilterField(handler=lambda criterion: None, metadata_lookup="status")
