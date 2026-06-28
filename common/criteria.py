"""
Typed criterion inputs for building structured filters.

Inspired by Stash's filter architecture: every filterable field uses a typed
criterion with a value and a CriterionModifier. This separates *what* you're
filtering from *how* you're comparing, and makes filter serialization trivial.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field, fields as dc_fields
from enum import Enum
from typing import Any, Literal, Self, TypeVar

from django.core.exceptions import FieldDoesNotExist
from django.db import models
from django.db.models import F, Q

# ── Errors ─────────────────────────────────────────────────────────────────


class FilterError(ValueError):
    """A syntactically-parseable filter that is semantically invalid.

    Raised for user-controllable bad input reachable from a hand-edited
    ``?filter=``: an unknown modifier/match enum, a missing ``BETWEEN`` bound,
    an unsupported modifier for a field type, an M2M-only modifier on the
    generic layer, or malformed JSON. The view layer catches this to
    warn-and-ignore; the API layer turns it into a 400 — neither should 500.

    Subclasses ``ValueError`` so it stays catchable as one. Internal invariants
    that can only fail through a programmer error (e.g. ``aggregate_to_q``'s
    hard-coded reducer/source) deliberately raise ``RuntimeError`` instead, so a
    real bug still surfaces as a 500 rather than being masked as bad user input
    by ``filter_from_json``'s eager-validation catch.
    """


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

    @classmethod
    def for_field_comparisons(cls) -> list[Self]:
        return [cls.EQUALS, cls.NOT_EQUALS, cls.GREATER_THAN, cls.LESS_THAN]


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
                    try:
                        val = Modifier(val)
                    except ValueError as exc:
                        raise FilterError(f"Unknown filter modifier {val!r}") from exc
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
        raise FilterError(f"Unsupported modifier {m} for string field")


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
            if self.value is None or self.value2 is None:
                raise FilterError("BETWEEN requires two bounds (value and value2)")
            return Q(
                **{
                    f"{field_name}__gte": min(self.value, self.value2),
                    f"{field_name}__lte": max(self.value, self.value2),
                }
            )
        if m == Modifier.NOT_BETWEEN:
            if self.value is None or self.value2 is None:
                raise FilterError("NOT_BETWEEN requires two bounds (value and value2)")
            lo, hi = min(self.value, self.value2), max(self.value, self.value2)
            return Q(**{f"{field_name}__lt": lo}) | Q(**{f"{field_name}__gt": hi})
        if m == Modifier.IS_NULL:
            return Q(**{f"{field_name}__isnull": True})
        if m == Modifier.NOT_NULL:
            return Q(**{f"{field_name}__isnull": False})
        raise FilterError(f"Unsupported modifier {m} for int field")


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
            if self.value is None or self.value2 is None:
                raise FilterError("BETWEEN requires two bounds (value and value2)")
            return Q(
                **{
                    f"{field_name}__gte": min(self.value, self.value2),
                    f"{field_name}__lte": max(self.value, self.value2),
                }
            )
        if m == Modifier.NOT_BETWEEN:
            if self.value is None or self.value2 is None:
                raise FilterError("NOT_BETWEEN requires two bounds (value and value2)")
            lo, hi = min(self.value, self.value2), max(self.value, self.value2)
            return Q(**{f"{field_name}__lt": lo}) | Q(**{f"{field_name}__gt": hi})
        if m == Modifier.IS_NULL:
            return Q(**{f"{field_name}__isnull": True})
        if m == Modifier.NOT_NULL:
            return Q(**{f"{field_name}__isnull": False})
        raise FilterError(f"Unsupported modifier {m} for float field")


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
            if self.value is None or self.value2 is None:
                raise FilterError("BETWEEN requires two bounds (value and value2)")
            return Q(
                **{f"{field_name}__gte": self.value, f"{field_name}__lte": self.value2}
            )
        if m == Modifier.NOT_BETWEEN:
            if self.value is None or self.value2 is None:
                raise FilterError("NOT_BETWEEN requires two bounds (value and value2)")
            return Q(**{f"{field_name}__lt": self.value}) | Q(
                **{f"{field_name}__gt": self.value2}
            )
        if m == Modifier.IS_NULL:
            return Q(**{f"{field_name}__isnull": True})
        if m == Modifier.NOT_NULL:
            return Q(**{f"{field_name}__isnull": False})
        raise FilterError(f"Unsupported modifier {m} for date field")


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
        raise FilterError(f"Unsupported modifier {self.modifier} for bool field")

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
            raise FilterError(
                f"{modifier} requires a filter-level Q builder for M2M fields. "
                "See PurchaseFilter._games_to_q for the chained-subquery pattern."
            )
        raise FilterError(f"Unsupported modifier {modifier} for {type(self).__name__}")

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
    carries only the user's comparison value(s)/modifier.
    """

    value: int | float = 0
    value2: int | float | None = None
    modifier: Modifier = Modifier.EQUALS

    def to_q(self, field_name: str) -> Q:
        # Unlike sibling criteria, an aggregate is not self-contained: its meaning
        # depends on static config (reducer/relation/source/unit) the filter holds.
        # It is evaluated via aggregate_to_q(...), never this method.
        raise NotImplementedError(
            "AggregateCriterion is evaluated via aggregate_to_q(), not to_q()"
        )


@dataclass
class FieldComparisonCriterion(_Criterion):
    """Compare one model column to another (``left <op> right``) via F() expressions.

    ``left`` and ``right`` are model column names (resolved + type-checked against
    the filter's model by the base OperatorFilter before to_q runs). Operands are
    self-contained, so to_q ignores the inherited ``field_name`` argument.

    Null semantics: an F() comparison against a NULL operand matches no rows (SQL
    unknown); NOT_EQUALS via ~Q likewise excludes NULLs. This is expected.
    """

    left: str = ""
    right: str = ""
    modifier: Modifier = Modifier.EQUALS

    def to_q(self, field_name: str = "") -> Q:  # field_name ignored; operands self-contained
        return _field_comparison_to_q(self.left, self.right, self.modifier)

    def to_json(self) -> dict[str, Any]:
        # left/right default to "" — the base to_json would drop them. Force-emit, like BoolCriterion.
        return {"left": self.left, "right": self.right, "modifier": self.modifier}


# ── OperatorFilter base ────────────────────────────────────────────────────

FilterType = TypeVar("FilterType", bound="OperatorFilter")


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
    "FieldComparisonCriterion": FieldComparisonCriterion,
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

# The dedicated field for field-to-field comparisons on every OperatorFilter.
# Kept separate from _OPERATOR_FIELDS (a fixed 3-tuple) so the operator-resolution
# logic is untouched; the from_json/to_json/apply paths branch on this name.
_COMPARISON_FIELD = "field_comparisons"


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


def _filter_class_for(
    cls: type["OperatorFilter"], field_name: str
) -> type["OperatorFilter"] | None:
    """Resolve the cross-entity sub-filter class declared for ``field_name`` on a
    filter, or None if the field is absent or isn't a sub-filter field.

    Mirrors ``_criterion_class_for`` but resolves the field's (string) annotation
    through ``_FILTER_TYPES`` — e.g. ``GameFilter.session_filter`` annotated
    ``"SessionFilter | None"`` resolves to ``SessionFilter``. The same-class
    AND/OR/NOT operator fields are deliberately excluded: they compose a filter
    with itself rather than crossing to another entity, and a widget path never
    steps through them."""
    if field_name in _OPERATOR_FIELDS:
        return None
    for dataclass_field in dc_fields(cls):
        if dataclass_field.name != field_name:
            continue
        field_type = dataclass_field.type
        if isinstance(field_type, str):
            # e.g. "SessionFilter | None" → "SessionFilter"
            field_type = field_type.split("|")[0].strip()
            return _FILTER_TYPES.get(field_type)
        if isinstance(field_type, type) and issubclass(field_type, OperatorFilter):
            return field_type
        return None
    return None


# A filter widget's canonical filter-JSON key chain: single-segment for a flat
# field (e.g. ["year_released"]), multi-segment for a cross-entity widget that
# steps through nested sub-filters (e.g. ["session_filter", "device"] or
# ["game_filter", "playevent_filter", "ended"]).
type FilterWidgetPath = list[str]

# The fixed child criterion of a relation-bool widget, keyed by the related field
# name. The serializer wraps it in the relation sub-filter (adding ``match: NONE``
# for the False radio).
type RelationChild = dict[
    str, dict[str, object]
]  # {"emulated": {"value": True, "modifier": "EQUALS"}}

# The widget ``data-kind`` tokens for leaf criteria — one token per value shape;
# several criterion types share a kind (every numeric criterion → "number"). These
# are the only kinds ``criterion_kind`` / ``resolve_path_kind`` ever produce, with
# one exception: ``"field-comparison"`` is registered to satisfy the
# _CRITERION_TYPES/_CRITERION_KINDS parity invariant but is never path-reachable —
# ``field_comparisons`` is a list field, so no path resolves to it (no widget yet).
type LeafWidgetKind = Literal["string", "number", "date", "bool", "set", "field-comparison"]

# Every widget ``data-kind`` token the filter-bar serializer dispatches on.
# ``relation-bool`` extends the leaf kinds: it describes not a leaf criterion but
# a whole cross-entity sub-filter toggled by a boolean radio (ANY vs NONE) over a
# fixed child criterion, so it is a valid widget kind yet never produced by the
# leaf resolvers above. See ``filter_widget_attributes`` and
# ``ts/elements/filter-bar.ts``.
type FilterWidgetKind = LeafWidgetKind | Literal["relation-bool"]

# The DB type "bucket" used to verify that two columns being compared
# field-to-field share the same kind (e.g. both "date", both "number").
# date and datetime are intentionally SEPARATE groups.
type ComparisonGroup = str  # e.g. "date"

_GROUP_BY_INTERNAL_TYPE: dict[str, ComparisonGroup] = {
    "DateField": "date",
    "DateTimeField": "datetime",
    "DurationField": "duration",
    "IntegerField": "number",
    "PositiveIntegerField": "number",
    "PositiveSmallIntegerField": "number",
    "SmallIntegerField": "number",
    "BigIntegerField": "number",
    "FloatField": "number",
    "DecimalField": "number",
    "CharField": "string",
    "TextField": "string",
    "BooleanField": "bool",
}


# Maps a criterion class to the widget ``data-kind`` token a filter-bar widget
# advertises for it (see ``filter_widget_attributes``). The server↔client
# contract: a widget's ``data-kind`` must equal the kind of the criterion its
# ``data-path`` resolves to. Several criterion types share a kind (every numeric
# criterion → "number"; both set criteria → "set").
_CRITERION_KINDS: dict[type[_Criterion], LeafWidgetKind] = {
    StringCriterion: "string",
    IntCriterion: "number",
    FloatCriterion: "number",
    AggregateCriterion: "number",
    DateCriterion: "date",
    BoolCriterion: "bool",
    MultiCriterion: "set",
    ChoiceCriterion: "set",
    FieldComparisonCriterion: "field-comparison",
}


def criterion_kind(criterion_cls: type[_Criterion]) -> LeafWidgetKind:
    """Return the widget ``data-kind`` token for a criterion class.

    Raises ``ValueError`` for a criterion type with no registered kind, so a new
    criterion class can't silently slip past the widget-contract check."""
    try:
        return _CRITERION_KINDS[criterion_cls]
    except KeyError:
        raise ValueError(
            f"No widget kind registered for criterion {criterion_cls.__name__}"
        ) from None


def resolve_path_kind(
    filter_cls: type["OperatorFilter"], path: FilterWidgetPath
) -> LeafWidgetKind:
    """Resolve a filter-widget ``data-path`` against a filter dataclass tree and
    return the expected ``data-kind``.

    Walks ``path[:-1]`` through cross-entity sub-filter fields (via
    ``_filter_class_for``), then resolves the final segment to a criterion (via
    ``_criterion_class_for``) and maps it to a kind (via ``criterion_kind``).
    Raises ``ValueError`` if the path is empty, a non-leaf segment isn't a
    sub-filter, or the leaf isn't a criterion — so a widget pointing at a
    non-existent path fails loudly. Used to guard the rendered server↔client
    widget contract (issue #123 Phase 2)."""
    if not path:
        raise ValueError("resolve_path_kind requires a non-empty path")
    current = filter_cls
    for segment in path[:-1]:
        sub_filter_cls = _filter_class_for(current, segment)
        if sub_filter_cls is None:
            raise ValueError(
                f"{current.__name__} has no sub-filter field {segment!r} "
                f"(resolving path {path})"
            )
        current = sub_filter_cls
    leaf = path[-1]
    criterion_cls = _criterion_class_for(current, leaf)
    if criterion_cls is None:
        raise ValueError(
            f"{current.__name__} has no criterion field {leaf!r} "
            f"(resolving path {path})"
        )
    return criterion_kind(criterion_cls)


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

    Each operator field is a *list* of sub-filters (n-ary boolean composition),
    so one node can compose several independent sub-filters — the prerequisite
    for AND-composing two uncorrelated EXISTS constraints over the same relation.
    Subclasses declare list-valued references to themselves::

        @dataclass
        class GameFilter(OperatorFilter):
            AND: list["GameFilter"] = field(default_factory=list)
            OR:  list["GameFilter"] = field(default_factory=list)
            NOT: list["GameFilter"] = field(default_factory=list)
            name: StringCriterion | None = None
            ...

    Application order (see ``_apply_operators``): this node's own criteria first,
    then each ``AND`` sub-filter (``&=``), then each ``OR`` (``|=``), then each
    ``NOT`` (``&= ~``). Mixing operator families on one node therefore composes
    left-to-right in that order; the common case keeps a node to a single
    operator family.

    ``match`` is the relation quantifier, meaningful only when this filter is
    nested as a cross-entity sub-filter (e.g. ``GameFilter.session_filter``):
    ANY (default), NONE, or ALL (ALL reserved — see ``relation_to_q``).
    ``relation_to_q`` reads it; at the top level it is ignored (``to_q`` never
    consults ``self.match``).
    """

    match: RelationMatch = RelationMatch.ANY

    # N-ary boolean composition: each operator is a list of sub-filters. Declared
    # on the base as ``Sequence["OperatorFilter"]`` so ``_apply_operators`` reads a
    # typed ``.to_q()`` while subclasses narrow to ``list[XFilter]`` (``Sequence``
    # is covariant, so the narrower override is accepted — a ``list[OperatorFilter]``
    # base would be rejected because ``list`` is invariant). Concrete filters
    # redeclare these with their own type — see games/filters.py.
    AND: Sequence["OperatorFilter"] = field(default_factory=list)
    OR: Sequence["OperatorFilter"] = field(default_factory=list)
    NOT: Sequence["OperatorFilter"] = field(default_factory=list)

    # Field-to-field comparisons: compare two columns of the filter's own model
    # (e.g. date_refunded < date_purchased).  Validated at to_q() time via
    # _comparison_model(); subclasses override that hook (T4).  Inherited by every
    # concrete filter with no re-declaration needed.
    field_comparisons: list[FieldComparisonCriterion] = field(default_factory=list)

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # Register concrete filter classes so from_json can resolve a
        # cross-entity sub-filter field's type by its annotation name.
        _FILTER_TYPES[cls.__name__] = cls

    @classmethod
    def where(cls: type[FilterType], **lookups: Any) -> FilterType:
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

    def _comparison_model(self) -> type[models.Model] | None:
        """The Django model whose columns ``field_comparisons`` reference.

        Returns None (this filter does not support field comparisons). Concrete
        filter subclasses override this to return their primary model — see T4.
        """
        return None

    def _apply_operators(self, q: Q) -> Q:
        """Compose this node's sub-filters onto ``q`` (which already holds this
        node's own criteria).

        Each operator field is a list, applied in order: every ``AND`` sub-filter
        is AND'd, every ``OR`` sub-filter is OR'd, every ``NOT`` sub-filter is
        AND'd-negated. Mixing families on one node composes left-to-right in that
        order (criteria → AND → OR → NOT); the common case uses one family.

        Field comparisons (``field_comparisons``) are validated here so errors
        surface on the ``to_q()`` path — preserving the "if it parses, to_q won't
        raise" guarantee when used via ``filter_from_json``.
        """
        for sub in self.AND:
            q &= sub.to_q()
        for sub in self.OR:
            q |= sub.to_q()
        for sub in self.NOT:
            q &= ~sub.to_q()
        if self.field_comparisons:
            model = self._comparison_model()
            if model is None:
                raise FilterError(
                    f"{type(self).__name__} does not support field comparisons"
                )
            for comparison in self.field_comparisons:
                if comparison.left == comparison.right:
                    raise FilterError(
                        f"field comparison needs two different columns"
                        f" (got {comparison.left!r} twice)"
                    )
                left_group = _comparison_group_for(model, comparison.left)
                right_group = _comparison_group_for(model, comparison.right)
                if left_group != right_group:
                    raise FilterError(
                        f"cannot compare {comparison.left!r} ({left_group})"
                        f" to {comparison.right!r} ({right_group})"
                    )
                if comparison.modifier not in _allowed_comparison_modifiers(left_group):
                    raise FilterError(
                        f"modifier {comparison.modifier} not allowed"
                        f" for {left_group} comparison"
                    )
                q &= comparison.to_q()
        return q

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
        return self._apply_operators(q)

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
                try:
                    kwargs["match"] = RelationMatch(raw)
                except ValueError as exc:
                    raise FilterError(f"Unknown relation match {raw!r}") from exc
                continue
            # Field-comparison list: parse each entry with FieldComparisonCriterion.
            # Mirrors the operator-field branch — null/absent → [], single item
            # wrapped to list, None results filtered out.
            if f.name == _COMPARISON_FIELD:
                if raw is None:
                    kwargs[f.name] = []
                else:
                    items = raw if isinstance(raw, list) else [raw]
                    parsed_comparisons = [
                        FieldComparisonCriterion.from_json(item) for item in items
                    ]
                    kwargs[f.name] = [
                        comparison
                        for comparison in parsed_comparisons
                        if comparison is not None
                    ]
                continue
            # Operator fields are list-valued; handle them before the generic
            # ``raw is None`` guard so a JSON ``null`` (or absent) operator
            # normalizes to ``[]`` and never violates the list invariant — leaving
            # it as ``None`` would crash ``_apply_operators``' iteration. A legacy
            # single object is tolerated by wrapping it as a one-element list;
            # None results (malformed entries) are filtered out.
            if f.name in _OPERATOR_FIELDS:
                if raw is None:
                    kwargs[f.name] = []
                    continue
                items = raw if isinstance(raw, list) else [raw]
                parsed = [cls.from_json(item) for item in items]
                kwargs[f.name] = [sub for sub in parsed if sub is not None]
                continue
            if raw is None:
                kwargs[f.name] = None
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
            # Field-comparison list: emit only when non-empty (mirrors operator fields).
            if f.name == _COMPARISON_FIELD:
                if v:
                    result[f.name] = [comparison.to_json() for comparison in v]
                continue
            # Operator fields are lists; emit a JSON array only when non-empty so
            # an unused operator stays out of the serialized form.
            if f.name in _OPERATOR_FIELDS:
                if v:
                    result[f.name] = [sub.to_json() for sub in v]
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


def filter_from_json(cls: type[FilterType], json_str: str) -> FilterType | None:
    """Deserialize and fully validate a filter from a JSON string.

    Usage:
        f = filter_from_json(GameFilter, request.GET.get("filter", ""))
        games = Game.objects.filter(f.to_q())

    Returns ``None`` for input that carries no filter: a missing param, JSON
    ``null``, or any non-object JSON value (``from_json`` rejects non-dicts).
    Raises ``FilterError`` for a filter that is present but invalid — malformed
    JSON, an unknown modifier/match enum, a missing/``null`` ``BETWEEN`` bound, a
    value of the wrong type for its field, etc. Callers (views/API) catch
    ``FilterError`` to degrade gracefully instead of 500-ing.

    Validation is eager: building the Q once here recurses through every
    AND/OR/NOT and cross-entity sub-filter (``relation_to_q`` calls each
    ``sub.to_q()``), so every criterion precondition and value-to-Q conversion is
    exercised. A ``ValueError``/``TypeError`` surfacing from a user value during
    that build (e.g. a non-integer game id, a non-numeric duration) is
    reclassified to ``FilterError`` — so if this returns, no later ``to_q()`` call
    on the result can raise. (A genuine wiring bug raises a non-``ValueError`` —
    see ``aggregate_to_q`` — and is intentionally *not* caught, so it still 500s.)

    Note: this guarantee is scoped to ``to_q()`` itself. A wrong-typed value that
    the database only rejects at query-execution time (e.g. a non-numeric
    ``year_released``) is not caught here — tracked in issue #157
    (parse-time value-type validation).
    """
    if not json_str:
        return None
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as exc:
        raise FilterError(f"Filter is not valid JSON: {exc}") from exc
    result = cls.from_json(data)
    if result is None:
        return None
    # Eager full-tree validation; discard the Q. A bad user *value* can make a
    # value-to-Q conversion raise ValueError/TypeError (int("x"), timedelta on a
    # str, min() against None); reclassify those to FilterError so the boundary
    # catches them. FilterError already re-raises as itself; non-ValueError
    # wiring bugs propagate untouched.
    try:
        result.to_q()
    except FilterError:
        raise
    except (ValueError, TypeError) as exc:
        raise FilterError(f"Invalid filter: {exc}") from exc
    return result


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
        if value is None or value2 is None:
            raise FilterError("BETWEEN requires two bounds (value and value2)")
        return Q(
            **{
                f"{field_name}__gte": min(value, value2),
                f"{field_name}__lte": max(value, value2),
            }
        )
    if modifier == Modifier.NOT_BETWEEN:
        if value is None or value2 is None:
            raise FilterError("NOT_BETWEEN requires two bounds (value and value2)")
        lower_bound, upper_bound = min(value, value2), max(value, value2)
        return Q(**{f"{field_name}__lt": lower_bound}) | Q(
            **{f"{field_name}__gt": upper_bound}
        )
    if modifier == Modifier.IS_NULL:
        return Q(**{f"{field_name}__isnull": True})
    if modifier == Modifier.NOT_NULL:
        return Q(**{f"{field_name}__isnull": False})
    raise FilterError(f"Unsupported modifier {modifier} for numeric comparison")


def _field_comparison_to_q(left: str, right: str, modifier: Modifier) -> Q:
    """Build a Q comparing two model columns: ``left <op> F(right)``.

    Used by field-to-field comparison criteria. Only the four ordered/equality
    modifiers are supported; anything else raises FilterError (the caller has
    already validated field existence and type-group — this only maps the operator).
    """
    if modifier == Modifier.EQUALS:
        return Q(**{left: F(right)})
    if modifier == Modifier.NOT_EQUALS:
        return ~Q(**{left: F(right)})
    if modifier == Modifier.GREATER_THAN:
        return Q(**{f"{left}__gt": F(right)})
    if modifier == Modifier.LESS_THAN:
        return Q(**{f"{left}__lt": F(right)})
    raise FilterError(f"Unsupported modifier {modifier} for field comparison")


def _comparison_group_for(model: type[models.Model], column: str) -> ComparisonGroup:
    """Resolve a model column's comparison group by DB type, or raise FilterError.

    Raises FilterError if the column does not exist, is a relation (FK/M2M/reverse),
    or is of a type with no comparison group (e.g. AutoField pk, JSONField).
    """
    try:
        model_field = model._meta.get_field(column)
    except FieldDoesNotExist:
        raise FilterError(f"{model.__name__} has no field {column!r}")

    if model_field.is_relation:
        raise FilterError(
            f"{model.__name__}.{column!r} is a relation and is not comparable"
        )

    if isinstance(model_field, models.GeneratedField):
        output_field = model_field.output_field
        if output_field is None:
            raise FilterError(
                f"{model.__name__}.{column!r} is a generated field with no output type"
            )
        internal_type = output_field.get_internal_type()
    else:
        internal_type = model_field.get_internal_type()

    group = _GROUP_BY_INTERNAL_TYPE.get(internal_type)
    if group is None:
        raise FilterError(
            f"{model.__name__}.{column!r} is not a comparable type ({internal_type})"
        )

    return group


def _allowed_comparison_modifiers(group: ComparisonGroup) -> list[Modifier]:
    """Modifiers valid for a comparison group: bool is equality-only; all others ordered."""
    if group == "bool":
        return [Modifier.EQUALS, Modifier.NOT_EQUALS]
    return Modifier.for_field_comparisons()


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
        if value is None or value2 is None:
            raise FilterError("BETWEEN requires two bounds (value and value2)")
        lower_bound = timedelta(hours=min(value, value2))
        upper_bound = timedelta(hours=max(value, value2))
        return Q(
            **{f"{field_name}__gte": lower_bound, f"{field_name}__lte": upper_bound}
        )
    if modifier == Modifier.NOT_BETWEEN:
        if value is None or value2 is None:
            raise FilterError("NOT_BETWEEN requires two bounds (value and value2)")
        lower_bound = timedelta(hours=min(value, value2))
        upper_bound = timedelta(hours=max(value, value2))
        return Q(**{f"{field_name}__lt": lower_bound}) | Q(
            **{f"{field_name}__gt": upper_bound}
        )
    if modifier == Modifier.IS_NULL:
        return Q(**{field_name: timedelta(0)})
    if modifier == Modifier.NOT_NULL:
        return ~Q(**{field_name: timedelta(0)})
    raise FilterError(f"Unsupported modifier {modifier} for duration comparison")


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
    raise FilterError(f"Unsupported relation match {sub.match!r}")


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

    # ``reducer``/``source`` are hard-coded by each filter's own to_q(), never
    # user input — a failure here is a wiring bug. Raise RuntimeError (not
    # ValueError) so filter_from_json's eager-validation catch does NOT reclassify
    # it to FilterError: a real bug must still 500, not masquerade as bad input.
    if reducer == "count":
        aggregate_expression: Any = Count(accessor, distinct=True)
    elif reducer in ("sum", "avg"):
        if source is None:
            raise RuntimeError(f"{reducer!r} aggregate requires a source field")
        reduce = Sum if reducer == "sum" else Avg
        aggregate_expression = reduce(f"{accessor}__{source}")
    else:
        raise RuntimeError(f"Unknown aggregate reducer {reducer!r}")

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
