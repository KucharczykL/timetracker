from __future__ import annotations

import re
from calendar import monthrange
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Literal

from django.core.exceptions import ValidationError
from django.db import NotSupportedError, models


class TemporalPrecision(StrEnum):
    DAY = "day"
    MONTH = "month"
    YEAR = "year"
    DECADE = "decade"


class TemporalValueKind(StrEnum):
    ATOMIC = "atomic"
    RANGE = "range"
    UNKNOWN = "unknown"


class TemporalEndpointKind(StrEnum):
    KNOWN = "known"
    UNKNOWN = "unknown"
    OPEN = "open"


class TemporalQualifier(StrEnum):
    UNCERTAIN = "uncertain"
    APPROXIMATE = "approximate"
    BOTH = "both"


class TemporalValueParseError(ValueError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class _TemporalParts:
    canonical: str | None
    lower_bound: date | None
    upper_bound: date | None
    kind: TemporalValueKind
    precision: TemporalPrecision | None
    qualifier: TemporalQualifier | None = None
    start: TemporalEndpoint | None = None
    end: TemporalEndpoint | None = None


@dataclass(frozen=True, slots=True, init=False)
class TemporalEndpoint:
    kind: TemporalEndpointKind
    value: TemporalValue | None

    @classmethod
    def _create(
        cls, kind: TemporalEndpointKind, value: TemporalValue | None
    ) -> TemporalEndpoint:
        endpoint = object.__new__(cls)
        object.__setattr__(endpoint, "kind", kind)
        object.__setattr__(endpoint, "value", value)
        return endpoint

    @classmethod
    def known(cls, value: TemporalValue) -> TemporalEndpoint:
        if not isinstance(value, TemporalValue):
            raise TypeError("A known temporal endpoint requires a TemporalValue.")
        if value.kind is not TemporalValueKind.ATOMIC:
            raise ValueError("A known temporal endpoint must contain an atomic value.")
        return cls._create(TemporalEndpointKind.KNOWN, value)

    @classmethod
    def unknown(cls) -> TemporalEndpoint:
        return cls._create(TemporalEndpointKind.UNKNOWN, None)

    @classmethod
    def open(cls) -> TemporalEndpoint:
        return cls._create(TemporalEndpointKind.OPEN, None)

    @property
    def precision(self) -> TemporalPrecision | None:
        return None if self.value is None else self.value.precision

    @property
    def qualifier(self) -> TemporalQualifier | None:
        return None if self.value is None else self.value.qualifier

    @property
    def year(self) -> int | None:
        return None if self.value is None else self.value.year

    @property
    def month(self) -> int | None:
        return None if self.value is None else self.value.month

    @property
    def day(self) -> int | None:
        return None if self.value is None else self.value.day

    @property
    def decade_start_year(self) -> int | None:
        return None if self.value is None else self.value.decade_start_year

    @property
    def is_known(self) -> bool:
        return self.kind is TemporalEndpointKind.KNOWN

    @property
    def is_unknown(self) -> bool:
        return self.kind is TemporalEndpointKind.UNKNOWN

    @property
    def is_open(self) -> bool:
        return self.kind is TemporalEndpointKind.OPEN

    @property
    def has_known_year(self) -> bool:
        return self.value is not None and self.value.has_known_year

    @property
    def has_known_month(self) -> bool:
        return self.value is not None and self.value.has_known_month

    @property
    def has_known_day(self) -> bool:
        return self.value is not None and self.value.has_known_day


@dataclass(frozen=True, slots=True, init=False)
class TemporalValue:
    canonical: str | None
    lower_bound: date | None
    upper_bound: date | None
    kind: TemporalValueKind
    precision: TemporalPrecision | None
    qualifier: TemporalQualifier | None
    start: TemporalEndpoint | None
    end: TemporalEndpoint | None

    def __init__(self, canonical: str | None) -> None:
        parsed = _parse_canonical(canonical)
        object.__setattr__(self, "canonical", parsed.canonical)
        object.__setattr__(self, "lower_bound", parsed.lower_bound)
        object.__setattr__(self, "upper_bound", parsed.upper_bound)
        object.__setattr__(self, "kind", parsed.kind)
        object.__setattr__(self, "precision", parsed.precision)
        object.__setattr__(self, "qualifier", parsed.qualifier)
        object.__setattr__(self, "start", parsed.start)
        object.__setattr__(self, "end", parsed.end)

    @classmethod
    def parse(cls, value: str | None) -> TemporalValue:
        return cls(value)

    @classmethod
    def unknown(cls) -> TemporalValue:
        return cls(None)

    @classmethod
    def from_day(
        cls, value: date, *, qualifier: TemporalQualifier | None = None
    ) -> TemporalValue:
        if type(value) is not date:
            raise TypeError("A day temporal value requires a date.")
        return cls(f"{value.isoformat()}{_qualifier_symbol(qualifier)}")

    @classmethod
    def from_month(
        cls, year: int, month: int, *, qualifier: TemporalQualifier | None = None
    ) -> TemporalValue:
        _reject_boolean_integer(year, "year")
        _reject_boolean_integer(month, "month")
        return cls(f"{year:04d}-{month:02d}{_qualifier_symbol(qualifier)}")

    @classmethod
    def from_year(
        cls, year: int, *, qualifier: TemporalQualifier | None = None
    ) -> TemporalValue:
        _reject_boolean_integer(year, "year")
        return cls(f"{year:04d}{_qualifier_symbol(qualifier)}")

    @classmethod
    def from_decade(
        cls, start_year: int, *, qualifier: TemporalQualifier | None = None
    ) -> TemporalValue:
        _reject_boolean_integer(start_year, "start_year")
        if start_year % 10 or not 10 <= start_year <= 9990:
            raise ValueError(
                "A decade must start on a ten-year boundary from 0010 through 9990."
            )
        return cls(f"{start_year // 10:03d}X{_qualifier_symbol(qualifier)}")

    @classmethod
    def range(cls, *, start: TemporalEndpoint, end: TemporalEndpoint) -> TemporalValue:
        if not isinstance(start, TemporalEndpoint) or not isinstance(
            end, TemporalEndpoint
        ):
            raise TypeError("A temporal range requires two TemporalEndpoint values.")
        return cls(f"{_serialize_endpoint(start)}/{_serialize_endpoint(end)}")

    def serialize(self) -> str | None:
        return self.canonical

    @property
    def is_range(self) -> bool:
        return self.kind is TemporalValueKind.RANGE

    @property
    def is_unknown(self) -> bool:
        return self.kind is TemporalValueKind.UNKNOWN

    @property
    def is_uncertain(self) -> bool:
        return self.qualifier in (
            TemporalQualifier.UNCERTAIN,
            TemporalQualifier.BOTH,
        )

    @property
    def is_approximate(self) -> bool:
        return self.qualifier in (
            TemporalQualifier.APPROXIMATE,
            TemporalQualifier.BOTH,
        )

    @property
    def has_known_year(self) -> bool:
        return self.kind is TemporalValueKind.ATOMIC and self.precision in {
            TemporalPrecision.DAY,
            TemporalPrecision.MONTH,
            TemporalPrecision.YEAR,
        }

    @property
    def has_known_month(self) -> bool:
        return self.kind is TemporalValueKind.ATOMIC and self.precision in {
            TemporalPrecision.DAY,
            TemporalPrecision.MONTH,
        }

    @property
    def has_known_day(self) -> bool:
        return (
            self.kind is TemporalValueKind.ATOMIC
            and self.precision is TemporalPrecision.DAY
        )

    @property
    def year(self) -> int | None:
        if self.lower_bound is None or not self.has_known_year:
            return None
        return self.lower_bound.year

    @property
    def month(self) -> int | None:
        if self.lower_bound is None or not self.has_known_month:
            return None
        return self.lower_bound.month

    @property
    def day(self) -> int | None:
        if self.lower_bound is None or not self.has_known_day:
            return None
        return self.lower_bound.day

    @property
    def decade_start_year(self) -> int | None:
        if self.kind is not TemporalValueKind.ATOMIC:
            return None
        if self.precision is not TemporalPrecision.DECADE:
            return None
        return None if self.lower_bound is None else self.lower_bound.year

    @property
    def is_complete_day(self) -> bool:
        return self.has_known_year and self.has_known_month and self.has_known_day

    @property
    def is_exact_day(self) -> bool:
        return self.is_complete_day


_DAY_RE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})", re.ASCII)
_MONTH_RE = re.compile(r"([0-9]{4})-([0-9]{2})", re.ASCII)
_YEAR_RE = re.compile(r"([0-9]{4})", re.ASCII)
_DECADE_RE = re.compile(r"([0-9]{3})X", re.ASCII)

_QUALIFIER_BY_SYMBOL: dict[str, TemporalQualifier] = {
    "?": TemporalQualifier.UNCERTAIN,
    "~": TemporalQualifier.APPROXIMATE,
    "%": TemporalQualifier.BOTH,
}
_SYMBOL_BY_QUALIFIER: dict[TemporalQualifier, str] = {
    qualifier: symbol for symbol, qualifier in _QUALIFIER_BY_SYMBOL.items()
}


def _split_qualifier(token: str) -> tuple[str, TemporalQualifier | None]:
    """Splits the trailing symbol off a token."""
    if not token:
        return token, None
    qualifier = _QUALIFIER_BY_SYMBOL.get(token[-1])
    if qualifier is None:
        return token, None
    return token[:-1], qualifier


def _qualifier_symbol(qualifier: TemporalQualifier | None) -> str:
    if qualifier is None:
        return ""
    if not isinstance(qualifier, TemporalQualifier):
        raise TypeError("qualifier must be a TemporalQualifier or None.")
    return _SYMBOL_BY_QUALIFIER[qualifier]


def _parse_canonical(canonical: str | None) -> _TemporalParts:
    if canonical is None:
        return _TemporalParts(
            canonical=None,
            lower_bound=None,
            upper_bound=None,
            kind=TemporalValueKind.UNKNOWN,
            precision=None,
        )
    if not isinstance(canonical, str):
        raise TemporalValueParseError(
            "Temporal value must be a canonical string or None.",
            code="invalid_type",
        )
    _reject_unsupported_family(canonical)
    if "/" in canonical:
        return _parse_range(canonical)
    return _parse_atom(canonical)


def _reject_unsupported_family(canonical: str) -> None:
    if canonical.startswith(("[", "{")) or canonical.endswith(("]", "}")):
        raise TemporalValueParseError(
            f"Temporal sets are not supported: {canonical!r}.",
            code="unsupported_set",
        )
    if "T" in canonical:
        raise TemporalValueParseError(
            f"Temporal timestamps are not supported: {canonical!r}.",
            code="unsupported_timestamp",
        )
    tokens = canonical.split("/")
    split_tokens = tuple(_split_qualifier(token) for token in tokens)
    unqualified = tuple(atom for atom, _ in split_tokens)
    for atom in unqualified:
        if atom and atom[-1] in _QUALIFIER_BY_SYMBOL:
            raise TemporalValueParseError(
                "A temporal position takes one qualifier symbol, and '%' is the "
                f"symbol for both: {canonical!r}.",
                code="invalid_qualifier",
            )
        if any(symbol in atom for symbol in _QUALIFIER_BY_SYMBOL):
            raise TemporalValueParseError(
                f"Component temporal qualifiers are not supported: {canonical!r}.",
                code="unsupported_component_qualifier",
            )
    if len(tokens) == 2 and any(
        qualifier is not None and atom in ("", "..") for atom, qualifier in split_tokens
    ):
        raise TemporalValueParseError(
            "An open or unknown temporal endpoint holds no date to qualify: "
            f"{canonical!r}.",
            code="unsupported_endpoint_qualifier",
        )
    bare = "/".join(unqualified)
    if re.fullmatch(r"[0-9]{4}-(?:2[1-4])", bare, re.ASCII):
        raise TemporalValueParseError(
            f"Temporal seasons are not supported: {canonical!r}.",
            code="unsupported_season",
        )
    if "X" in bare and any(
        "X" in atom and not _DECADE_RE.fullmatch(atom) for atom in unqualified
    ):
        raise TemporalValueParseError(
            f"Unspecified temporal components are not supported: {canonical!r}.",
            code="unsupported_unspecified_component",
        )
    if any(
        atom.startswith(("-", "Y"))
        or re.match(r"(?:0000|[0-9]{5,})(?:$|-)", atom, re.ASCII)
        for atom in unqualified
    ):
        raise TemporalValueParseError(
            f"Unsupported, extended, or negative temporal year: {canonical!r}.",
            code="unsupported_year",
        )


def _parse_atom(canonical: str) -> _TemporalParts:
    atom, qualifier = _split_qualifier(canonical)

    if match := _DAY_RE.fullmatch(atom):
        year, month, day = (int(part) for part in match.groups())
        try:
            value = date(year, month, day)
        except ValueError as exc:
            raise TemporalValueParseError(
                f"Invalid calendar day: {canonical}.", code="invalid_date"
            ) from exc
        return _atomic_parts(canonical, value, value, TemporalPrecision.DAY, qualifier)

    if match := _MONTH_RE.fullmatch(atom):
        year, month = (int(part) for part in match.groups())
        try:
            last_day = monthrange(year, month)[1]
            lower = date(year, month, 1)
            upper = date(year, month, last_day)
        except (ValueError, OverflowError) as exc:
            raise TemporalValueParseError(
                f"Invalid calendar month: {canonical}.", code="invalid_date"
            ) from exc
        return _atomic_parts(
            canonical, lower, upper, TemporalPrecision.MONTH, qualifier
        )

    if match := _YEAR_RE.fullmatch(atom):
        year = int(match.group(1))
        try:
            lower = date(year, 1, 1)
            upper = date(year, 12, 31)
        except ValueError as exc:
            raise TemporalValueParseError(
                f"Invalid calendar year: {canonical}.", code="unsupported_year"
            ) from exc
        return _atomic_parts(canonical, lower, upper, TemporalPrecision.YEAR, qualifier)

    if match := _DECADE_RE.fullmatch(atom):
        first_year = int(match.group(1)) * 10
        try:
            lower = date(first_year, 1, 1)
            upper = date(first_year + 9, 12, 31)
        except ValueError as exc:
            raise TemporalValueParseError(
                f"Unsupported calendar decade: {canonical}.",
                code="unsupported_year",
            ) from exc
        return _atomic_parts(
            canonical, lower, upper, TemporalPrecision.DECADE, qualifier
        )

    raise TemporalValueParseError(
        f"Invalid temporal value syntax: {canonical!r}.", code="invalid_syntax"
    )


def _atomic_parts(
    canonical: str,
    lower: date,
    upper: date,
    precision: TemporalPrecision,
    qualifier: TemporalQualifier | None,
) -> _TemporalParts:
    return _TemporalParts(
        canonical=canonical,
        lower_bound=lower,
        upper_bound=upper,
        kind=TemporalValueKind.ATOMIC,
        precision=precision,
        qualifier=qualifier,
    )


def _parse_range(canonical: str) -> _TemporalParts:
    if canonical.count("/") != 1:
        raise TemporalValueParseError(
            f"Invalid temporal range: {canonical!r}.", code="invalid_range"
        )
    start_token, end_token = canonical.split("/")
    start = _parse_endpoint(start_token)
    end = _parse_endpoint(end_token)
    if not start.is_known and not end.is_known:
        raise TemporalValueParseError(
            "A temporal range requires at least one known endpoint.",
            code="invalid_range",
        )
    if start.value is not None and end.value is not None:
        start_lower = start.value.lower_bound
        end_upper = end.value.upper_bound
        assert start_lower is not None and end_upper is not None
        if start_lower > end_upper:
            raise TemporalValueParseError(
                f"Temporal range start follows its end: {canonical!r}.",
                code="invalid_range",
            )
    return _TemporalParts(
        canonical=canonical,
        lower_bound=None if start.value is None else start.value.lower_bound,
        upper_bound=None if end.value is None else end.value.upper_bound,
        kind=TemporalValueKind.RANGE,
        precision=None,
        start=start,
        end=end,
    )


def _parse_endpoint(token: str) -> TemporalEndpoint:
    if token == "":
        return TemporalEndpoint.unknown()
    if token == "..":
        return TemporalEndpoint.open()
    return TemporalEndpoint.known(TemporalValue(token))


def _serialize_endpoint(endpoint: TemporalEndpoint) -> str:
    if endpoint.kind is TemporalEndpointKind.UNKNOWN:
        return ""
    if endpoint.kind is TemporalEndpointKind.OPEN:
        return ".."
    if endpoint.value is None:
        raise ValueError("A known temporal endpoint requires a value.")
    return endpoint.value.canonical or ""


def _reject_boolean_integer(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer.")


def parse_temporal_value(value: object) -> TemporalValue:
    if isinstance(value, TemporalValue):
        return value
    if value is None or isinstance(value, str):
        return TemporalValue(value)
    raise TemporalValueParseError(
        "Temporal value must be a canonical string, TemporalValue, or None.",
        code="invalid_type",
    )


def validate_temporal_value(value: object) -> None:
    parse_temporal_value(value)


@dataclass(slots=True)
class TemporalEndpointDraft:
    """One position's dimensions, each independently assignable.

    Mutable on purpose. ``TemporalValue`` is frozen and parses from one
    canonical string, so changing a month there means string surgery.
    Here it is a field assignment, and ``build()`` reassembles the value.
    """

    year: int | None = None
    month: int | None = None
    day: int | None = None
    decade_start_year: int | None = None
    qualifier: TemporalQualifier | None = None

    @property
    def is_empty(self) -> bool:
        """No dimension states anything."""
        return (
            self.year is None
            and self.month is None
            and self.day is None
            and self.decade_start_year is None
        )

    @classmethod
    def from_value(cls, value: TemporalValue | None) -> TemporalEndpointDraft:
        """The dimensions an atomic value states."""
        if value is None:
            return cls()
        return cls(
            year=value.year,
            month=value.month,
            day=value.day,
            decade_start_year=value.decade_start_year,
            qualifier=value.qualifier,
        )

    def build(self) -> TemporalValue | None:
        """The value these dimensions state, or nothing.

        The precision is derived rather than stated: the deepest filled
        part decides it. A part with no shallower part to sit on is a
        disagreement, and a disagreement is refused with a sentence
        rather than completed with an invented part.
        """
        self._refuse_disagreement()
        if self.day is not None:
            assert self.year is not None and self.month is not None
            return _build_day(self.year, self.month, self.day, self.qualifier)
        if self.month is not None:
            assert self.year is not None
            return TemporalValue.from_month(
                self.year, self.month, qualifier=self.qualifier
            )
        if self.year is not None:
            return TemporalValue.from_year(self.year, qualifier=self.qualifier)
        if self.decade_start_year is not None:
            return _build_decade(self.decade_start_year, self.qualifier)
        return None

    def _refuse_disagreement(self) -> None:
        if self.day is not None and (self.year is None or self.month is None):
            raise TemporalValueParseError(
                "A day needs a year and a month beside it.",
                code="incomplete_day",
            )
        if self.month is not None and self.year is None:
            raise TemporalValueParseError(
                "A month needs a year beside it.", code="incomplete_month"
            )
        if self.decade_start_year is not None and not (
            self.year is None and self.month is None and self.day is None
        ):
            raise TemporalValueParseError(
                "State a decade or a date, not both.", code="decade_with_year"
            )


def _build_day(
    year: int, month: int, day: int, qualifier: TemporalQualifier | None
) -> TemporalValue:
    """A refused calendar day carries a sentence."""
    try:
        return TemporalValue.from_day(date(year, month, day), qualifier=qualifier)
    except ValueError as error:
        raise TemporalValueParseError(
            f"{year}-{month}-{day} is not a day the calendar holds.",
            code="invalid_date",
        ) from error


def _build_decade(
    start_year: int, qualifier: TemporalQualifier | None
) -> TemporalValue:
    """A refused decade carries a sentence."""
    try:
        return TemporalValue.from_decade(start_year, qualifier=qualifier)
    except ValueError as error:
        raise TemporalValueParseError(
            "A decade starts on a ten-year boundary, such as 1980.",
            code="invalid_decade",
        ) from error


def _normalize_temporal_model_value(value: object) -> TemporalValue | None:
    if value is None:
        return None
    try:
        parsed = parse_temporal_value(value)
    except TemporalValueParseError as exc:
        raise ValidationError(str(exc), code=exc.code) from exc
    return None if parsed.kind is TemporalValueKind.UNKNOWN else parsed


class TemporalValueField(models.Field):
    def __init__(self, *args, **kwargs) -> None:
        max_length = kwargs.pop("max_length", 64)
        if max_length != 64:
            raise ValueError("TemporalValueField.max_length is fixed at 64.")
        kwargs["max_length"] = 64
        kwargs.setdefault("null", True)
        kwargs.setdefault("blank", False)
        kwargs.setdefault("default", None)
        kwargs.setdefault("editable", False)
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        kwargs.update(
            max_length=64,
            null=self.null,
            blank=self.blank,
            default=self.default,
            editable=self.editable,
        )
        return name, path, args, kwargs

    def db_type(self, connection) -> str:
        if connection.vendor != "postgresql":
            raise NotSupportedError("TemporalValueField requires PostgreSQL.")
        return "temporal_value"

    def to_python(self, value):
        return _normalize_temporal_model_value(value)

    def from_db_value(self, value, expression, connection):
        return _normalize_temporal_model_value(value)

    def get_prep_value(self, value):
        normalized = _normalize_temporal_model_value(value)
        return None if normalized is None else normalized.serialize()

    def value_from_object(self, obj):
        return _normalize_temporal_model_value(super().value_from_object(obj))

    def value_to_string(self, obj):
        value = self.value_from_object(obj)
        return "" if value is None else value.serialize()


class TemporalLowerBound(models.Func):
    function = "timetracker_temporal_lower"
    output_field = models.DateField(null=True)


class TemporalUpperBound(models.Func):
    function = "timetracker_temporal_upper"
    output_field = models.DateField(null=True)


class TemporalKind(models.Func):
    function = "timetracker_temporal_kind"
    output_field = models.CharField(max_length=7)


class TemporalPrecisionValue(models.Func):
    function = "timetracker_temporal_precision"
    output_field = models.CharField(max_length=7, null=True)


class TemporalStartKind(models.Func):
    function = "timetracker_temporal_start_kind"
    output_field = models.CharField(max_length=7, null=True)


class TemporalEndKind(models.Func):
    function = "timetracker_temporal_end_kind"
    output_field = models.CharField(max_length=7, null=True)


class TemporalStartPrecision(models.Func):
    function = "timetracker_temporal_start_precision"
    output_field = models.CharField(max_length=7, null=True)


class TemporalEndPrecision(models.Func):
    function = "timetracker_temporal_end_precision"
    output_field = models.CharField(max_length=7, null=True)


class TemporalQualifierValue(models.Func):
    function = "timetracker_temporal_qualifier"
    output_field = models.CharField(max_length=11, null=True)


class TemporalStartQualifier(models.Func):
    function = "timetracker_temporal_start_qualifier"
    output_field = models.CharField(max_length=11, null=True)


class TemporalEndQualifier(models.Func):
    function = "timetracker_temporal_end_qualifier"
    output_field = models.CharField(max_length=11, null=True)


type TemporalEndpointName = Literal["start", "end"]

_KNOWN_YEAR_PRECISIONS = (
    TemporalPrecision.DAY.value,
    TemporalPrecision.MONTH.value,
    TemporalPrecision.YEAR.value,
)
_KNOWN_MONTH_PRECISIONS = (
    TemporalPrecision.DAY.value,
    TemporalPrecision.MONTH.value,
)
_KNOWN_DAY_PRECISIONS = (TemporalPrecision.DAY.value,)
_APPROXIMATE_QUALIFIERS = (
    TemporalQualifier.APPROXIMATE.value,
    TemporalQualifier.BOTH.value,
)
_UNCERTAIN_QUALIFIERS = (
    TemporalQualifier.UNCERTAIN.value,
    TemporalQualifier.BOTH.value,
)


def _temporal_component_q(
    field_name: str,
    precisions: tuple[str, ...],
    *,
    endpoint: TemporalEndpointName | None,
) -> models.Q:
    if not isinstance(field_name, str) or not field_name:
        raise ValueError("A temporal field name is required.")
    if endpoint is None:
        return models.Q(
            **{
                f"{field_name}_kind": TemporalValueKind.ATOMIC.value,
                f"{field_name}_precision__in": precisions,
            }
        )
    if endpoint not in ("start", "end"):
        raise ValueError("endpoint must be 'start' or 'end'.")
    return models.Q(
        **{
            f"{field_name}_{endpoint}_kind": TemporalEndpointKind.KNOWN.value,
            f"{field_name}_{endpoint}_precision__in": precisions,
        }
    )


def temporal_has_known_year_q(
    field_name: str, *, endpoint: TemporalEndpointName | None = None
) -> models.Q:
    return _temporal_component_q(field_name, _KNOWN_YEAR_PRECISIONS, endpoint=endpoint)


def temporal_has_known_month_q(
    field_name: str, *, endpoint: TemporalEndpointName | None = None
) -> models.Q:
    return _temporal_component_q(field_name, _KNOWN_MONTH_PRECISIONS, endpoint=endpoint)


def temporal_has_known_day_q(
    field_name: str, *, endpoint: TemporalEndpointName | None = None
) -> models.Q:
    return _temporal_component_q(field_name, _KNOWN_DAY_PRECISIONS, endpoint=endpoint)


def temporal_exact_day_q(field_name: str) -> models.Q:
    if not isinstance(field_name, str) or not field_name:
        raise ValueError("A temporal field name is required.")
    return models.Q(
        **{
            f"{field_name}_kind": TemporalValueKind.ATOMIC.value,
            f"{field_name}_precision": TemporalPrecision.DAY.value,
        }
    )


def _temporal_qualifier_q(
    field_name: str,
    qualifiers: tuple[str, ...],
    *,
    endpoint: TemporalEndpointName | None,
) -> models.Q:
    if not isinstance(field_name, str) or not field_name:
        raise ValueError("A temporal field name is required.")
    if endpoint is None:
        return models.Q(
            **{
                f"{field_name}_kind": TemporalValueKind.ATOMIC.value,
                f"{field_name}_qualifier__in": qualifiers,
            }
        )
    if endpoint not in ("start", "end"):
        raise ValueError("endpoint must be 'start' or 'end'.")
    return models.Q(
        **{
            f"{field_name}_{endpoint}_kind": TemporalEndpointKind.KNOWN.value,
            f"{field_name}_{endpoint}_qualifier__in": qualifiers,
        }
    )


def temporal_is_approximate_q(
    field_name: str, *, endpoint: TemporalEndpointName | None = None
) -> models.Q:
    return _temporal_qualifier_q(field_name, _APPROXIMATE_QUALIFIERS, endpoint=endpoint)


def temporal_is_uncertain_q(
    field_name: str, *, endpoint: TemporalEndpointName | None = None
) -> models.Q:
    return _temporal_qualifier_q(field_name, _UNCERTAIN_QUALIFIERS, endpoint=endpoint)
