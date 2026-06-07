"""
Typed criterion inputs for building structured filters.

Inspired by Stash's filter architecture: every filterable field uses a typed
criterion with a value and a CriterionModifier. This separates *what* you're
filtering from *how* you're comparing, and makes filter serialization trivial.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, fields as dc_fields
from enum import Enum
from typing import Any, Self, TypeVar

from django.db.models import Q

# ── Modifier ──────────────────────────────────────────────────────────────


class Modifier(str, Enum):
    """Comparison operators shared across all criterion types."""

    EQUALS = "EQUALS"
    NOT_EQUALS = "NOT_EQUALS"
    GREATER_THAN = "GREATER_THAN"
    LESS_THAN = "LESS_THAN"
    BETWEEN = "BETWEEN"
    NOT_BETWEEN = "NOT_BETWEEN"
    INCLUDES = "INCLUDES"
    EXCLUDES = "EXCLUDES"
    INCLUDES_ALL = "INCLUDES_ALL"
    IS_NULL = "IS_NULL"
    NOT_NULL = "NOT_NULL"
    MATCHES_REGEX = "MATCHES_REGEX"
    NOT_MATCHES_REGEX = "NOT_MATCHES_REGEX"

    @classmethod
    def for_strings(cls) -> list[Self]:
        return [
            cls.EQUALS,
            cls.NOT_EQUALS,
            cls.INCLUDES,
            cls.EXCLUDES,
            cls.MATCHES_REGEX,
            cls.NOT_MATCHES_REGEX,
            cls.IS_NULL,
            cls.NOT_NULL,
        ]

    @classmethod
    def for_numbers(cls) -> list[Self]:
        return [
            cls.EQUALS,
            cls.NOT_EQUALS,
            cls.GREATER_THAN,
            cls.LESS_THAN,
            cls.BETWEEN,
            cls.NOT_BETWEEN,
            cls.IS_NULL,
            cls.NOT_NULL,
        ]

    @classmethod
    def for_dates(cls) -> list[Self]:
        return cls.for_numbers()

    @classmethod
    def for_multi(cls) -> list[Self]:
        return [
            cls.INCLUDES,
            cls.EXCLUDES,
            cls.INCLUDES_ALL,
            cls.IS_NULL,
            cls.NOT_NULL,
        ]


# ── Base criterion ─────────────────────────────────────────────────────────

T = TypeVar("T")


@dataclass
class _Criterion:
    """Base for all typed criteria."""

    value: Any = None
    modifier: Modifier = Modifier.EQUALS

    def to_q(self, field_name: str) -> Q:
        raise NotImplementedError

    @classmethod
    def from_json(cls, data: dict | None) -> Self | None:
        if data is None or not isinstance(data, dict):
            return None
        kwargs: dict[str, Any] = {}
        for f in dc_fields(cls):
            if f.name in data:
                val = data[f.name]
                # Coerce string modifier to Modifier enum
                if f.name == "modifier" and isinstance(val, str):
                    val = Modifier(val)
                kwargs[f.name] = val
        return cls(**kwargs)

    def to_json(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for f in dc_fields(self):
            v = getattr(self, f.name)
            if v is not None and v != f.default:
                result[f.name] = v
        return result


# ── Concrete criteria ──────────────────────────────────────────────────────


@dataclass
class StringCriterion(_Criterion):
    value: str = ""
    modifier: Modifier = Modifier.EQUALS

    def to_q(self, field_name: str) -> Q:
        m = self.modifier
        if m == Modifier.EQUALS:
            return Q(**{field_name: self.value})
        if m == Modifier.NOT_EQUALS:
            return ~Q(**{field_name: self.value})
        if m == Modifier.INCLUDES:
            return Q(**{f"{field_name}__icontains": self.value})
        if m == Modifier.EXCLUDES:
            return ~Q(**{f"{field_name}__icontains": self.value})
        if m == Modifier.MATCHES_REGEX:
            return Q(**{f"{field_name}__regex": self.value})
        if m == Modifier.NOT_MATCHES_REGEX:
            return ~Q(**{f"{field_name}__regex": self.value})
        if m == Modifier.IS_NULL:
            return Q(**{f"{field_name}__isnull": True})
        if m == Modifier.NOT_NULL:
            return Q(**{f"{field_name}__isnull": False})
        raise ValueError(f"Unsupported modifier {m} for string field")


@dataclass
class IntCriterion(_Criterion):
    value: int = 0
    value2: int | None = None
    modifier: Modifier = Modifier.EQUALS

    def to_q(self, field_name: str) -> Q:
        m = self.modifier
        if m == Modifier.EQUALS:
            return Q(**{field_name: self.value})
        if m == Modifier.NOT_EQUALS:
            return ~Q(**{field_name: self.value})
        if m == Modifier.GREATER_THAN:
            return Q(**{f"{field_name}__gt": self.value})
        if m == Modifier.LESS_THAN:
            return Q(**{f"{field_name}__lt": self.value})
        if m == Modifier.BETWEEN:
            if self.value2 is None:
                raise ValueError("BETWEEN requires value2")
            return Q(
                **{
                    f"{field_name}__gte": min(self.value, self.value2),
                    f"{field_name}__lte": max(self.value, self.value2),
                }
            )
        if m == Modifier.NOT_BETWEEN:
            if self.value2 is None:
                raise ValueError("NOT_BETWEEN requires value2")
            lo, hi = min(self.value, self.value2), max(self.value, self.value2)
            return Q(**{f"{field_name}__lt": lo}) | Q(**{f"{field_name}__gt": hi})
        if m == Modifier.IS_NULL:
            return Q(**{f"{field_name}__isnull": True})
        if m == Modifier.NOT_NULL:
            return Q(**{f"{field_name}__isnull": False})
        raise ValueError(f"Unsupported modifier {m} for int field")


@dataclass
class FloatCriterion(_Criterion):
    value: float = 0.0
    value2: float | None = None
    modifier: Modifier = Modifier.EQUALS

    def to_q(self, field_name: str) -> Q:
        m = self.modifier
        if m == Modifier.EQUALS:
            return Q(**{field_name: self.value})
        if m == Modifier.NOT_EQUALS:
            return ~Q(**{field_name: self.value})
        if m == Modifier.GREATER_THAN:
            return Q(**{f"{field_name}__gt": self.value})
        if m == Modifier.LESS_THAN:
            return Q(**{f"{field_name}__lt": self.value})
        if m == Modifier.BETWEEN:
            if self.value2 is None:
                raise ValueError("BETWEEN requires value2")
            return Q(
                **{
                    f"{field_name}__gte": min(self.value, self.value2),
                    f"{field_name}__lte": max(self.value, self.value2),
                }
            )
        if m == Modifier.NOT_BETWEEN:
            if self.value2 is None:
                raise ValueError("NOT_BETWEEN requires value2")
            lo, hi = min(self.value, self.value2), max(self.value, self.value2)
            return Q(**{f"{field_name}__lt": lo}) | Q(**{f"{field_name}__gt": hi})
        if m == Modifier.IS_NULL:
            return Q(**{f"{field_name}__isnull": True})
        if m == Modifier.NOT_NULL:
            return Q(**{f"{field_name}__isnull": False})
        raise ValueError(f"Unsupported modifier {m} for float field")


@dataclass
class DateCriterion(_Criterion):
    value: str = ""
    value2: str | None = None
    modifier: Modifier = Modifier.EQUALS

    def to_q(self, field_name: str) -> Q:
        m = self.modifier
        if m == Modifier.EQUALS:
            return Q(**{field_name: self.value})
        if m == Modifier.NOT_EQUALS:
            return ~Q(**{field_name: self.value})
        if m == Modifier.GREATER_THAN:
            return Q(**{f"{field_name}__gt": self.value})
        if m == Modifier.LESS_THAN:
            return Q(**{f"{field_name}__lt": self.value})
        if m == Modifier.BETWEEN:
            if self.value2 is None:
                raise ValueError("BETWEEN requires value2")
            return Q(
                **{f"{field_name}__gte": self.value, f"{field_name}__lte": self.value2}
            )
        if m == Modifier.NOT_BETWEEN:
            if self.value2 is None:
                raise ValueError("NOT_BETWEEN requires value2")
            return Q(**{f"{field_name}__lt": self.value}) | Q(
                **{f"{field_name}__gt": self.value2}
            )
        if m == Modifier.IS_NULL:
            return Q(**{f"{field_name}__isnull": True})
        if m == Modifier.NOT_NULL:
            return Q(**{f"{field_name}__isnull": False})
        raise ValueError(f"Unsupported modifier {m} for date field")


@dataclass
class BoolCriterion(_Criterion):
    value: bool = False
    # Bool only makes sense with EQUALS
    modifier: Modifier = Modifier.EQUALS

    def to_q(self, field_name: str) -> Q:
        if self.modifier == Modifier.EQUALS:
            return Q(**{field_name: self.value})
        if self.modifier == Modifier.NOT_EQUALS:
            return ~Q(**{field_name: self.value})
        raise ValueError(f"Unsupported modifier {self.modifier} for bool field")


@dataclass
class MultiCriterion(_Criterion):
    """Filter on a many-to-many or ForeignKey relationship by ID list."""

    value: list[int] = field(default_factory=list)
    excludes: list[int] = field(default_factory=list)
    modifier: Modifier = Modifier.INCLUDES

    def to_q(self, field_name: str) -> Q:
        m = self.modifier
        if m == Modifier.INCLUDES:
            q = Q(**{f"{field_name}__in": self.value})
            if self.excludes:
                q &= ~Q(**{f"{field_name}__in": self.excludes})
            return q
        if m == Modifier.EXCLUDES:
            return ~Q(**{f"{field_name}__in": self.value})
        if m == Modifier.INCLUDES_ALL:
            q = Q()
            for v in self.value:
                q &= Q(**{field_name: v})
            return q
        if m == Modifier.IS_NULL:
            return Q(**{f"{field_name}__isnull": True})
        if m == Modifier.NOT_NULL:
            return Q(**{f"{field_name}__isnull": False})
        raise ValueError(f"Unsupported modifier {m} for multi field")


@dataclass
class ChoiceCriterion(_Criterion):
    """Filter on a choice/enum field with multi-select include/exclude.

    Used by FilterSelect widgets for status, ownership_type, etc.
    Supports INCLUDES, EXCLUDES, EQUALS, IS_NULL, NOT_NULL modifiers.
    """

    value: list[str] = field(default_factory=list)
    excludes: list[str] = field(default_factory=list)
    modifier: Modifier = Modifier.INCLUDES

    def to_q(self, field_name: str) -> Q:
        m = self.modifier
        if m == Modifier.INCLUDES:
            q = Q()
            if self.value:
                q &= Q(**{f"{field_name}__in": self.value})
            if self.excludes:
                q &= ~Q(**{f"{field_name}__in": self.excludes})
            return q
        if m == Modifier.EXCLUDES:
            q = Q()
            if self.value:
                q &= ~Q(**{f"{field_name}__in": self.value})
            if self.excludes:
                q &= Q(**{f"{field_name}__in": self.excludes})
            return q
        if m == Modifier.EQUALS:
            q = Q()
            if self.value:
                q &= Q(**{f"{field_name}__in": self.value})
            if self.excludes:
                q &= ~Q(**{f"{field_name}__in": self.excludes})
            return q
        if m == Modifier.NOT_EQUALS:
            return ~Q(**{f"{field_name}__in": self.value})
        if m == Modifier.IS_NULL:
            return Q(**{f"{field_name}__isnull": True})
        if m == Modifier.NOT_NULL:
            return Q(**{f"{field_name}__isnull": False})
        raise ValueError(f"Unsupported modifier {m} for choice field")


# ── OperatorFilter base ────────────────────────────────────────────────────

F = TypeVar("F", bound="OperatorFilter")


@dataclass
class OperatorFilter:
    """Mixin providing AND/OR/NOT composition for entity filter types.

    Subclasses should declare nullable references to themselves::

        @dataclass
        class GameFilter(OperatorFilter):
            AND: "GameFilter | None" = None
            OR:  "GameFilter | None" = None
            NOT: "GameFilter | None" = None
            name: StringCriterion | None = None
            ...
    """

    def sub_filter(self) -> OperatorFilter | None:
        """Return the first non-None of AND / OR / NOT."""
        for attr in ("AND", "OR", "NOT"):
            if hasattr(self, attr):
                v = getattr(self, attr)
                if v is not None:
                    return v
        return None

    def _criterion_fields(self) -> list[str]:
        """Return field names that hold a _Criterion instance."""
        names: list[str] = []
        for f in dc_fields(self):
            if f.name in ("AND", "OR", "NOT"):
                continue
            v = getattr(self, f.name)
            if isinstance(v, _Criterion):
                names.append(f.name)
        return names

    def to_q(self) -> Q:
        """Build a Django Q object from this filter and its sub-filters."""
        q = Q()
        for field_name in self._criterion_fields():
            c = getattr(self, field_name)
            if c is not None:
                q &= c.to_q(field_name)
        sub = self.sub_filter()
        if sub is not None:
            if getattr(self, "AND", None) is not None:
                q &= sub.to_q()
            elif getattr(self, "OR", None) is not None:
                q |= sub.to_q()
            elif getattr(self, "NOT", None) is not None:
                q &= ~sub.to_q()
        return q

    @classmethod
    def from_json(cls, data: dict[str, Any] | None) -> Self | None:
        if data is None or not isinstance(data, dict):
            return None
        # Resolve criterion class names to actual types
        criterion_types: dict[str, type[_Criterion]] = {
            "StringCriterion": StringCriterion,
            "IntCriterion": IntCriterion,
            "FloatCriterion": FloatCriterion,
            "DateCriterion": DateCriterion,
            "BoolCriterion": BoolCriterion,
            "MultiCriterion": MultiCriterion,
            "ChoiceCriterion": ChoiceCriterion,
        }
        kwargs: dict[str, Any] = {}
        for f in dc_fields(cls):
            if f.name not in data:
                continue
            raw = data[f.name]
            if raw is None:
                kwargs[f.name] = None
                continue
            # Recurse into sub-filters (AND / OR / NOT)
            if f.name in ("AND", "OR", "NOT"):
                kwargs[f.name] = cls.from_json(raw) if isinstance(raw, dict) else None
                continue
            # Resolve criterion fields from string type annotation
            f_type = f.type
            if isinstance(f_type, str):
                # e.g. "StringCriterion | None" → "StringCriterion"
                f_type = f_type.split("|")[0].strip()
            if isinstance(f_type, str) and f_type in criterion_types:
                criterion_cls = criterion_types[f_type]
                kwargs[f.name] = (
                    criterion_cls.from_json(raw) if isinstance(raw, dict) else None
                )
            elif isinstance(f_type, type) and issubclass(f_type, _Criterion):
                kwargs[f.name] = (
                    f_type.from_json(raw) if isinstance(raw, dict) else None
                )
        return cls(**kwargs)

    def to_json(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for f in dc_fields(self):
            v = getattr(self, f.name)
            if v is None:
                continue
            if f.name in ("AND", "OR", "NOT"):
                result[f.name] = v.to_json()
            elif isinstance(v, _Criterion):
                j = v.to_json()
                if j:
                    result[f.name] = j
        return result


# ── JSON helpers ───────────────────────────────────────────────────────────


def filter_from_json(cls: type[F], json_str: str) -> F | None:
    """Deserialize a filter from a JSON string.

    Usage:
        f = filter_from_json(GameFilter, request.GET.get("filter", ""))
        games = Game.objects.filter(f.to_q())
    """
    if not json_str:
        return None
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        return None
    return cls.from_json(data)


def filter_to_json(f: OperatorFilter) -> str:
    """Serialize a filter to a JSON string for URL params or storage."""
    return json.dumps(f.to_json())
