"""A stated endpoint's columns and constraints."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, NamedTuple

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


class WayColumn(NamedTuple):
    """A way column and the ways it admits."""

    column: ColumnName
    #: At least one; none would refuse every act.
    ways: tuple[EndWay, *tuple[EndWay, ...]]


type EndpointName = str  # e.g. "access_end"; names its constraints


@dataclass(frozen=True, slots=True, kw_only=True)
class EndpointColumnsBase:
    """The columns every endpoint shape names."""

    name: EndpointName
    #: A label: models import this module.
    model_label: ModelLabel
    #: The stated day; null is unknown.
    when: ColumnName
    lower: ColumnName
    upper: ColumnName
    #: First recorded.
    marker: ColumnName
    note: ColumnName
    way: WayColumn | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class EndpointColumns(EndpointColumnsBase):
    """A stated endpoint: stated, corrected, voided."""

    def unstated_columns(self) -> dict[ColumnName, Any]:
        """What a row holds before any act."""
        columns: dict[ColumnName, Any] = {
            self.when: None,
            self.marker: None,
            self.note: "",
        }
        if self.way is not None:
            columns[self.way.column] = ""
        return columns


@dataclass(frozen=True, slots=True, kw_only=True)
class OpeningEndpointColumns(EndpointColumnsBase):
    """Stated by the creation; corrected; never voided."""

    def __post_init__(self) -> None:
        if self.way is not None:
            raise TypeError("An opening endpoint states no way.")


_BOUND_EXPRESSIONS: dict[BoundSide, type[models.Func]] = {
    "lower": TemporalLowerBound,
    "upper": TemporalUpperBound,
}


def endpoint_when() -> TemporalValueField:
    """The stated day; null is a day nobody knows."""
    return TemporalValueField()


def endpoint_bound(when: str, side: BoundSide) -> models.GeneratedField:
    """One bound of the stated day."""
    return models.GeneratedField(
        expression=_BOUND_EXPRESSIONS[side](when),
        output_field=models.DateField(null=True),
        null=True,
        serialize=False,
        db_persist=True,
        editable=False,
    )


def endpoint_marker() -> models.DateTimeField:
    """First recorded; null is no act."""
    return models.DateTimeField(null=True, default=None, editable=False)


def opening_marker() -> models.DateTimeField:
    """First recorded; every row holds the act."""
    return models.DateTimeField(editable=False)


def endpoint_note() -> models.TextField:
    """The act's note; the empty string is none."""
    return models.TextField(blank=True, default="")


def endpoint_way(ways: Sequence[EndWay]) -> models.CharField:
    """How it happened; empty is no act."""
    return models.CharField(
        max_length=WAY_MAX_LENGTH,
        blank=True,
        default="",
        choices=[(way.value, END_WAY_LABELS[way]) for way in ways],
    )


def endpoint_constraints(
    endpoint: EndpointColumnsBase,
) -> tuple[models.CheckConstraint, ...]:
    """A way endpoint's CHECKs; none without ways."""
    if endpoint.way is None:
        return ()
    way = endpoint.way.column
    stem = endpoint.model_label.replace(".", "_").lower() + "_" + endpoint.name
    known = [option.value for option in endpoint.way.ways]
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
