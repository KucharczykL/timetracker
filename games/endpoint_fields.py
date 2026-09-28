"""The columns and constraints of a stated endpoint.

Each model spells an endpoint's columns in its own class body
through these factories, so type checkers and the migration
autodetector see every field. `games.E014` holds a registered
endpoint against the fields and constraints its model declares.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from django.db import models
from django.db.models import Q

from games.end_ways import END_WAY_LABELS, EndWay
from timetracker.temporal import (
    TemporalLowerBound,
    TemporalUpperBound,
    TemporalValueField,
)

type BoundSide = Literal["lower", "upper"]

#: Longest recorded way, with room for more.
WAY_MAX_LENGTH = 16

type ColumnName = str  # e.g. "started"
type ModelLabel = str  # e.g. "games.Playthrough"


@dataclass(frozen=True, slots=True, kw_only=True)
class EndpointColumns:
    """The columns one endpoint writes on one projection model.

    Free of events, so a model's `Meta` can read it.
    """

    #: Names the endpoint's constraints; unique per model.
    name: str
    #: A label, not the class: the model reads this value.
    model_label: ModelLabel
    #: The stated day; null is a day nobody knows.
    when: ColumnName
    lower: ColumnName
    upper: ColumnName
    #: The instant the act was first recorded; null is no act.
    marker: ColumnName
    note: ColumnName
    #: Both empty for an endpoint without ways.
    way: ColumnName | None = None
    ways: tuple[EndWay, ...] = ()

    def __post_init__(self) -> None:
        if (self.way is None) != (not self.ways):
            raise ValueError(
                f"Endpoint {self.name!r} names a way column exactly when it "
                "admits ways."
            )

    def unstated_columns(self) -> dict[ColumnName, Any]:
        """What a row holds before any act."""
        columns: dict[ColumnName, Any] = {
            self.when: None,
            self.marker: None,
            self.note: "",
        }
        if self.way is not None:
            columns[self.way] = ""
        return columns


_BOUND_EXPRESSIONS: dict[BoundSide, type[models.Func]] = {
    "lower": TemporalLowerBound,
    "upper": TemporalUpperBound,
}


def endpoint_when() -> TemporalValueField:
    """The stated day; null is a day nobody knows."""
    return TemporalValueField()


def endpoint_bound(when: str, side: BoundSide) -> models.GeneratedField:
    """One bound of the stated day, as the database computes it."""
    return models.GeneratedField(
        expression=_BOUND_EXPRESSIONS[side](when),
        output_field=models.DateField(null=True),
        null=True,
        serialize=False,
        db_persist=True,
        editable=False,
    )


def endpoint_marker() -> models.DateTimeField:
    """When the act was first recorded; null is no act."""
    return models.DateTimeField(null=True, default=None, editable=False)


def endpoint_note() -> models.TextField:
    """The act's note; the empty string is none."""
    return models.TextField(blank=True, default="")


def endpoint_way(ways: Sequence[EndWay]) -> models.CharField:
    """How the act happened; the empty string is no act."""
    return models.CharField(
        max_length=WAY_MAX_LENGTH,
        blank=True,
        default="",
        choices=[(way.value, END_WAY_LABELS[way]) for way in ways],
    )


def endpoint_constraints(
    endpoint: EndpointColumns,
) -> tuple[models.CheckConstraint, ...]:
    """The CHECKs a way endpoint needs; none without ways.

    Each admits every row a command can state, so neither refuses
    in a command's place.
    """
    if endpoint.way is None:
        return ()
    way = endpoint.way
    stem = endpoint.model_label.replace(".", "_").lower() + "_" + endpoint.name
    known = [option.value for option in endpoint.ways]
    return (
        models.CheckConstraint(
            condition=Q(**{f"{way}__in": [*known, ""]}),
            name=f"{stem}_way_known",
        ),
        models.CheckConstraint(
            condition=(
                Q(**{way: "", f"{endpoint.marker}__isnull": True})
                | (~Q(**{way: ""}) & Q(**{f"{endpoint.marker}__isnull": False}))
            ),
            name=f"{stem}_way_with_marker",
        ),
    )
