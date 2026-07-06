"""
Typed criterion inputs for building structured filters.

Inspired by Stash's filter architecture: every filterable field uses a typed
criterion with a value and a CriterionModifier. This separates *what* you're
filtering from *how* you're comparing, and makes filter serialization trivial.
"""

import json
import types
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from dataclasses import dataclass, field, fields as dc_fields
from enum import Enum
from typing import (
    Any,
    ClassVar,
    Literal,
    Self,
    TypedDict,
    TypeVar,
    Union,
    get_args,
    get_origin,
    get_type_hints,
)

from django.core.exceptions import FieldDoesNotExist
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import ExtractYear, TruncDate

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
    GREATER_THAN_OR_EQUAL = "GREATER_THAN_OR_EQUAL"
    LESS_THAN_OR_EQUAL = "LESS_THAN_OR_EQUAL"
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
    def for_ordered_field_comparisons(cls) -> list[Self]:
        """Equality + ordering — valid for every comparable group (numeric/date/string)."""
        return [
            cls.EQUALS,
            cls.NOT_EQUALS,
            cls.GREATER_THAN,
            cls.LESS_THAN,
            cls.GREATER_THAN_OR_EQUAL,
            cls.LESS_THAN_OR_EQUAL,
        ]

    @classmethod
    def for_field_comparisons(cls) -> list[Self]:
        """Full field-comparison vocabulary: ordering + string containment (string-only)."""
        return [*cls.for_ordered_field_comparisons(), cls.INCLUDES, cls.EXCLUDES]


# ── Relation match-mode ──────────────────────────────────────────────────────


class RelationMatch(str, Enum):
    """Quantifier for a nested cross-entity sub-filter (e.g. a game's sessions).

    A dedicated vocabulary (rather than reusing ``Modifier``) so only the three
    meaningful quantifiers are representable. ``relation_to_q`` interprets it.
    """

    ANY = "ANY"  # ≥1 related row matches the sub-filter (EXISTS)
    NONE = "NONE"  # no related row matches (NOT EXISTS); includes zero-row parents
    ALL = "ALL"  # every related row matches; vacuously true for zero-row parents


# ── Value coercers ───────────────────────────────────────────────────────────
# Parse-time value validators (issue #157). A criterion declares one via its
# ``_coerce`` hook; ``from_json`` applies it so a wrong-typed hand-edited
# ``?filter=`` value raises ``FilterError`` at parse rather than escaping the
# error boundary and 500-ing when the DB rejects it at query-execution time.
# Each returns the coerced value or raises ``FilterError`` (a ``ValueError``,
# caught by the boundary).


# An ``int``/``float``/ISO-date coercer for a criterion's value (raises
# ``FilterError`` on mismatch). Used as a criterion's ``_coerce`` hook.
type Coercer = Callable[[Any], Any]  # e.g. _coerce_int


def _coerce_int(raw: Any) -> int:
    # Reject what ``int()`` would silently *accept and rewrite* rather than flag as
    # the wrong type: a JSON bool (``int(True) == 1``) and a non-integral float
    # (``int(3.9) == 3``). Both are wrong-typed input #157 means to surface.
    if isinstance(raw, bool) or (isinstance(raw, float) and not raw.is_integer()):
        raise FilterError(f"expected an integer, got {raw!r}")
    try:
        return int(raw)
    except (ValueError, TypeError) as exc:
        raise FilterError(f"expected an integer, got {raw!r}") from exc


def _coerce_float(raw: Any) -> float:
    # Reject JSON bool (``float(True) == 1.0``); a boolean is not a numeric bound.
    if isinstance(raw, bool):
        raise FilterError(f"expected a number, got {raw!r}")
    try:
        return float(raw)
    except (ValueError, TypeError) as exc:
        raise FilterError(f"expected a number, got {raw!r}") from exc


def _coerce_number(raw: Any) -> int | float:
    # For fields that may be integer (a count) or fractional (a sum/avg): validate
    # numerically but keep an integral value an ``int`` so a count round-trips as
    # ``5`` rather than ``5.0`` in serialized filter JSON. Querying is unaffected.
    number = _coerce_float(raw)
    return int(number) if number.is_integer() else number


def _strip_set_label(item: Any) -> Any:
    """Reduce a set-criterion element to its bare id. Widgets send ``{id, label}``
    dicts (label is display-only); a hand-edited dict missing ``id`` is bad input
    and raises ``FilterError`` rather than a boundary-bypassing ``KeyError``."""
    if not isinstance(item, dict):
        return item
    if "id" not in item:
        raise FilterError(f"set filter element is missing an id: {item!r}")
    return item["id"]


def _coerce_date(raw: Any) -> str:
    # Keep the ISO string (``to_q`` passes it to ``Q``; the DB parses it); only
    # validate that it is one, so a bad date is rejected here, not at eval.
    if not isinstance(raw, str):
        raise FilterError(f"expected an ISO date string, got {raw!r}")
    try:
        date.fromisoformat(raw)
    except ValueError as exc:
        raise FilterError(f"expected an ISO date string, got {raw!r}") from exc
    return raw


# ── Base criterion ─────────────────────────────────────────────────────────

T = TypeVar("T")


@dataclass
class _Criterion:
    """Base for all typed criteria."""

    value: Any = None
    modifier: Modifier = Modifier.EQUALS

    # Parse-time value validator (issue #157); ``None`` accepts the value as-is
    # (string/bool/choice — never a 500 vector). Concrete classes whose value
    # has a field-column type (int/float/date) set one of the ``_coerce_*``
    # helpers; ``from_json`` applies it so a wrong-typed hand-edited value raises
    # ``FilterError`` at parse instead of escaping to a query-execution 500.
    # ``_ScalarCriterion`` enforces that its scalar subclasses set one.
    _coerce: ClassVar[Coercer | None] = None

    def to_q(self, field_name: str) -> Q:
        raise NotImplementedError

    @classmethod
    def from_json(cls, data: dict | None) -> Self | None:
        if data is None or not isinstance(data, dict):
            return None
        kwargs: dict[str, Any] = {}
        for f in dc_fields(cls):
            if not f.init:
                continue
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
class _ScalarCriterion(_Criterion):
    """Base for criteria whose ``value``/``value2`` are single field-column values
    (int / float / date). Applies the class ``_coerce`` validator at parse so a
    wrong-typed hand-edited value raises ``FilterError`` here, not as a 500 when
    the DB rejects it at query-execution time (issue #157)."""

    value2: Any = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        # The whole point of a scalar criterion is that its value has a column type
        # to validate. A subclass that forgets ``_coerce`` silently reverts to the
        # pre-#157 500 vector, so fail at class-definition time instead.
        super().__init_subclass__(**kwargs)
        if cls._coerce is None:
            raise TypeError(f"{cls.__name__} must set a _coerce validator (issue #157)")

    def to_json(self) -> dict[str, Any]:
        # ``value`` carries the criterion's payload; at the type default (0 / 0.0 /
        # "") the base to_json drops it, silently losing a meaningful EQUALS-0 (free
        # price, zero-duration session, "0 sessions" aggregate — issue #223).
        # Force-emit it, like BoolCriterion/FieldComparisonCriterion. ``value2``
        # (None default = no second bound) and ``modifier`` (EQUALS default) stay
        # base-handled: both re-parse to the same default, so omitting them is
        # lossless and keeps existing filter JSON byte-stable.
        result = super().to_json()
        result["value"] = self.value
        return result

    @classmethod
    def from_json(cls, data: dict | None) -> Self | None:
        result = super().from_json(data)
        # ``result`` is non-None only when ``data`` was a dict (base contract).
        if result is None or cls._coerce is None:
            return result
        # Presence tests ignore the value entirely (and widgets emit a placeholder
        # ``value: ""`` for them), so skip coercion — the value never reaches to_q.
        if result.modifier in (Modifier.IS_NULL, Modifier.NOT_NULL):
            return result
        coerce = cls._coerce
        # Coerce every non-None value/value2: ``None`` is the DB-safe sentinel (an
        # explicit null or a missing BETWEEN bound — compiled to IS NULL or caught
        # by the BETWEEN guard), but a non-None default *can* be invalid (the
        # DateCriterion ``""`` default with a value-using modifier), so it must be
        # validated too rather than gated on user-supplied-ness. (Finding #157.)
        for key in ("value", "value2"):
            if getattr(result, key) is not None:
                setattr(result, key, coerce(getattr(result, key)))
        return result


@dataclass
class StringCriterion(_Criterion):
    value: str = ""
    modifier: Modifier = Modifier.EQUALS

    def to_json(self) -> dict[str, Any]:
        # "unset" is the criterion being absent at the filter level (field is None),
        # never a magic empty value — so a present StringCriterion with value=="" is
        # a meaningful EQUALS "" match and must serialize. The base to_json drops it
        # (value == default). Force-emit, mirroring the scalar #223 fix and
        # BoolCriterion/FieldComparisonCriterion. ``modifier`` (EQUALS default)
        # stays base-handled: it re-parses to the same default, byte-stable.
        result = super().to_json()
        result["value"] = self.value
        return result

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
            # String fields in this codebase use blank=True, default="" (null=False),
            # so "empty" means either SQL NULL or an empty string. Both are matched here
            # so the criterion works correctly regardless of the field's null setting.
            return Q(**{f"{field_name}__isnull": True}) | Q(
                **{f"{field_name}__exact": ""}
            )
        if m == Modifier.NOT_NULL:
            # Logical complement of IS_NULL: neither NULL nor empty string.
            return ~(
                Q(**{f"{field_name}__isnull": True}) | Q(**{f"{field_name}__exact": ""})
            )
        raise FilterError(f"Unsupported modifier {m} for string field")


@dataclass
class IntCriterion(_ScalarCriterion):
    value: int = 0
    value2: int | None = None
    modifier: Modifier = Modifier.EQUALS
    _coerce: ClassVar[Coercer | None] = staticmethod(_coerce_int)

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
class FloatCriterion(_ScalarCriterion):
    value: float = 0.0
    value2: float | None = None
    modifier: Modifier = Modifier.EQUALS
    _coerce: ClassVar[Coercer | None] = staticmethod(_coerce_float)

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
class DateCriterion(_ScalarCriterion):
    value: str = ""
    value2: str | None = None
    modifier: Modifier = Modifier.EQUALS
    _coerce: ClassVar[Coercer | None] = staticmethod(_coerce_date)

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

    # Display-only id -> label map. THE place where embedded set labels are
    # documented (issue #224).
    #
    # Set pills (platform/game/device) need a human label to render; the id
    # alone ("5") is meaningless to the user. UI-built filters carry the label
    # inline as ``{id, label}`` dicts (see ``ts/elements/filter-widgets.ts``); a
    # filter built server-side (stats-page links) only knows the id, so it stashes
    # the labels it has here and ``to_json`` folds them back into the ``{id, label}``
    # wire shape. The filter bar then prefills labelled pills straight from the URL
    # JSON with no extra DB round-trip.
    #
    # Labels are PURELY cosmetic: ``to_q`` reads only ``value``/``excludes``/
    # ``modifier`` and never touches ``labels``, and ``from_json`` strips labels
    # back to bare ids. So they never change which rows a filter matches; the one
    # trade-off is that a label can go stale if the underlying record is renamed
    # after the link/preset was created (the pill shows the old name until the link
    # is regenerated). ``compare=False`` keeps two criteria with the same ids but
    # different labels equal.
    labels: dict = field(default_factory=dict, compare=False)

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
            q &= self._not_in_q(field_name, self.excludes)
        return q

    @staticmethod
    def _not_in_q(field_name: str, values: list) -> Q:
        """Negative membership that explicitly matches NULL rows. Raw SQL
        ``NOT IN`` is never true for NULL, but Django's negated-lookup
        compilation already adds an ``IS NOT NULL`` guard that keeps NULL rows
        — this arm states "exclude platform X keeps platformless games" in the
        Q tree itself rather than leaving it to ORM negation internals. The
        isnull arm is vacuous on non-nullable columns."""
        return ~Q(**{f"{field_name}__in": values}) | Q(
            **{f"{field_name}__isnull": True}
        )

    def _value_q(self, field_name: str) -> Q:
        """Build the Q for the include (``value``) set, per the modifier."""
        modifier = self.modifier
        if modifier in (Modifier.INCLUDES, Modifier.EQUALS):
            return Q(**{f"{field_name}__in": self.value}) if self.value else Q()
        if modifier in (Modifier.EXCLUDES, Modifier.NOT_EQUALS):
            return self._not_in_q(field_name, self.value) if self.value else Q()
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
        # ``value``/``excludes`` must be JSON arrays (the widget sends id/code lists).
        # The base from_json assigns the raw JSON value verbatim, so validate the type
        # and bound the length before the per-element comprehensions below:
        #  - a null normalizes to ``[]`` (mirrors the AND/OR/NOT None->[] handling);
        #  - any other non-list (a scalar, string, or dict) is bad input — reject it
        #    here, else ``_strip_set_label`` iterates it: a non-iterable scalar 500s
        #    (TypeError escapes the FilterError boundary) and a string is silently
        #    split into characters (a quietly-wrong filter);
        #  - a 300k-element list would drive a 300k-iteration strip + coerce, so a
        #    tiny blob amplifies into an expensive parse + Q build (DoS, issue #204).
        for field_name in ("value", "excludes"):
            field_value = getattr(result, field_name)
            if field_value is None:
                setattr(result, field_name, [])
                continue
            if not isinstance(field_value, list):
                raise FilterError(f"Filter set {field_name} must be a list")
            if len(field_value) > MAX_SET_VALUES:
                raise FilterError(f"Filter set list too long (max {MAX_SET_VALUES})")
        # Labels embedded as {id, label} dicts are display-only; strip to bare ids
        # so the querying layer stays clean and typed. A hand-edited dict without
        # an ``id`` is bad input — raise FilterError (not a bare KeyError, which
        # would bypass the boundary and 500).
        result.value = [_strip_set_label(item) for item in result.value]
        result.excludes = [_strip_set_label(item) for item in result.excludes]
        # Coerce each element against the field-column type (issue #157), so an
        # int-set field (MultiCriterion) rejects a wrong-typed id at parse rather
        # than letting ``field__in=["xyz"]`` 500 at query execution. ChoiceCriterion
        # leaves ``_coerce`` None: its string-code fields (status, ownership_type,
        # group, …) run against char columns and never 500. The one id-bearing
        # ChoiceCriterion, PurchaseFilter.games (M2M int ids), is made 500-safe
        # separately by _games_to_q's explicit int() coercion, not here.
        if cls._coerce is not None:
            coerce = cls._coerce
            result.value = [coerce(item) for item in result.value]
            result.excludes = [coerce(item) for item in result.excludes]
        return result

    def _labelled(self, item: Any) -> Any:
        """Fold a known label back into the ``{id, label}`` wire shape (#224).

        Returns the bare id when no label is known, so unlabelled criteria
        serialize exactly as before.
        """
        label = self.labels.get(item)
        return {"id": item, "label": label} if label else item

    def to_json(self) -> dict[str, Any]:
        # Overrides (does NOT mirror) the base ``to_json``: because ``value`` /
        # ``excludes`` use ``default_factory``, the base never treats an empty
        # list as the default, so it would leak ``"value": []`` / ``"excludes":
        # []`` and a raw ``"labels": {}`` key onto the wire. This skips empty
        # lists, never emits ``labels`` as its own key (labels are folded inline
        # per ``_labelled``), and — like the base — omits the default modifier.
        result: dict[str, Any] = {}
        if self.value:
            result["value"] = [self._labelled(item) for item in self.value]
        if self.excludes:
            result["excludes"] = [self._labelled(item) for item in self.excludes]
        if self.modifier != Modifier.INCLUDES:
            result["modifier"] = self.modifier
        return result


@dataclass
class MultiCriterion(_SetCriterion):
    """Filter on a many-to-many or ForeignKey relationship by ID list.

    All modifier logic (including ``INCLUDES_ALL`` and ``EXCLUDES``) lives in
    ``_SetCriterion``; this subclass only refines the value type.
    """

    value: list[int] = field(default_factory=list)
    excludes: list[int] = field(default_factory=list)
    labels: dict[int, str] = field(default_factory=dict, compare=False)
    _coerce: ClassVar[Coercer | None] = staticmethod(_coerce_int)


@dataclass
class ChoiceCriterion(_SetCriterion):
    """Filter on a choice/enum field with multi-select include/exclude.

    Used by FilterSelect widgets for status, ownership_type, etc. Shares all
    modifier logic with ``MultiCriterion`` via ``_SetCriterion``.
    """

    value: list[str] = field(default_factory=list)
    excludes: list[str] = field(default_factory=list)
    labels: dict[str, str] = field(default_factory=dict, compare=False)


@dataclass
class AggregateCriterion(_ScalarCriterion):
    """Filter a parent entity by a reducer (count / sum / avg) over one of its
    relations, compared numerically — e.g. "games with > 5 sessions" or "sum of
    a game's purchase prices between X and Y".

    The reducer, relation accessor, source field, and unit are *static config*
    declared on the filter class (its ``aggregates`` table of ``AggregateSpec``,
    read by ``aggregate_to_q``); the instance carries only the user's comparison
    value(s)/modifier and an optional ``scope`` sub-filter narrowing which
    related rows the reducer sees (issue #151) — e.g. "> 5 sessions *on the
    Steam Deck*" counts only sessions matching ``scope``.
    """

    value: int | float = 0
    value2: int | float | None = None
    modifier: Modifier = Modifier.EQUALS
    # Scope sub-filter over the related rows being reduced. ``init=False`` keeps
    # it out of the base ``from_json`` field loop — the criterion alone cannot
    # resolve the concrete filter class (that is fixed by the relation accessor's
    # ``AggregateSpec``, which lives on the filter class), so only
    # ``OperatorFilter._aggregate_from_json`` may populate it. Re-adding this as
    # an init field would recreate the mis-typed dead field #139/#144 removed.
    # Beware: ``dataclasses.replace()`` re-defaults ``init=False`` fields, so a
    # replaced criterion silently loses its scope — mutate the attribute instead.
    scope: "OperatorFilter | None" = field(default=None, init=False)
    # Aggregates compare numerically; coerce so a wrong-typed bound is caught at
    # parse rather than surfacing as a query-execution 500 (the eager build can't
    # catch it: ``aggregate_to_q`` feeds the value straight into Q). ``_coerce_number``
    # keeps an integral count an int so it round-trips as ``5``, not ``5.0``.
    _coerce: ClassVar[Coercer | None] = staticmethod(_coerce_number)

    def to_q(self, field_name: str) -> Q:
        # Unlike sibling criteria, an aggregate is not self-contained: its meaning
        # depends on static config (reducer/relation/source/unit) the filter holds.
        # It is evaluated via aggregate_to_q(...), never this method.
        raise NotImplementedError(
            "AggregateCriterion is evaluated via aggregate_to_q(), not to_q()"
        )

    def to_json(self) -> dict[str, Any]:
        # The base loop would emit the raw ``scope`` OperatorFilter object;
        # replace it with its JSON, omitting an empty scope — an empty sub-filter
        # matches every related row, so "no scope" is the canonical form.
        result = super().to_json()
        result.pop("scope", None)
        if self.scope is not None:
            scope_json = self.scope.to_json()
            if scope_json:
                result["scope"] = scope_json
        return result


# A non-raw comparison space (#169): a query-time projection under which
# operands of different DB groups become comparable. "raw" is deliberately not
# a space — it means "compare columns as-is" and requires both operands to
# share a group (special-cased in _apply_operators).
type ComparisonSpace = Literal["date", "year"]

type ComparisonGranularity = ComparisonSpace | Literal["raw"]

# The operand groups each comparison space accepts. In "date" space datetime
# operands are projected to calendar dates; in "year" space temporal operands
# are projected to their year and compared as numbers. Exported to TS as a
# typed const by `manage.py gen_element_types` (ts/generated/filter-metadata.ts,
# issue #284), so the field-comparison widget consumes this table directly
# rather than a hand-kept mirror.
SPACE_GROUPS: dict[ComparisonSpace, frozenset[ComparisonGroup]] = {
    "date": frozenset({"date", "datetime"}),
    "year": frozenset({"date", "datetime", "number"}),
}


@dataclass
class FieldComparisonCriterion(_Criterion):
    """Compare one model column to another (``left <op> right``) via F() expressions.

    ``left`` and ``right`` are model column names (resolved + type-checked against
    the filter's model by the base OperatorFilter before to_q runs). Operands are
    self-contained; ``to_q`` is not callable directly — use
    ``OperatorFilter._apply_operators``, which resolves operand groups and then
    calls ``_field_comparison_to_q`` with the required ``left_group``/``right_group``
    keyword arguments.

    NULL semantics are strict two-valued (#169): every Q carries explicit
    ``__isnull=False`` guards on both operand paths, so a row matches only when
    both operands exist and the predicate holds — for every modifier, on either
    side. This is deliberately independent of Django's declared-nullability guard
    injection (which is asymmetric for join-introduced NULLs) and supersedes the
    previous NULL-counts-as-not-equal NOT_EQUALS behavior.

    Empty-string note: an empty ``right`` (``""``, not NULL) is a substring of
    every non-NULL ``left``, so INCLUDES then matches all rows with a non-NULL
    ``left``.

    Granularity / comparison spaces: each non-``"raw"`` value defines a *space*
    whose accepted operand groups are listed in ``SPACE_GROUPS``.
    ``"date"`` space truncates datetime operands to calendar day at query time
    (``left__date <op> TruncDate(F(right))``) using the active timezone —
    accepts ``date`` and ``datetime`` operands.
    ``"year"`` space projects temporal operands to their year and compares as
    numbers (``left__year <op> ExtractYear(F(right))`` / vice-versa) —
    accepts ``date``, ``datetime``, and ``number`` operands.
    ``"raw"`` (the default) compares columns as-is; both operands must share
    the same comparison group.
    Non-raw spaces restrict modifiers to ``for_ordered_field_comparisons()``
    (no string-containment INCLUDES/EXCLUDES).
    """

    # Shadow the inherited `value` field: FieldComparisonCriterion has no
    # user-supplied value (operands are `left`/`right`).  init=False keeps
    # it out of __init__ and from_json iteration, preventing a stray JSON
    # "value" key from being accepted and creating a roundtrip asymmetry.
    value: Any = field(default=None, init=False, repr=False)
    left: ComparisonOperand = ""
    right: ComparisonOperand = ""
    modifier: Modifier = Modifier.EQUALS
    granularity: ComparisonGranularity = "raw"

    def to_q(self, field_name: str = "") -> Q:
        # Static mis-wiring, never user input: comparisons are built by
        # OperatorFilter._apply_operators, which resolves operand groups
        # against the filter's model first.
        raise RuntimeError(
            "FieldComparisonCriterion.to_q needs model context;"
            " build it via OperatorFilter._apply_operators"
        )

    def to_json(self) -> dict[str, Any]:
        # left/right default to "" — the base to_json would drop them. Force-emit, like BoolCriterion.
        payload: dict[str, Any] = {
            "left": self.left,
            "right": self.right,
            "modifier": self.modifier,
        }
        # Emit granularity only when non-default to keep existing filter JSON byte-compatible.
        if self.granularity != "raw":
            payload["granularity"] = self.granularity
        return payload

    @classmethod
    def from_json(cls, data: dict | None) -> Self | None:
        # Validate granularity here (the base loop assigns it verbatim, like any
        # field) so an unknown value is rejected at parse time rather than
        # silently degrading to a raw comparison — mirrors the modifier coercion.
        # Derived from SPACE_GROUPS so a new space is accepted the moment it is
        # added to the table, not when someone remembers this check.
        result = super().from_json(data)
        if result is not None and result.granularity not in ("raw", *SPACE_GROUPS):
            raise FilterError(f"unknown granularity {result.granularity!r}")
        return result


# ── Field descriptors ──────────────────────────────────────────────────────

type AttrName = str  # a filter dataclass field name, e.g. "playtime_hours"
type ORMLookup = str  # a Django query path, e.g. "platform__group"

# A custom criterion→Q builder for a filter field whose mapping is not a plain
# ``criterion.to_q(lookup)`` — e.g. hours→duration conversion or a bool
# presence/zero test. Built by the factories below (see ``duration_hours_handler``).
type FieldHandler = Callable[[_Criterion], Q]


@dataclass(frozen=True)
class FilterField:
    """Declarative attr→ORM-lookup mapping for one filter field.

    Lifts the per-field mapping a filter's ``to_q`` used to do imperatively into a
    single declarative table (see ``OperatorFilter.fields``). ``lookup`` overrides
    the ORM path (defaulting to the attribute name, so a plain field needs no
    argument); ``handler`` supplies bespoke Q logic for fields whose mapping is not
    a plain ``criterion.to_q(lookup)`` — the hours→duration and bool
    presence/zero cases. The two are mutually exclusive: a handler is fully
    self-contained, so a ``lookup`` alongside it would be silently ignored —
    ``__post_init__`` rejects that misconfiguration at import time.
    """

    lookup: ORMLookup | None = None
    handler: FieldHandler | None = None
    # Human label for the field-metadata registry (``field_metadata``). Optional;
    # when None, the registry falls back to a title-cased field name.
    label: str | None = None
    # Widget config consumed by ``field_metadata`` → ``field_widget`` (issue #242),
    # never by ``to_q``. ``search_url`` names the endpoint a set field fetches its
    # options from on demand — model-backed FKs/M2Ms *and* dynamic value lists like
    # platform groups (None → static-enum set field, or a non-set field).
    # ``imperative`` marks a field whose value widget belongs in the table but whose
    # Q is built in ``_extra_q`` (the M2M ``games``), so ``to_q`` must skip it — see
    # ``OperatorFilter.to_q``. Declared after ``label`` so existing positional
    # ``FilterField("lookup")`` calls are unaffected.
    search_url: str | None = None
    imperative: bool = False

    def __post_init__(self) -> None:
        # Same loud-at-import contract as the lookup/handler check: reject the
        # config combinations whose widget/Q axes silently cancel each other, so a
        # misconfigured field fails on load rather than degrading at query/render.
        if self.lookup is not None and self.handler is not None:
            raise ValueError("FilterField takes lookup OR handler, not both")
        if self.imperative and self.handler is not None:
            # ``to_q`` skips imperative fields, so the handler would never run.
            raise ValueError(
                "FilterField imperative fields build their Q in _extra_q; "
                "a handler would be dead code"
            )
        if self.imperative and self.lookup is None:
            # ``field_metadata`` needs the lookup to resolve the field's column for
            # the widget (choices / nullable / is_m2m); without it the imperative
            # field surfaces in the picker resolving to nothing.
            raise ValueError(
                "FilterField imperative=True needs a lookup so field_metadata "
                "can build its widget"
            )
        if self.search_url is not None and self.handler is not None:
            # Handler-mapped fields skip column resolution, so search_url (a
            # set-field widget input) has no consumer.
            raise ValueError(
                "FilterField search_url has no effect on a handler-mapped field"
            )

    def to_q(self, attr_name: AttrName, criterion: _Criterion) -> Q:
        if self.handler is not None:
            return self.handler(criterion)
        return criterion.to_q(self.lookup or attr_name)


# ── OperatorFilter base ────────────────────────────────────────────────────


# Canonical registry of every concrete criterion class, by name. Field-type
# resolution no longer consults it (that is introspection now — see
# ``_field_types``); it remains the single source of truth for the
# ``_CRITERION_TYPES``↔``_CRITERION_KINDS`` parity invariant (tests/test_filter_paths.py),
# so a new criterion class can't slip in without being given a widget kind.
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

# The three sub-filter composition fields, shared by every OperatorFilter.
_OPERATOR_FIELDS: tuple[str, str, str] = ("AND", "OR", "NOT")

# The dedicated field for field-to-field comparisons on every OperatorFilter.
# Kept separate from _OPERATOR_FIELDS (a fixed 3-tuple) so the operator-resolution
# logic is untouched; the from_json/to_json/apply paths branch on this name.
_COMPARISON_FIELD = "field_comparisons"

# Max OperatorFilter nesting depth accepted from a hand-edited/shared ``?filter=``.
# Each from_json frame (one AND/OR/NOT level OR one relation descent) = one unit, so
# this counts the same nesting the builder bounds with its UI soft cap of 5. Both
# operator groups and relation descents draw from this single budget, so this 10 is
# 2x headroom over that cap — a filter built within the UI's nesting limit is not
# rejected in practice — while a pathologically deep / cyclic blob (relation fields
# cycle, e.g. GameFilter.session_filter <-> SessionFilter.game_filter) raises
# FilterError at parse instead of recursing into a RecursionError/500 or a runaway
# nested-subquery build (DoS). See issue #186.
MAX_FILTER_DEPTH = 10

# Max breadth (sibling-list length) accepted from a hand-edited/shared ``?filter=``.
# The depth guard above bounds *nesting*, not *width*: a shallow-but-very-wide blob
# (e.g. ``{"AND": [<10 000 sub-filters>]}`` or a 300k-element ``INCLUDES`` id array)
# is otherwise bounded only by ``DATA_UPLOAD_MAX_MEMORY_SIZE`` (2.5 MB), yet each
# sibling/value becomes its own criterion/subquery — so a tiny blob still amplifies
# into an expensive parse + Q build (CPU/memory DoS). These caps remove that
# amplification; the byte limit caps the substance. Reachable un-capped via a stored
# FilterPreset blob (URL-length limits don't apply). Values are generous headroom
# over any realistic hand-built filter. See issue #204.
MAX_FILTER_BREADTH = 100  # max entries per AND/OR/NOT operator list
MAX_FIELD_COMPARISONS = 100  # max entries in a field_comparisons list
MAX_SET_VALUES = 1000  # max entries per set-criterion value / excludes list


# Per-class cache for ``_field_types`` (these resolvers sit on the hot from_json /
# where / resolve_path_kind paths). Keyed by the filter class; a class is created
# once, so this never grows unbounded. A plain dict rather than ``functools.cache``
# because the dataclass ``__hash__`` confuses the cache decorator's type signature.
_FIELD_TYPES_CACHE: dict[type[OperatorFilter], dict[str, type]] = {}


def _field_types(cls: type[OperatorFilter]) -> dict[str, type]:
    """Resolved (Optional-unwrapped) type of each dataclass field on a filter class.

    Built on ``typing.get_type_hints`` so a stringized annotation (PEP 563 /
    explicit forward ref) and a live ``X | None`` object resolve identically —
    correctness no longer depends on a module's ``from __future__ import
    annotations``. A union ``X | None`` is unwrapped to its single non-None
    member; a non-union generic (``list[...]``) is left as-is so a list field
    (``field_comparisons``, ``AND``/``OR``/``NOT``) is never misread as a
    criterion. Cached per class.
    """
    cached = _FIELD_TYPES_CACHE.get(cls)
    if cached is not None:
        return cached
    hints = get_type_hints(cls)
    resolved: dict[str, type] = {}
    for dataclass_field in dc_fields(cls):
        hint = hints.get(dataclass_field.name)
        if hint is None:
            continue
        if get_origin(hint) in (Union, types.UnionType):
            non_none = [arg for arg in get_args(hint) if arg is not type(None)]
            if len(non_none) == 1:
                hint = non_none[0]
        resolved[dataclass_field.name] = hint
    _FIELD_TYPES_CACHE[cls] = resolved
    return resolved


def _criterion_class_for(
    cls: type[OperatorFilter], field_name: str
) -> type[_Criterion] | None:
    """Resolve the criterion class declared for ``field_name`` on a filter, or
    None if the field is absent or isn't a criterion field.

    Reads the field's resolved annotation via ``_field_types`` (real type objects,
    not annotation strings), so a list/sub-filter field — whose resolved hint is a
    generic alias or an ``OperatorFilter`` subclass, not a ``_Criterion`` — yields
    None."""
    hint = _field_types(cls).get(field_name)
    if isinstance(hint, type) and issubclass(hint, _Criterion):
        return hint
    return None


def _filter_class_for(
    cls: type[OperatorFilter], field_name: str
) -> type[OperatorFilter] | None:
    """Resolve the cross-entity sub-filter class declared for ``field_name`` on a
    filter, or None if the field is absent or isn't a sub-filter field.

    Mirrors ``_criterion_class_for`` over ``_field_types`` — e.g.
    ``GameFilter.session_filter`` annotated ``SessionFilter | None`` resolves to
    ``SessionFilter``. The same-class AND/OR/NOT operator fields are deliberately
    excluded: they compose a filter with itself rather than crossing to another
    entity, and a widget path never steps through them."""
    if field_name in _OPERATOR_FIELDS:
        return None
    hint = _field_types(cls).get(field_name)
    if isinstance(hint, type) and issubclass(hint, OperatorFilter):
        return hint
    return None


# A filter widget's canonical filter-JSON key chain: single-segment for a flat
# field (e.g. ["year_released"]), multi-segment for a cross-entity widget that
# steps through nested sub-filters (e.g. ["session_filter", "device"] or
# ["game_filter", "playevent_filter", "ended"]).
type FilterWidgetPath = list[str]

# The widget ``data-kind`` tokens for leaf criteria — one token per value shape;
# several criterion types share a kind (every numeric criterion → "number"). These
# are the only kinds ``criterion_kind`` / ``resolve_path_kind`` ever produce, with
# one exception: ``"field-comparison"`` is registered to satisfy the
# _CRITERION_TYPES/_CRITERION_KINDS parity invariant but is never path-reachable —
# ``field_comparisons`` is a list field, so no path resolves to it (the builder's
# comparison leaves carry their own row markup instead).
type LeafWidgetKind = Literal[
    "string", "number", "date", "bool", "set", "field-comparison"
]

# The DB type "bucket" used to verify that two columns being compared
# field-to-field share the same kind (e.g. both "date", both "number").
# date and datetime are intentionally SEPARATE groups.
type ComparisonGroup = Literal[
    "date", "datetime", "duration", "number", "string", "bool"
]

_GROUP_BY_INTERNAL_TYPE: dict[str, ComparisonGroup] = {
    "DateField": "date",
    "DateTimeField": "datetime",
    "DurationField": "duration",
    "IntegerField": "number",
    "PositiveIntegerField": "number",
    "PositiveSmallIntegerField": "number",
    "PositiveBigIntegerField": "number",
    "SmallIntegerField": "number",
    "BigIntegerField": "number",
    "FloatField": "number",
    "DecimalField": "number",
    "CharField": "string",
    "TextField": "string",
    "SlugField": "string",  # SlugField.get_internal_type() is "SlugField", not "CharField"
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
    filter_cls: type[OperatorFilter], path: FilterWidgetPath
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


type Reducer = Literal["count", "sum", "avg"]  # e.g. "count"
type DurationUnit = Literal["duration_hours"]  # compare hours vs a DurationField
type RelationAccessor = str  # a relation accessor on the parent model, e.g. "sessions"


@dataclass(frozen=True)
class AggregateSpec:
    """Static wiring for one aggregate criterion field (issue #151): how to
    reduce (``reducer``), over which relation (``accessor``), and which filter
    type scopes the reduced rows (``scope_filter`` — e.g. ``SessionFilter`` for
    a ``sessions`` aggregate).

    The criterion instance carries only the user's comparison (and optional
    ``scope`` sub-filter); this spec is the per-field static half, declared on
    the filter class's ``aggregates`` table. ``scope_filter`` is what lets
    ``from_json`` resolve the scope's concrete class — the criterion's own
    annotation cannot name it (the abstract ``OperatorFilter`` says nothing
    about *which* entity the accessor reaches). It doubles as the related-model
    resolver for the scope subquery (via ``_comparison_model()``).
    """

    reducer: Reducer
    accessor: RelationAccessor
    scope_filter: "type[OperatorFilter]"
    source: AttrName | None = None  # summed/averaged related column; None for count
    unit: DurationUnit | None = None

    def __post_init__(self) -> None:
        # The reducer/source/unit dependencies are cross-field invariants the
        # annotations can't say; specs are module-level constants, so validating
        # here turns a mis-wired table into an import-time failure instead of a
        # query-time 500 on first use.
        if self.reducer == "count":
            if self.source is not None:
                raise TypeError("a count aggregate takes no source field")
            if self.unit is not None:
                raise TypeError("a count aggregate takes no unit")
        elif self.source is None:
            raise TypeError(f"a {self.reducer} aggregate requires a source field")


@dataclass
class OperatorFilter:
    """Mixin providing AND/OR/NOT composition for entity filter types.

    Each operator field is a *list* of sub-filters (n-ary boolean composition),
    so one node can compose several independent sub-filters — the prerequisite
    for AND-composing two uncorrelated EXISTS constraints over the same relation.
    Subclasses declare list-valued references to themselves::

        @dataclass
        class GameFilter(OperatorFilter):
            AND: list[GameFilter] = field(default_factory=list)
            OR:  list[GameFilter] = field(default_factory=list)
            NOT: list[GameFilter] = field(default_factory=list)
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
    # on the base as ``Sequence[OperatorFilter]`` so ``_apply_operators`` reads a
    # typed ``.to_q()`` while subclasses narrow to ``list[XFilter]`` (``Sequence``
    # is covariant, so the narrower override is accepted — a ``list[OperatorFilter]``
    # base would be rejected because ``list`` is invariant). Concrete filters
    # redeclare these with their own type — see games/filters.py.
    AND: Sequence[OperatorFilter] = field(default_factory=list)
    OR: Sequence[OperatorFilter] = field(default_factory=list)
    NOT: Sequence[OperatorFilter] = field(default_factory=list)

    # Field-to-field comparisons: compare two columns of the filter's own model
    # (e.g. date_refunded < date_purchased).  Validated at to_q() time via
    # _comparison_model(); subclasses override that hook (T4).  Inherited by every
    # concrete filter with no re-declaration needed.
    field_comparisons: list[FieldComparisonCriterion] = field(default_factory=list)

    # Declarative attr→lookup table consumed by the generic ``to_q``. Each concrete
    # filter overrides this with a ``FilterField`` per simple criterion field (the
    # single source of truth for the ORM mapping); aggregates are absent (they live
    # in the ``aggregates`` table below); M2M, ``search`` and relation sub-filters
    # live in ``_extra_q``. Declared as a ClassVar so the dataclass machinery does
    # not treat it as a field.
    fields: ClassVar[dict[AttrName, FilterField]] = {}

    # Declarative reducer/relation wiring per aggregate criterion field, consumed
    # by the generic ``to_q`` walk and by ``from_json`` (an aggregate's ``scope``
    # deserializes via its spec's ``scope_filter`` — issue #151). Empty on the
    # base; a concrete filter with aggregate fields assigns its table *after* all
    # filter classes exist (the specs reference sibling filter classes) — see
    # ``GameFilter.aggregates`` in games/filters.py.
    aggregates: ClassVar[Mapping[AttrName, AggregateSpec]] = {}

    # Criterion fields deliberately handled imperatively in ``_extra_q`` rather than
    # via ``fields`` (e.g. the M2M ``games``). ``search`` is here for every filter.
    # The drift-guard test (tests/test_filters.py) asserts ``fields`` plus this set
    # plus the aggregate-typed fields partitions every criterion field.
    _IMPERATIVE_CRITERIA: ClassVar[set[str]] = {"search"}

    # Human labels for the field-metadata registry, keyed by field name. A home for
    # labels of fields outside ``fields`` (aggregates, the M2M ``games``) without
    # touching the field-partition invariant; ``fields`` entries carry their own
    # ``FilterField.label``. Empty by default — ``field_metadata`` falls back to a
    # title-cased field name. Populated with exact strings when the field picker
    # (issue #168) is built. Subclasses override per field.
    labels: ClassVar[dict[AttrName, str]] = {}

    @classmethod
    def where(cls, **lookups: Any) -> Self:
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

    @classmethod
    def _comparison_model(cls) -> type[models.Model] | None:
        """The Django model whose columns ``field_comparisons`` reference.

        Returns None (this filter does not support field comparisons). Concrete
        filter subclasses override this to return their primary model — see T4.
        A classmethod so the field-metadata registry can resolve filter→model
        without instantiating (``field_metadata``); ``self``-call sites are
        unaffected (classmethods are callable on instances).
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
                left_group = _comparison_operand_group(
                    model, comparison.left, side="left"
                )
                right_group = _comparison_operand_group(
                    model, comparison.right, side="right"
                )
                if comparison.granularity == "raw":
                    if left_group != right_group:
                        raise FilterError(
                            f"cannot compare {comparison.left!r} ({left_group})"
                            f" to {comparison.right!r} ({right_group})"
                        )
                    allowed_modifiers = _allowed_comparison_modifiers(left_group)
                    vocabulary_hint = f"{left_group} comparison"
                else:
                    accepted_groups = SPACE_GROUPS[comparison.granularity]
                    for operand, group in (
                        (comparison.left, left_group),
                        (comparison.right, right_group),
                    ):
                        if group not in accepted_groups:
                            raise FilterError(
                                f"{operand!r} ({group}) cannot take part in a"
                                f" {comparison.granularity}-granularity comparison"
                            )
                    allowed_modifiers = Modifier.for_ordered_field_comparisons()
                    vocabulary_hint = f"{comparison.granularity}-granularity comparison"
                if comparison.modifier not in allowed_modifiers:
                    raise FilterError(
                        f"modifier {comparison.modifier} not allowed"
                        f" for {vocabulary_hint}"
                    )
                q &= _field_comparison_to_q(
                    comparison.left,
                    comparison.right,
                    comparison.modifier,
                    comparison.granularity,
                    left_group=left_group,
                    right_group=right_group,
                )
        return q

    def to_q(self) -> Q:
        """Build a Django Q object from this filter and its sub-filters.

        Generic for every concrete filter: walk the declarative ``fields`` table
        (each set criterion mapped to its ORM lookup/handler), then the
        ``aggregates`` table, then fold in the imperative tail (``_extra_q``:
        M2M, free-text search, relation sub-filters), then the AND/OR/NOT
        operators and field comparisons.
        """
        q = Q()
        for attr_name, descriptor in self.fields.items():
            # ``imperative`` fields carry widget config in the table but build
            # their Q in ``_extra_q`` (e.g. the M2M ``games``) — skip them here so
            # the criterion is not double-applied.
            if descriptor.imperative:
                continue
            criterion = getattr(self, attr_name)
            if criterion is not None:
                q &= descriptor.to_q(attr_name, criterion)
        if self.aggregates:
            model = self._comparison_model()
            if model is None:
                # Static mis-wiring, never user input — 500, don't FilterError.
                raise RuntimeError(
                    f"{type(self).__name__} declares aggregates but no comparison model"
                )
            for attr_name, spec in self.aggregates.items():
                aggregate = getattr(self, attr_name)
                if aggregate is not None:
                    q &= aggregate_to_q(aggregate, model=model, spec=spec)
        q &= self._extra_q()
        return self._apply_operators(q)

    def _extra_q(self) -> Q:
        """Q for criterion fields handled imperatively rather than via ``fields``.

        Default is empty; concrete filters override to add the M2M ``games``
        handler, free-text ``search``, and relation sub-filters. Kept a
        separate hook so the generic ``to_q`` never needs overriding.
        """
        return Q()

    @classmethod
    def from_json(cls, data: dict[str, Any] | None, *, _depth: int = 0) -> Self | None:
        if data is None or not isinstance(data, dict):
            return None
        # Cap nesting before recursing: a hand-edited/shared cyclic ``?filter=`` would
        # otherwise parse into an unbounded tree and DoS the server (see MAX_FILTER_DEPTH).
        # ``_depth`` is incremented at the two recursion sites below: the AND/OR/NOT
        # operator list and the cross-entity relation descent (both consume the budget).
        if _depth > MAX_FILTER_DEPTH:
            raise FilterError(f"Filter nesting too deep (max {MAX_FILTER_DEPTH})")
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
            # null/absent → [], single dict wrapped to list.  Unlike AND/OR/NOT
            # sub-filters (where a silently-dropped entry tightens the filter),
            # a dropped *leaf* comparison silently weakens it — returning MORE rows
            # than intended.  So non-dict entries and unparseable dicts raise
            # FilterError rather than being silently dropped.
            if f.name == _COMPARISON_FIELD:
                if raw is None:
                    kwargs[f.name] = []
                else:
                    items = raw if isinstance(raw, list) else [raw]
                    if len(items) > MAX_FIELD_COMPARISONS:
                        raise FilterError(
                            f"Filter field_comparisons list too long"
                            f" (max {MAX_FIELD_COMPARISONS})"
                        )
                    parsed_comparisons: list[FieldComparisonCriterion] = []
                    for item in items:
                        if not isinstance(item, dict):
                            raise FilterError(
                                f"field_comparisons entries must be dicts,"
                                f" got {type(item).__name__!r}"
                            )
                        comparison = FieldComparisonCriterion.from_json(item)
                        if comparison is None:
                            raise FilterError(
                                f"field_comparisons entry could not be parsed: {item!r}"
                            )
                        parsed_comparisons.append(comparison)
                    kwargs[f.name] = parsed_comparisons
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
                # Bound breadth before recursing: a shallow-but-wide operator list
                # (``{"AND": [<10 000 sub-filters>]}``) builds one Q per sibling and
                # amplifies a tiny blob into an expensive parse (DoS, issue #204).
                if len(items) > MAX_FILTER_BREADTH:
                    raise FilterError(
                        f"Filter operator list too long (max {MAX_FILTER_BREADTH})"
                    )
                parsed = [cls.from_json(item, _depth=_depth + 1) for item in items]
                kwargs[f.name] = [sub for sub in parsed if sub is not None]
                continue
            if raw is None:
                kwargs[f.name] = None
                continue
            # Resolve the field's declared type by introspection (shared with
            # ``where``/``resolve_path_kind``), so a criterion field and a
            # cross-entity sub-filter field dispatch identically regardless of
            # whether the module stringizes its annotations.
            criterion_cls = _criterion_class_for(cls, f.name)
            if criterion_cls is not None:
                # Aggregate fields carry an optional ``scope`` sub-filter whose
                # concrete class only the field's AggregateSpec knows — split it
                # off and parse it here rather than in the criterion (issue #151).
                if f.name in cls.aggregates and isinstance(raw, dict):
                    kwargs[f.name] = cls._aggregate_from_json(f.name, raw, _depth)
                    continue
                kwargs[f.name] = (
                    criterion_cls.from_json(raw) if isinstance(raw, dict) else None
                )
                continue
            # Cross-entity sub-filter field (e.g. game_filter, playevent_filter):
            # resolve the filter class and recurse.
            sub_filter_cls = _filter_class_for(cls, f.name)
            if sub_filter_cls is not None:
                kwargs[f.name] = (
                    sub_filter_cls.from_json(raw, _depth=_depth + 1)
                    if isinstance(raw, dict)
                    else None
                )
        return cls(**kwargs)

    @classmethod
    def _aggregate_from_json(
        cls, name: AttrName, raw: dict[str, Any], _depth: int
    ) -> AggregateCriterion | None:
        """Parse one aggregate criterion dict, including its optional ``scope``.

        ``scope`` is split off before the generic criterion parse (the field is
        ``init=False``, so the base loop could never mis-assign the raw dict) and
        deserialized via the field's ``AggregateSpec.scope_filter`` — only the
        filter class knows which concrete filter type scopes the aggregate's
        relation (issue #151). The scope descent consumes the same
        ``MAX_FILTER_DEPTH`` budget as a relation descent, so a scope-nesting
        bomb is bounded identically.
        """
        payload = dict(raw)
        scope_raw = payload.pop("scope", None)
        criterion_cls = _criterion_class_for(cls, name)
        if criterion_cls is None or not issubclass(criterion_cls, AggregateCriterion):
            # ``aggregates`` names a non-aggregate field: static mis-wiring the
            # drift guard should have caught — 500, don't FilterError.
            raise RuntimeError(
                f"{cls.__name__}.aggregates[{name!r}] is not an AggregateCriterion field"
            )
        criterion = criterion_cls.from_json(payload)
        if criterion is None or scope_raw is None:
            return criterion
        if not isinstance(scope_raw, dict):
            raise FilterError(
                f"aggregate scope must be an object, got {type(scope_raw).__name__}"
            )
        scope = cls.aggregates[name].scope_filter.from_json(
            scope_raw, _depth=_depth + 1
        )
        if scope is not None and scope.match != RelationMatch.ANY:
            # A scope is a row predicate over the reduced relation, not a
            # relation test: a quantifier here would be silently meaningless
            # (which rows would NONE/ALL count?), so reject rather than ignore.
            raise FilterError("aggregate scope does not take a match quantifier")
        if scope is not None and not scope.to_json():
            # An empty scope matches every related row — normalize to unscoped so
            # parse → serialize round-trips to the canonical omitted form.
            scope = None
        criterion.scope = scope
        return criterion

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


def filter_from_json[F: OperatorFilter](cls: type[F], json_str: str) -> F | None:
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

    Wrong-typed *values* are caught even earlier (issue #157): each criterion's
    ``from_json`` coerces/validates its value against the field-column type (int /
    float / ISO date / int-id set), raising ``FilterError`` at parse — so a value
    the database would only reject at query-execution time (e.g. a non-numeric
    ``year_released``) never reaches the DB. The eager ``to_q()`` build below then
    covers the remaining structural conversions (BETWEEN bounds, M2M id coercion
    in ``_games_to_q``, hours→timedelta).
    """
    if not json_str:
        return None
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as exc:
        raise FilterError(f"Filter is not valid JSON: {exc}") from exc
    except RecursionError as exc:
        # ``json.loads`` recurses per nesting level and overflows the C stack on a
        # deeply-nested blob *before* OperatorFilter.from_json's MAX_FILTER_DEPTH
        # guard can run. Reclassify to FilterError so the same deep/cyclic ``?filter=``
        # DoS (issue #186) is caught here too, not just post-parse — otherwise this
        # RecursionError escapes the view's FilterError boundary and 500s. Reachable
        # un-capped via a stored FilterPreset blob (URL-length limits don't apply).
        raise FilterError("Filter nesting too deep") from exc
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
# Self-contained Q builders for the two cross-entity node kinds. Callers pass the
# related/parent model and the wiring (relation lookups, or the aggregate's
# ``AggregateSpec``); the algebra lives here so every entity composes the same
# logic instead of repeating bespoke subqueries in each to_q().

Number = int | float


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


def _field_comparison_to_q(
    left: str,
    right: str,
    modifier: Modifier,
    granularity: ComparisonGranularity = "raw",
    *,
    left_group: ComparisonGroup,
    right_group: ComparisonGroup,
) -> Q:
    """Build a Q comparing two operands: ``left <op> right`` in the row's space.

    Operands may be one-hop relation paths (``game__year_released``); the ORM
    joins for a lookup path on the left and for ``F("relation__column")`` on the
    right, and both operands on one relation share a single join.

    Space projection: ``date`` truncates datetime operands to calendar day
    (``__date`` / ``TruncDate``), ``year`` extracts the year from temporal
    operands (``__year`` / ``ExtractYear``) so they compare against numbers.

    NULL semantics are strict two-valued (#169): every Q carries explicit
    ``__isnull=False`` guards on both operand paths, so a row matches only when
    both operands exist and the predicate holds — for every modifier, on either
    side. This is deliberately independent of Django's declared-nullability
    guard injection (which is asymmetric for join-introduced NULLs) and
    supersedes the previous NULL-counts-as-not-equal NOT_EQUALS behavior.
    """
    temporal_groups = ("date", "datetime")
    left_base = left
    right_expr: F | TruncDate | ExtractYear = F(right)
    if granularity == "date":
        if left_group == "datetime":
            left_base = f"{left}__date"
        if right_group == "datetime":
            right_expr = TruncDate(F(right))
    elif granularity == "year":
        if left_group in temporal_groups:
            left_base = f"{left}__year"
        if right_group in temporal_groups:
            right_expr = ExtractYear(F(right))

    guards = Q(**{f"{left}__isnull": False}) & Q(**{f"{right}__isnull": False})
    if modifier == Modifier.EQUALS:
        return Q(**{left_base: right_expr}) & guards
    if modifier == Modifier.NOT_EQUALS:
        return ~Q(**{left_base: right_expr}) & guards
    if modifier == Modifier.GREATER_THAN:
        return Q(**{f"{left_base}__gt": right_expr}) & guards
    if modifier == Modifier.LESS_THAN:
        return Q(**{f"{left_base}__lt": right_expr}) & guards
    if modifier == Modifier.GREATER_THAN_OR_EQUAL:
        return Q(**{f"{left_base}__gte": right_expr}) & guards
    if modifier == Modifier.LESS_THAN_OR_EQUAL:
        return Q(**{f"{left_base}__lte": right_expr}) & guards
    if modifier == Modifier.INCLUDES:
        return Q(**{f"{left_base}__icontains": right_expr}) & guards
    if modifier == Modifier.EXCLUDES:
        return ~Q(**{f"{left_base}__icontains": right_expr}) & guards
    raise FilterError(f"Unsupported modifier {modifier} for field comparison")


def _maybe_group_for(model: type[models.Model], column: str) -> ComparisonGroup | None:
    """Classify a model column into a comparison group, or None if non-comparable.

    Returns None — never raises — for every column that has no comparison group:
    the column does not exist, is a relation (FK/M2M/reverse), is a GeneratedField
    with no resolvable output type, or is of a type absent from
    ``_GROUP_BY_INTERNAL_TYPE`` (e.g. AutoField pk, JSONField).

    This is the single source of truth for the classification; the raising
    ``_comparison_group_for`` wraps it, and ``comparable_columns`` enumerates with
    it (so enumeration never has to drive off exceptions).
    """
    try:
        model_field = model._meta.get_field(column)
    except FieldDoesNotExist:
        return None

    if model_field.is_relation:
        return None

    if isinstance(model_field, models.GeneratedField):
        output_field = model_field.output_field
        if output_field is None:
            return None
        internal_type = output_field.get_internal_type()
    else:
        internal_type = model_field.get_internal_type()

    return _GROUP_BY_INTERNAL_TYPE.get(internal_type)


def _comparison_group_for(model: type[models.Model], column: str) -> ComparisonGroup:
    """Resolve a model column's comparison group by DB type, or raise FilterError.

    Thin raising wrapper over ``_maybe_group_for``: where that returns None, this
    raises FilterError with a message describing why the column is not comparable
    (does not exist, is a relation, is a GeneratedField with no output type, or is
    of a type with no comparison group such as AutoField pk / JSONField).
    """
    try:
        model_field = model._meta.get_field(column)
    except FieldDoesNotExist as exc:
        raise FilterError(f"{model.__name__} has no field {column!r}") from exc

    if model_field.is_relation:
        raise FilterError(
            f"{model.__name__}.{column!r} is a relation and is not comparable"
        )

    if (
        isinstance(model_field, models.GeneratedField)
        and model_field.output_field is None
    ):
        raise FilterError(
            f"{model.__name__}.{column!r} is a generated field with no output type"
        )

    group = _maybe_group_for(model, column)
    if group is None:
        internal_type = model_field.get_internal_type()
        raise FilterError(
            f"{model.__name__}.{column!r} is not a comparable type ({internal_type})"
        )

    return group


type ComparisonOperand = (
    str  # own column "playtime" or one-hop FK path "game__year_released"
)


def _comparison_operand_group(
    model: type[models.Model], operand: ComparisonOperand, *, side: str
) -> ComparisonGroup:
    """Resolve a comparison operand to its group, enforcing the operand grammar.

    Grammar (#169): a bare comparable column, or exactly one forward to-one FK
    hop (``relation__column``). M2M and reverse relations are rejected — ``F()``
    across a multi-valued relation fans out rows (see the spec's follow-up
    issue for Exists()-based semantics). Terminal classification is delegated
    to ``_comparison_group_for`` against the related model, so type-group
    gating and its error vocabulary stay single-sourced. ``side`` ("left"/
    "right") only decorates error messages.
    """
    segments = operand.split("__")
    if len(segments) == 1:
        return _comparison_group_for(model, operand)
    if len(segments) > 2:
        raise FilterError(
            f"{side} operand {operand!r} traverses more than one relation"
            f" (one hop allowed)"
        )
    relation, column = segments
    try:
        relation_field = model._meta.get_field(relation)
    except FieldDoesNotExist as exc:
        raise FilterError(
            f"{side} operand {operand!r}: {model.__name__} has no relation {relation!r}"
        ) from exc
    if not isinstance(relation_field, (models.ForeignKey, models.OneToOneField)):
        raise FilterError(
            f"{side} operand {operand!r}: {model.__name__}.{relation}"
            f" is not a to-one relation (only forward FK hops are comparable)"
        )
    try:
        return _comparison_group_for(relation_field.related_model, column)
    except FilterError as exc:
        raise FilterError(f"{side} operand {operand!r}: {exc}") from exc


type ModifierValue = str  # a Modifier.value, e.g. "INCLUDES"


class ComparableColumn(TypedDict):
    """A comparison-operand option, ready for a picker: operand value, human
    label, comparison group, allowed raw-space operators, and the source
    optgroup it renders under."""

    value: ComparisonOperand  # "timestamp_end" or "game__year_released"
    label: str  # own: "Timestamp End"; related: "Base Game: Year Released"
    group: ComparisonGroup
    operators: list[ModifierValue]  # valid for this column's group, raw space (#152)
    source: str  # optgroup label: model verbose name for own columns, FK verbose name for related columns


def _comparison_relations(
    model: type[models.Model],
) -> list[tuple[str, type[models.Model], str]]:
    """The forward to-one FKs comparison operands may traverse, introspected
    (never configured): ``(fk_name, related_model, title-cased verbose name)``
    per concrete ForeignKey/OneToOneField, in ``_meta`` declaration order.
    The same acceptance rule ``_comparison_operand_group`` validates against.
    """
    relations: list[tuple[str, type[models.Model], str]] = []
    for model_field in model._meta.get_fields():
        if (
            isinstance(model_field, (models.ForeignKey, models.OneToOneField))
            and model_field.concrete
            and model_field.related_model is not None
        ):
            relations.append(
                (
                    model_field.name,
                    model_field.related_model,
                    str(model_field.verbose_name).title(),
                )
            )
    return relations


def _own_comparable_columns(
    model: type[models.Model],
    *,
    prefix: str = "",
    source: str = "",
) -> list[ComparableColumn]:
    """The comparable columns of ``model``, optionally prefixed and sourced.

    ``prefix`` is prepended to each ``value`` (e.g. ``"game__"`` for FK-hop
    entries).  ``source`` is stored on each entry as the optgroup label.
    When ``prefix`` is non-empty (i.e. these are related-model columns) the
    source is also prepended to each ``label`` as ``f"{source}: {label}"`` to
    qualify them — own-model columns (no prefix) always carry bare labels.
    Sorted alphabetically by label (case-insensitive) within the block.
    """
    columns: list[ComparableColumn] = []
    for model_field in model._meta.get_fields():
        column = model_field.name
        group = _maybe_group_for(model, column)
        if group is None:
            continue
        verbose_name = getattr(model_field, "verbose_name", column)
        raw_label: str = verbose_name.title()
        label = f"{source}: {raw_label}" if prefix else raw_label
        columns.append(
            ComparableColumn(
                value=f"{prefix}{column}",
                label=label,
                group=group,
                # Send the allowed operators as data so the TS widget renders them
                # directly instead of re-deriving the group->operators mapping (#152).
                operators=[
                    modifier.value for modifier in _allowed_comparison_modifiers(group)
                ],
                source=source,
            )
        )
    columns.sort(key=lambda entry: entry["label"].lower())
    return columns


def comparable_columns(model: type[models.Model]) -> list[ComparableColumn]:
    """Every comparable column of ``model`` and its forward to-one FK targets,
    labelled and grouped, with a ``source`` discriminator for optgroup rendering.

    Own columns come first, sorted alphabetically by label, with ``source`` set
    to the model's title-cased verbose name (e.g. "Session").  Then one block
    per forward FK in ``_meta`` declaration order — each block sorted
    alphabetically by its column label, with ``source`` set to the FK's
    title-cased verbose name.  No global re-sort across blocks.

    ``source`` is always non-empty: own columns carry the model's verbose name
    and related columns carry the FK's verbose name — every source renders as
    an optgroup label.  Own-column labels are NOT prefixed (label
    qualification is keyed off the ``prefix`` param in
    ``_own_comparable_columns``, not off ``source``).

    Relations, reverse relations, M2M, the pk/AutoField, GeneratedFields without
    an output type, and JSONField all classify to None in ``_maybe_group_for``
    and are excluded.  The same one-hop grammar that ``_comparison_operand_group``
    enforces is what ``_comparison_relations`` enumerates — they stay in sync by
    sharing the same FK acceptance predicate.
    """
    own_source = str(model._meta.verbose_name).title()
    columns = _own_comparable_columns(model, source=own_source)
    for fk_name, related_model, fk_source in _comparison_relations(model):
        columns.extend(
            _own_comparable_columns(
                related_model, prefix=f"{fk_name}__", source=fk_source
            )
        )
    return columns


# ── Field-metadata registry (issue #187) ───────────────────────────────────
# The per-model source of truth the nested filter builder's add-criterion field
# picker, leaf widget, and relation-descent picker read (issue #168). Builds on
# the existing resolvers (``_criterion_class_for``, ``_filter_class_for``,
# ``criterion_kind``) and adds the missing label / choices / nullable / relation
# enumeration. Pure Python — JSON/codegen exposure is deferred to #152.

type FieldMetaKind = LeafWidgetKind | Literal["relation"]
type ModelName = str  # a Django model class name, e.g. "Session"
type ModelKey = str  # a Django model _meta.model_name, e.g. "session"
type FilterClassName = str  # an OperatorFilter subclass name, e.g. "SessionFilter"
type ModifierToken = str  # a Modifier value, e.g. "EQUALS"


class ChoiceMeta(TypedDict):
    """One static-enum option for a filter field (status, ownership_type, …)."""

    value: str  # stored value, e.g. "f"
    label: str  # human label, e.g. "Finished"


class RelationTarget(TypedDict):
    """The target a relation-descent field points at, for the relation picker."""

    field: AttrName  # the sub-filter attr, e.g. "session_filter"
    filter: FilterClassName  # target filter class name, e.g. "SessionFilter"
    model: ModelName  # target model name, e.g. "Session"


class FieldMeta(TypedDict):
    """Everything a picker needs to render one filterable field. ``choices`` is
    populated only for static-enum fields; ``relations`` is non-empty (a single
    entry) iff ``kind == "relation"``, and a relation entry always has empty
    ``choices``, empty ``modifiers``, and ``nullable=False``. A leaf entry always
    has a non-empty ``modifiers``. ``scope_model`` is non-empty iff the field is
    an aggregate (issue #151). These cross-field invariants are enforced by
    ``field_metadata`` (the sole producer), not by the type."""

    name: AttrName
    label: str
    kind: FieldMetaKind
    nullable: bool
    choices: list[ChoiceMeta]
    # Ordered, nullable-filtered modifier vocabulary for this field. The FIRST
    # entry is the reset default the add-criterion field picker (#191) selects on
    # field change; the whole list is what the modifier dropdown (#192) renders. A
    # relation entry always has empty ``modifiers`` (it carries no leaf criterion).
    modifiers: list[ModifierToken]
    relations: list[RelationTarget]
    # Value-widget config for ``field_widget`` (issue #242). ``search_url`` is the
    # endpoint a ``set`` field fetches its options from on demand (model-backed
    # FKs/M2Ms and dynamic value lists like platform groups); "" means a
    # static-enum set field (``field_widget`` dispatches it via ``choices``) or a
    # non-set field (dispatched by ``kind``). ``is_m2m`` is True only for true
    # many-to-many set fields (surfaces ``(All)``/``(Only)`` modifiers); derived
    # from the resolved model field, not stored on ``FilterField``.
    search_url: str
    is_m2m: bool
    # The model key (``_meta.model_name``, e.g. "session") of the related rows an
    # aggregate field reduces — the model whose fields build the aggregate's
    # ``scope`` sub-filter (issue #151). ``""`` for every non-aggregate field.
    scope_model: ModelKey


class ModelFieldBundle(TypedDict):
    """One model's client-side filter metadata: its leaf/relation ``field_metadata``
    plus its ``comparable_columns``. The nested builder (#193) carries one bundle per
    relation-reachable model so a relation's child group renders offline from the
    target model's fields — see ``games.filters.model_field_registry``."""

    fields: list[FieldMeta]
    columns: list[ComparableColumn]


def _resolve_model_field(
    model: type[models.Model], lookup: ORMLookup
) -> models.Field | None:
    """Resolve a filter field's ORM ``lookup`` to its terminal concrete model field.

    Walks ``__``-separated segments, descending into the related model at each
    relation segment, and stops at the first non-relation field — so a trailing
    transform such as ``created_at__date`` returns the ``created_at`` field and a
    relation hop such as ``platform__group`` returns ``Platform.group``. A
    single-segment FK attname (``platform_id``) resolves directly (Django accepts
    attnames). Returns None when a segment does not resolve (e.g. a mis-typed
    lookup, or an aggregate field name that is no column); the caller decides
    whether that None is expected (columnless field) or a misconfiguration to
    raise on. Handler-mapped fields never reach here — ``field_metadata`` skips
    them upstream.
    """
    current = model
    segments = lookup.split("__")
    for index, segment in enumerate(segments):
        try:
            model_field = current._meta.get_field(segment)
        except FieldDoesNotExist:
            return None
        is_last = index == len(segments) - 1
        if model_field.is_relation and not is_last:
            related = model_field.related_model
            if related is None:
                return None
            current = related
            continue
        # First non-relation field, or a terminal relation/FK: this is the field.
        # Any remaining segments are transforms (e.g. ``__date``) and are ignored.
        return model_field if isinstance(model_field, models.Field) else None
    return None


def _static_choices(model_field: models.Field | None) -> list[ChoiceMeta]:
    """Static enum ``(value, label)`` pairs for a model field, or ``[]``.

    Only fields with declared ``choices`` (status, ownership_type, type) yield
    entries; FK/M2M/free-text fields have no choices and are left to the dynamic
    relation picker.
    """
    choices = getattr(model_field, "choices", None)
    if not choices:
        return []
    return [ChoiceMeta(value=str(value), label=str(label)) for value, label in choices]


def _modifiers_for_field(kind: FieldMetaKind, nullable: bool) -> list[ModifierToken]:
    """Ordered modifier vocabulary for a leaf field of the given kind.

    Reuses the ``Modifier.for_*`` lists (the single home for "which operators a
    value shape allows") keyed by leaf kind, so the field picker's reset default
    (first entry) and the modifier dropdown (#192) never duplicate a per-kind
    table on the client. ``IS_NULL``/``NOT_NULL`` are dropped for a non-nullable
    field — a column that can't be NULL has no meaningful presence test.
    """
    by_kind: dict[FieldMetaKind, list[Modifier]] = {
        "string": Modifier.for_strings(),
        "number": Modifier.for_numbers(),
        "date": Modifier.for_dates(),
        "set": Modifier.for_multi(),
        "bool": [Modifier.EQUALS, Modifier.NOT_EQUALS],
    }
    modifiers = by_kind.get(kind, [])
    if not nullable:
        modifiers = [
            modifier
            for modifier in modifiers
            if modifier not in (Modifier.IS_NULL, Modifier.NOT_NULL)
        ]
    return [modifier.value for modifier in modifiers]


def _field_label(filter_cls: type[OperatorFilter], name: AttrName) -> str:
    """Human label for a filter field: explicit ``FilterField.label`` →
    ``filter_cls.labels`` override → title-cased field name.

    ``verbose_name`` is deliberately not consulted: a nested lookup like
    ``platform_group`` would surface ``Platform.group``'s verbose_name ("group"),
    losing the relation context, whereas the field name gives "Platform Group".
    The field name is the stable identifier; exact display strings are filled in
    on ``FilterField.label`` / ``labels`` as the field picker (issue #168) lands.
    """
    field_spec = filter_cls.fields.get(name)
    if field_spec is not None and field_spec.label is not None:
        return field_spec.label
    override = filter_cls.labels.get(name)
    if override is not None:
        return override
    return name.replace("_", " ").title()


# Memoization for field_metadata: the result is pure class/model introspection
# (dataclass fields + Django _meta), identical for a given filter class for the
# process lifetime — and per-field callers (field_widget's _field_meta, the
# quick bar's facet loop) re-invoke it many times per request. An explicit dict
# rather than lru_cache: mypy rejects `type[X]` against _lru_cache_wrapper's
# Hashable parameters. Callers treat the returned list/dicts as READ-ONLY;
# mutating them would poison this shared cache.
_FIELD_METADATA_CACHE: dict[type[OperatorFilter], list[FieldMeta]] = {}


def field_metadata(filter_cls: type[OperatorFilter]) -> list[FieldMeta]:
    """Per-field filter metadata for ``filter_cls`` — the source of truth the
    add-criterion field picker, leaf widget, and relation-descent picker read.

    One ``FieldMeta`` per filterable field: leaf criteria and aggregates as value
    fields (``kind`` from the criterion type), each cross-entity sub-filter as a
    ``kind="relation"`` entry naming its target. The ``search`` free-text field is
    excluded — it is not a pickable per-field criterion but the filter bar's
    dedicated free-text search criterion (the ``search`` key), applied imperatively in
    each filter's ``_extra_q`` via ``search_q``. Non-recursive: a relation entry
    names its target only; callers descend by calling ``field_metadata`` on the
    target filter class, which bounds the ``GameFilter`` ↔ ``SessionFilter``
    relation cycle.
    """
    cached = _FIELD_METADATA_CACHE.get(filter_cls)
    if cached is not None:
        return cached
    model = filter_cls._comparison_model()
    entries: list[FieldMeta] = []
    for dataclass_field in dc_fields(filter_cls):
        name = dataclass_field.name
        if name == "search":
            # The filter bar's free-text box, not a pickable field — excluded here.
            continue
        criterion_cls = _criterion_class_for(filter_cls, name)
        if criterion_cls is not None:
            # Resolve the model column for any field in ``fields`` with a lookup
            # and no handler — this includes the imperative M2M ``games``
            # (``lookup="games"``, ``handler=None``), whose resolved field is what
            # powers its ``is_m2m``/``search_url`` widget config. Aggregates (not in
            # ``fields``) and handler-mapped fields name no single column, so they
            # skip resolution and carry no choices / aren't nullable. Resolving
            # *only* the column-backed fields means a mis-typed ``FilterField``
            # lookup raises here (matching ``criterion_kind`` / ``resolve_path_kind``'s
            # loud-failure contract) instead of silently degrading to an empty
            # picker, while the legitimately-columnless fields never hit the None.
            model_field: models.Field | None = None
            field_spec = filter_cls.fields.get(name)
            if (
                field_spec is not None
                and field_spec.handler is None
                and model is not None
            ):
                lookup = field_spec.lookup or name
                model_field = _resolve_model_field(model, lookup)
                if model_field is None:
                    raise ValueError(
                        f"{filter_cls.__name__}.{name} lookup {lookup!r} resolves "
                        f"to no field on {model.__name__}"
                    )
            is_aggregate = issubclass(criterion_cls, AggregateCriterion)
            # Aggregates set kind directly: ``criterion_kind`` would reject a
            # future ``AggregateCriterion`` subclass (its exact-class registry has
            # no entry → ValueError), whereas the value shape is always "number".
            kind: FieldMetaKind = (
                "number" if is_aggregate else criterion_kind(criterion_cls)
            )
            nullable = bool(getattr(model_field, "null", False))
            # Value-widget config (issue #242). ``field_spec`` is None for
            # aggregates (no ``fields`` entry) — guard it. ``is_m2m`` is derived
            # from the resolved model field, so a future FK set field needs no flag.
            is_m2m = bool(getattr(model_field, "many_to_many", False))
            search_url = field_spec.search_url if field_spec is not None else None
            # An aggregate's scope target (issue #151): the model of the related
            # rows it reduces, resolved from the field's AggregateSpec. Resolving
            # loudly here matches the mis-typed-lookup contract above — a spec
            # gap is a wiring bug, not a degraded picker.
            scope_model: ModelKey = ""
            if is_aggregate:
                spec = filter_cls.aggregates.get(name)
                if spec is None:
                    raise ValueError(
                        f"{filter_cls.__name__}.{name} is an aggregate field with "
                        f"no AggregateSpec in {filter_cls.__name__}.aggregates"
                    )
                scope_target = spec.scope_filter._comparison_model()
                if scope_target is None:
                    raise ValueError(
                        f"{filter_cls.__name__}.{name} scope filter "
                        f"{spec.scope_filter.__name__} has no comparison model"
                    )
                scope_model = scope_target._meta.model_name or ""
            entries.append(
                FieldMeta(
                    name=name,
                    label=_field_label(filter_cls, name),
                    kind=kind,
                    nullable=nullable,
                    choices=_static_choices(model_field),
                    modifiers=_modifiers_for_field(kind, nullable),
                    relations=[],
                    search_url=search_url or "",
                    is_m2m=is_m2m,
                    scope_model=scope_model,
                )
            )
            continue
        sub_filter_cls = _filter_class_for(filter_cls, name)
        if sub_filter_cls is not None:
            target_model = sub_filter_cls._comparison_model()
            if target_model is None:
                # A descendable sub-filter with no model is a misconfiguration:
                # fail loudly rather than emit a nameless relation target.
                raise ValueError(
                    f"{filter_cls.__name__}.{name} descends into "
                    f"{sub_filter_cls.__name__}, which has no comparison model"
                )
            entries.append(
                FieldMeta(
                    name=name,
                    label=_field_label(filter_cls, name),
                    kind="relation",
                    nullable=False,
                    choices=[],
                    modifiers=[],
                    relations=[
                        RelationTarget(
                            field=name,
                            filter=sub_filter_cls.__name__,
                            model=target_model.__name__,
                        )
                    ],
                    search_url="",
                    is_m2m=False,
                    scope_model="",
                )
            )
    _FIELD_METADATA_CACHE[filter_cls] = entries
    return entries


def _allowed_comparison_modifiers(group: ComparisonGroup) -> list[Modifier]:
    """Modifiers valid for a comparison group.

    bool is equality-only; string adds case-insensitive containment
    (INCLUDES/EXCLUDES) on top of ordering; all other groups are ordered-only.
    """
    if group == "bool":
        return [Modifier.EQUALS, Modifier.NOT_EQUALS]
    if group == "string":
        return Modifier.for_field_comparisons()
    return Modifier.for_ordered_field_comparisons()


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


# ── Field-handler factories ──────────────────────────────────────────────────
# Reusable criterion→Q builders for the non-plain ``FilterField`` mappings, so a
# filter's descriptor table can express hours→duration and bool presence/zero
# fields declaratively instead of in an imperative ``to_q`` block.


def duration_hours_handler(field_name: str) -> FieldHandler:
    """Map an hours-based ``IntCriterion`` onto a DurationField via timedelta."""

    def handler(c: _Criterion) -> Q:
        # ``value2`` is the optional upper bound (BETWEEN); only numeric criteria
        # declare it, so read it None-tolerantly off the base-typed criterion.
        value2 = getattr(c, "value2", None)
        return duration_hours_to_q(c.value, value2, c.modifier, field_name)

    return handler


def bool_isnull_handler(field_name: str, *, invert: bool = False) -> FieldHandler:
    """Map a ``BoolCriterion`` onto a ``__isnull`` presence test.

    ``invert=False``: True means the column IS NULL (e.g. is_active → an open
    session has ``timestamp_end IS NULL``).  ``invert=True``: True means the
    column IS NOT NULL (e.g. is_refunded → ``date_refunded IS NOT NULL``).
    """
    return lambda c: Q(
        **{f"{field_name}__isnull": (not c.value) if invert else c.value}
    )


def bool_nonzero_duration_handler(field_name: str) -> FieldHandler:
    """Map a ``BoolCriterion`` onto a non-zero DurationField test.

    True selects rows whose duration differs from ``timedelta(0)`` (e.g. is_manual
    → ``duration_manual`` was entered by hand); False selects the zero rows.
    """
    from datetime import timedelta

    return lambda c: (
        (~Q(**{field_name: timedelta(0)}))
        if c.value
        else Q(**{field_name: timedelta(0)})
    )


def search_q(criterion: StringCriterion, *field_names: str) -> Q:
    """Free-text OR across several ``__icontains`` columns, negated on EXCLUDES.

    Mirrors the per-filter free-text ``search`` block: an empty value contributes
    no constraint; otherwise each column is OR'd, and ``EXCLUDES`` negates the
    whole disjunction. ``field_names`` must be non-empty.
    """
    if not criterion.value:
        return Q()
    combined = Q(**{f"{field_names[0]}__icontains": criterion.value})
    for field_name in field_names[1:]:
        combined |= Q(**{f"{field_name}__icontains": criterion.value})
    if criterion.modifier == Modifier.EXCLUDES:
        combined = ~combined
    return combined


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
    spec: AggregateSpec,
) -> Q:
    """Filter ``model`` by a reducer (count / sum / avg) over a relation.

    Annotates ``model`` with the aggregate, compares it against the criterion's
    value(s)/modifier, and returns ``Q(id__in=<matching ids>)``.
    ``unit="duration_hours"`` compares an hours value against a DurationField
    aggregate; otherwise a plain numeric comparison is used. ``sum``/``avg``
    require a ``source`` field; ``count`` aggregates whole rows.

    A criterion ``scope`` narrows the reducer to related rows matching the
    sub-filter (issue #151), via the aggregate's ``filter=`` argument. The
    condition is a subquery membership test — ``accessor IN (<related rows
    matching scope>)`` — rather than a rewrite of the scope's Q into the parent
    namespace: the scope Q is evaluated entirely by the related model's own
    queryset, so ``F()`` expressions, transforms, and nested subqueries inside
    it keep their meaning (a key-prefix rewriter would silently re-root them
    against the wrong model).
    """
    from django.db.models import Avg, Count, Sum

    scope_condition: Q | None = None
    if criterion.scope is not None:
        # A hand-assembled criterion could carry a wrong-typed scope; its Q would
        # be built in the wrong model's namespace and produce a silently-wrong
        # (or FieldError-ing) subquery, so guard the type loudly. Never user
        # input — from_json always builds the scope from the spec's class.
        if not isinstance(criterion.scope, spec.scope_filter):
            raise RuntimeError(
                f"aggregate scope must be a {spec.scope_filter.__name__},"
                f" got {type(criterion.scope).__name__}"
            )
        related_model: ModelClass = spec.scope_filter._comparison_model()
        if related_model is None:
            raise RuntimeError(
                f"{spec.scope_filter.__name__} has no comparison model"
                f" to scope a {spec.accessor!r} aggregate"
            )
        matching = related_model.objects.filter(criterion.scope.to_q())
        scope_condition = Q(**{f"{spec.accessor}__in": matching})

    # The spec is static config declared on the filter class, never user input —
    # a failure here is a wiring bug. Raise RuntimeError (not ValueError) so
    # filter_from_json's eager-validation catch does NOT reclassify it to
    # FilterError: a real bug must still 500, not masquerade as bad input.
    if spec.reducer == "count":
        aggregate_expression: Any = Count(
            spec.accessor, distinct=True, filter=scope_condition
        )
    elif spec.reducer in ("sum", "avg"):
        if spec.source is None:
            raise RuntimeError(f"{spec.reducer!r} aggregate requires a source field")
        reduce = Sum if spec.reducer == "sum" else Avg
        aggregate_expression = reduce(
            f"{spec.accessor}__{spec.source}", filter=scope_condition
        )
    else:
        raise RuntimeError(f"Unknown aggregate reducer {spec.reducer!r}")

    if spec.unit == "duration_hours":
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
