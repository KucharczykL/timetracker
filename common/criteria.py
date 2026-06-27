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
from typing import Any, Literal, Self, TypeVar

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
    INCLUDES_ONLY = "INCLUDES_ONLY"
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
            cls.INCLUDES_ONLY,
            cls.IS_NULL,
            cls.NOT_NULL,
        ]


# ── Relation match-mode ──────────────────────────────────────────────────────


class RelationMatch(str, Enum):
    """Quantifier for a nested cross-entity sub-filter (e.g. a game's sessions).

    A dedicated vocabulary (rather than reusing ``Modifier``) so only the three
    meaningful quantifiers are representable. ``relation_to_q`` interprets it.
    """

    ANY = "ANY"  # ≥1 related row matches the sub-filter (EXISTS)
    NONE = "NONE"  # no related row matches (NOT EXISTS); includes zero-row parents
    ALL = "ALL"  # every related row matches; vacuously true for zero-row parents


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

    def to_json(self) -> dict[str, Any]:
        # `value` is the whole payload here, so it must always serialize — the
        # base implementation omits fields equal to their default, which would
        # silently drop a meaningful ``value=False`` (e.g. is_refunded=False).
        result = super().to_json()
        result["value"] = self.value
        return result


@dataclass
class _SetCriterion(_Criterion):
    """Shared base for set-membership criteria (``MultiCriterion`` /
    ``ChoiceCriterion``).

    Two orthogonal channels, mirroring Stash's modifier model:

    - ``value`` is the *include* set. The ``modifier`` governs how it matches:

      - ``INCLUDES`` — in ``value`` (match *any*); ``EQUALS`` is an alias.
      - ``INCLUDES_ALL`` — related to *all* of ``value`` (meaningful for
        many-to-many fields, e.g. a purchase's games).
      - ``EXCLUDES`` — in none of ``value`` (match *none*); ``NOT_EQUALS`` is an
        alias.

    - ``excludes`` is an *always-orthogonal* negative: it contributes
      ``AND NOT IN (excludes)`` for every (non-presence) modifier, never
      swapped into the include set. An exclude-only criterion therefore means
      "everything except ``excludes``".

    Empty lists contribute no constraint. ``IS_NULL`` / ``NOT_NULL`` test
    presence and ignore both lists.

    The logic lives entirely here so the two subclasses (which differ only in
    their value type) cannot drift.
    """

    value: list = field(default_factory=list)
    excludes: list = field(default_factory=list)
    modifier: Modifier = Modifier.INCLUDES

    def to_q(self, field_name: str) -> Q:
        modifier = self.modifier
        if modifier == Modifier.IS_NULL:
            return Q(**{f"{field_name}__isnull": True})
        if modifier == Modifier.NOT_NULL:
            return Q(**{f"{field_name}__isnull": False})
        # The modifier governs only the include set; ``excludes`` is an orthogonal
        # AND'd negative applied for every (non-presence) modifier.
        q = self._value_q(field_name)
        if self.excludes:
            q &= ~Q(**{f"{field_name}__in": self.excludes})
        return q

    def _value_q(self, field_name: str) -> Q:
        """Build the Q for the include (``value``) set, per the modifier."""
        modifier = self.modifier
        if modifier in (Modifier.INCLUDES, Modifier.EQUALS):
            return Q(**{f"{field_name}__in": self.value}) if self.value else Q()
        if modifier in (Modifier.EXCLUDES, Modifier.NOT_EQUALS):
            return ~Q(**{f"{field_name}__in": self.value}) if self.value else Q()
        if modifier in (Modifier.INCLUDES_ALL, Modifier.INCLUDES_ONLY):
            # INCLUDES_ALL ("related to all of these") and INCLUDES_ONLY
            # ("related to exactly these, nothing else") are only meaningful
            # for many-to-many fields.  A naive Q(field=a) & Q(field=b)
            # collapses to a single join requiring one through-row to equal
            # both values (impossible), so the generic criterion layer cannot
            # build a correct Q.  M2M callers must supply their own Q builder
            # at the filter level — see PurchaseFilter._games_to_q for the
            # chained-subquery pattern.
            assert False, (
                f"{modifier} requires a filter-level Q builder for M2M fields. "
                "See PurchaseFilter._games_to_q for the chained-subquery pattern."
            )
        raise ValueError(f"Unsupported modifier {modifier} for {type(self).__name__}")

    @classmethod
    def from_json(cls, data: dict | None) -> Self | None:
        result = super().from_json(data)
        if result is None:
            return None
        # Labels embedded as {id, label} dicts are display-only; strip to bare ids
        # so the querying layer stays clean and typed.
        result.value = [
            item["id"] if isinstance(item, dict) else item for item in result.value
        ]
        result.excludes = [
            item["id"] if isinstance(item, dict) else item for item in result.excludes
        ]
        return result


@dataclass
class MultiCriterion(_SetCriterion):
    """Filter on a many-to-many or ForeignKey relationship by ID list.

    All modifier logic (including ``INCLUDES_ALL`` and ``EXCLUDES``) lives in
    ``_SetCriterion``; this subclass only refines the value type.
    """

    value: list[int] = field(default_factory=list)
    excludes: list[int] = field(default_factory=list)


@dataclass
class ChoiceCriterion(_SetCriterion):
    """Filter on a choice/enum field with multi-select include/exclude.

    Used by FilterSelect widgets for status, ownership_type, etc. Shares all
    modifier logic with ``MultiCriterion`` via ``_SetCriterion``.
    """

    value: list[str] = field(default_factory=list)
    excludes: list[str] = field(default_factory=list)


@dataclass
class AggregateCriterion(_Criterion):
    """Filter a parent entity by a reducer (count / sum / avg) over one of its
    relations, compared numerically — e.g. "games with > 5 sessions" or "sum of
    a game's purchase prices between X and Y".

    The reducer, relation accessor, source field, and unit are *static config*
    supplied by the filter at query time (see ``aggregate_to_q``); the instance
    carries only the user's comparison value(s)/modifier and an optional
    ``scope`` sub-filter restricting which related rows are aggregated.
    """

    value: int | float = 0
    value2: int | float | None = None
    modifier: Modifier = Modifier.EQUALS
    # Restricts which related rows are aggregated. Always None today; honouring it
    # needs both the path serializer (to populate it) AND aggregate_to_q (to apply
    # it as the annotate ``filter=``) — neither is wired yet.
    scope: "OperatorFilter | None" = None

    def to_q(self, field_name: str) -> Q:
        # Unlike sibling criteria, an aggregate is not self-contained: its meaning
        # depends on static config (reducer/relation/source/unit) the filter holds.
        # It is evaluated via aggregate_to_q(...), never this method.
        raise NotImplementedError(
            "AggregateCriterion is evaluated via aggregate_to_q(), not to_q()"
        )


# ── OperatorFilter base ────────────────────────────────────────────────────

F = TypeVar("F", bound="OperatorFilter")


# Maps criterion class names (as they appear in dataclass annotations) to the
# concrete class. Shared by from_json() and where() so the two construction
# paths resolve field types identically and cannot drift.
_CRITERION_TYPES: dict[str, type[_Criterion]] = {
    "StringCriterion": StringCriterion,
    "IntCriterion": IntCriterion,
    "FloatCriterion": FloatCriterion,
    "DateCriterion": DateCriterion,
    "BoolCriterion": BoolCriterion,
    "MultiCriterion": MultiCriterion,
    "ChoiceCriterion": ChoiceCriterion,
    "AggregateCriterion": AggregateCriterion,
}

# Registry of OperatorFilter subclasses by name, so from_json can resolve a
# cross-entity sub-filter field's type from its (string) annotation name — e.g.
# PurchaseFilter.game_filter, GameFilter.playevent_filter. (to_json needs no
# lookup; it dispatches structurally on isinstance.) Populated by
# OperatorFilter.__init_subclass__ as each concrete filter class is defined (see
# games/filters.py). Mirrors _CRITERION_TYPES for criterion fields.
_FILTER_TYPES: dict[str, type["OperatorFilter"]] = {}

# The three sub-filter composition fields, shared by every OperatorFilter.
_OPERATOR_FIELDS: tuple[str, str, str] = ("AND", "OR", "NOT")


def _criterion_class_for(
    cls: type["OperatorFilter"], field_name: str
) -> type[_Criterion] | None:
    """Resolve the criterion class declared for ``field_name`` on a filter, or
    None if the field is absent or isn't a criterion field."""
    for dataclass_field in dc_fields(cls):
        if dataclass_field.name != field_name:
            continue
        field_type = dataclass_field.type
        if isinstance(field_type, str):
            # e.g. "StringCriterion | None" → "StringCriterion"
            field_type = field_type.split("|")[0].strip()
            return _CRITERION_TYPES.get(field_type)
        if isinstance(field_type, type) and issubclass(field_type, _Criterion):
            return field_type
        return None
    return None


# Lookup suffix → Modifier. A missing suffix defaults per criterion type
# (EQUALS for scalars, INCLUDES for set criteria) and is handled in where().
_SUFFIX_MODIFIER: dict[str, Modifier] = {
    "gt": Modifier.GREATER_THAN,
    "lt": Modifier.LESS_THAN,
    "ne": Modifier.NOT_EQUALS,
    "between": Modifier.BETWEEN,
    "not_between": Modifier.NOT_BETWEEN,
    "in": Modifier.INCLUDES,
    "exclude": Modifier.EXCLUDES,
    "all": Modifier.INCLUDES_ALL,
    "contains": Modifier.INCLUDES,
    "regex": Modifier.MATCHES_REGEX,
    "isnull": Modifier.IS_NULL,
    "notnull": Modifier.NOT_NULL,
}


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

    ``match`` is the relation quantifier, meaningful only when this filter is
    nested as a cross-entity sub-filter (e.g. ``GameFilter.session_filter``):
    ANY (default), NONE, or ALL (ALL reserved — see ``relation_to_q``).
    ``relation_to_q`` reads it; at the top level it is ignored (``to_q`` never
    consults ``self.match``).
    """

    match: RelationMatch = RelationMatch.ANY

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # Register concrete filter classes so from_json can resolve a
        # cross-entity sub-filter field's type by its annotation name.
        _FILTER_TYPES[cls.__name__] = cls

    @classmethod
    def where(cls: type[F], **lookups: Any) -> F:
        """Build a filter from Django-``QuerySet.filter()``-style lookups.

        Each keyword is ``field__suffix=value`` (or ``field=value`` for the
        default modifier). The criterion class is resolved from the field's
        annotation, so the same value can target an int / string / date / set
        field without naming the criterion type::

            GameFilter.where(year_released__gt=2010, status=["f", "p"])

        Suffix → modifier follows ``_SUFFIX_MODIFIER``; a missing suffix means
        EQUALS for scalars and INCLUDES for set criteria. ``between`` /
        ``not_between`` consume a 2-tuple; ``isnull`` / ``notnull`` ignore the
        value. Unknown fields or suffixes raise ``TypeError``.
        """
        field_criteria: dict[str, Any] = {}
        for lookup, value in lookups.items():
            field_name, _, suffix = lookup.rpartition("__")
            if not field_name:
                field_name, suffix = lookup, ""

            criterion_class = _criterion_class_for(cls, field_name)
            if criterion_class is None:
                raise TypeError(f"{cls.__name__} has no filter field {field_name!r}")

            is_set_criterion = issubclass(criterion_class, _SetCriterion)
            if suffix == "":
                modifier = Modifier.INCLUDES if is_set_criterion else Modifier.EQUALS
            elif suffix in _SUFFIX_MODIFIER:
                modifier = _SUFFIX_MODIFIER[suffix]
            else:
                raise TypeError(f"Unknown lookup suffix {suffix!r} on {field_name!r}")

            criterion_arguments: dict[str, Any] = {"modifier": modifier}
            if suffix in ("isnull", "notnull"):
                pass  # presence test ignores the value
            elif modifier in (Modifier.BETWEEN, Modifier.NOT_BETWEEN):
                lower_bound, upper_bound = value
                criterion_arguments["value"] = lower_bound
                criterion_arguments["value2"] = upper_bound
            else:
                criterion_arguments["value"] = value

            field_criteria[field_name] = criterion_class(**criterion_arguments)
        return cls(**field_criteria)

    def sub_filter(self) -> OperatorFilter | None:
        """Return the first non-None of AND / OR / NOT."""
        for attr in _OPERATOR_FIELDS:
            if hasattr(self, attr):
                v = getattr(self, attr)
                if v is not None:
                    return v
        return None

    def _criterion_fields(self) -> list[str]:
        """Return field names that hold a _Criterion instance."""
        names: list[str] = []
        for f in dc_fields(self):
            if f.name in _OPERATOR_FIELDS:
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
        criterion_types = _CRITERION_TYPES
        kwargs: dict[str, Any] = {}
        for f in dc_fields(cls):
            if f.name not in data:
                continue
            raw = data[f.name]
            # Relation quantifier (meaningful only on a nested sub-filter).
            if f.name == "match":
                kwargs["match"] = RelationMatch(raw)
                continue
            if raw is None:
                kwargs[f.name] = None
                continue
            # Recurse into sub-filters (AND / OR / NOT)
            if f.name in _OPERATOR_FIELDS:
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
            # Cross-entity sub-filter field (e.g. game_filter, playevent_filter):
            # resolve the filter class by its annotation name and recurse.
            elif isinstance(f_type, str) and f_type in _FILTER_TYPES:
                filter_cls = _FILTER_TYPES[f_type]
                kwargs[f.name] = (
                    filter_cls.from_json(raw) if isinstance(raw, dict) else None
                )
        return cls(**kwargs)

    def to_json(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        # Relation quantifier: only emit when set to a non-default (a nested
        # sub-filter asking for NONE/ALL); the default ANY stays implicit so
        # existing top-level and ANY-matched filters serialize unchanged.
        if self.match != RelationMatch.ANY:
            result["match"] = self.match
        for f in dc_fields(self):
            v = getattr(self, f.name)
            if v is None:
                continue
            if f.name == "match":
                continue
            if f.name in _OPERATOR_FIELDS:
                result[f.name] = v.to_json()
            elif isinstance(v, _Criterion):
                j = v.to_json()
                if j:
                    result[f.name] = j
            # Cross-entity sub-filter field (game_filter, playevent_filter, …).
            # AND/OR/NOT already matched the first branch; the name guard is
            # belt-and-suspenders against a future reordering of these branches.
            elif isinstance(v, OperatorFilter) and f.name not in _OPERATOR_FIELDS:
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


# ── Relation & aggregate query helpers ──────────────────────────────────────
# Self-contained Q builders for the two cross-entity node kinds. Filters pass the
# related/parent model and the relation wiring (lookups, accessor, reducer); the
# algebra lives here so every entity composes the same logic instead of repeating
# bespoke subqueries in each to_q().

Number = int | float
type Reducer = Literal["count", "sum", "avg"]  # e.g. "count"
type DurationUnit = Literal["duration_hours"]  # compare hours vs a DurationField


def _numeric_to_q(
    value: Number, value2: Number | None, modifier: Modifier, field_name: str
) -> Q:
    """Numeric comparison Q against a plain column/annotation (int or float)."""
    if modifier == Modifier.EQUALS:
        return Q(**{field_name: value})
    if modifier == Modifier.NOT_EQUALS:
        return ~Q(**{field_name: value})
    if modifier == Modifier.GREATER_THAN:
        return Q(**{f"{field_name}__gt": value})
    if modifier == Modifier.LESS_THAN:
        return Q(**{f"{field_name}__lt": value})
    if modifier == Modifier.BETWEEN:
        if value2 is None:
            raise ValueError("BETWEEN requires value2")
        return Q(
            **{
                f"{field_name}__gte": min(value, value2),
                f"{field_name}__lte": max(value, value2),
            }
        )
    if modifier == Modifier.NOT_BETWEEN:
        if value2 is None:
            raise ValueError("NOT_BETWEEN requires value2")
        lower_bound, upper_bound = min(value, value2), max(value, value2)
        return Q(**{f"{field_name}__lt": lower_bound}) | Q(
            **{f"{field_name}__gt": upper_bound}
        )
    if modifier == Modifier.IS_NULL:
        return Q(**{f"{field_name}__isnull": True})
    if modifier == Modifier.NOT_NULL:
        return Q(**{f"{field_name}__isnull": False})
    raise ValueError(f"Unsupported modifier {modifier} for numeric comparison")


def duration_hours_to_q(
    value: Number, value2: Number | None, modifier: Modifier, field_name: str
) -> Q:
    """Compare an hours value against a DurationField (or a duration aggregate).

    Django stores DurationField as microseconds, so hours convert to
    ``timedelta``. EQUALS matches the whole hour bucket ``[h, h+1)``;
    IS_NULL/NOT_NULL test against a zero duration. BETWEEN/NOT_BETWEEN require
    ``value2``. This is the single home for the hours<->timedelta logic shared by
    the direct duration fields (playtime, session durations) and the
    duration-unit aggregates. Like ``_numeric_to_q`` it raises on an unsupported
    or incomplete modifier rather than silently matching everything.
    """
    from datetime import timedelta

    duration = timedelta(hours=value)
    if modifier == Modifier.EQUALS:
        return Q(
            **{
                f"{field_name}__gte": duration,
                f"{field_name}__lt": timedelta(hours=value + 1),
            }
        )
    if modifier == Modifier.NOT_EQUALS:
        return ~Q(
            **{
                f"{field_name}__gte": duration,
                f"{field_name}__lt": timedelta(hours=value + 1),
            }
        )
    if modifier == Modifier.GREATER_THAN:
        return Q(**{f"{field_name}__gt": duration})
    if modifier == Modifier.LESS_THAN:
        return Q(**{f"{field_name}__lt": duration})
    if modifier == Modifier.BETWEEN:
        if value2 is None:
            raise ValueError("BETWEEN requires value2")
        lower_bound = timedelta(hours=min(value, value2))
        upper_bound = timedelta(hours=max(value, value2))
        return Q(
            **{f"{field_name}__gte": lower_bound, f"{field_name}__lte": upper_bound}
        )
    if modifier == Modifier.NOT_BETWEEN:
        if value2 is None:
            raise ValueError("NOT_BETWEEN requires value2")
        lower_bound = timedelta(hours=min(value, value2))
        upper_bound = timedelta(hours=max(value, value2))
        return Q(**{f"{field_name}__lt": lower_bound}) | Q(
            **{f"{field_name}__gt": upper_bound}
        )
    if modifier == Modifier.IS_NULL:
        return Q(**{field_name: timedelta(0)})
    if modifier == Modifier.NOT_NULL:
        return ~Q(**{field_name: timedelta(0)})
    raise ValueError(f"Unsupported modifier {modifier} for duration comparison")


# The related/parent model is the concrete Django model the filter targets.
# Typed ``Any`` rather than ``type[Model]`` because django-stubs doesn't expose
# ``.objects`` on the abstract base ``Model``, so ``type[Model]`` fails mypy here.
ModelClass = Any  # a concrete Django model class, e.g. Game


def relation_to_q(
    sub: OperatorFilter,
    *,
    related_model: ModelClass,
    related_lookup: str,
    parent_field: str = "id",
) -> Q:
    """EXISTS / NOT-EXISTS / FOR-ALL subquery for a nested cross-entity sub-filter.

    The sub-filter's ``match`` quantifier picks the set semantics, each expressed
    as a ``parent_field IN (...)`` membership over a subquery of related rows:

    - ANY (default): ``parent_field IN (<related rows matching sub>)`` — the
      parent has at least one matching related row (EXISTS).
    - NONE: the negation of ANY — the parent has no matching related row (NOT
      EXISTS). Zero-related-row parents are included.
    - ALL: every related row matches the sub-filter. Implemented as the absence
      of any *violating* (non-matching) related row:
      ``~Q(parent_field IN (<related rows NOT matching sub>))``.

      **Vacuous truth is INCLUDED**: a parent with zero related rows has no
      violating row, so it matches ALL — the standard ∀ semantics. The
      alternative (requiring ≥1 related row, i.e. ``ANY AND ALL``) was considered
      and rejected as the default; callers wanting it can AND an ANY sub-filter.

    The branch is exhaustive — an unexpected match raises rather than silently
    degrading to ANY.
    """
    related = related_model.objects.all()
    if sub.match == RelationMatch.ANY:
        matching = related.filter(sub.to_q()).values_list(related_lookup, flat=True)
        return Q(**{f"{parent_field}__in": matching})
    if sub.match == RelationMatch.NONE:
        matching = related.filter(sub.to_q()).values_list(related_lookup, flat=True)
        return ~Q(**{f"{parent_field}__in": matching})
    if sub.match == RelationMatch.ALL:
        violating = related.filter(~sub.to_q()).values_list(related_lookup, flat=True)
        return ~Q(**{f"{parent_field}__in": violating})
    raise ValueError(f"Unsupported relation match {sub.match!r}")


def aggregate_to_q(
    criterion: AggregateCriterion,
    *,
    model: ModelClass,
    reducer: Reducer,
    accessor: str,
    source: str | None = None,
    unit: DurationUnit | None = None,
) -> Q:
    """Filter ``model`` by a reducer (count / sum / avg) over a relation.

    Annotates ``model`` with the aggregate, compares it against the criterion's
    value(s)/modifier, and returns ``Q(id__in=<matching ids>)``.
    ``unit="duration_hours"`` compares an hours value against a DurationField
    aggregate; otherwise a plain numeric comparison is used. ``sum``/``avg``
    require a ``source`` field; ``count`` aggregates whole rows.
    """
    from django.db.models import Avg, Count, Sum

    if reducer == "count":
        aggregate_expression: Any = Count(accessor, distinct=True)
    elif reducer in ("sum", "avg"):
        if source is None:
            raise ValueError(f"{reducer!r} aggregate requires a source field")
        reduce = Sum if reducer == "sum" else Avg
        aggregate_expression = reduce(f"{accessor}__{source}")
    else:
        raise ValueError(f"Unknown aggregate reducer {reducer!r}")

    if unit == "duration_hours":
        compare = duration_hours_to_q(
            criterion.value, criterion.value2, criterion.modifier, "_agg"
        )
    else:
        compare = _numeric_to_q(
            criterion.value, criterion.value2, criterion.modifier, "_agg"
        )

    ids = (
        model.objects.annotate(_agg=aggregate_expression)
        .filter(compare)
        .values_list("id", flat=True)
    )
    return Q(id__in=ids)
