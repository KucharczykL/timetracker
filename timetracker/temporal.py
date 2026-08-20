from __future__ import annotations

import re
from calendar import monthrange
from dataclasses import dataclass
from datetime import date
from enum import StrEnum


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
    start: TemporalEndpoint | None
    end: TemporalEndpoint | None

    def __init__(self, canonical: str | None) -> None:
        parsed = _parse_canonical(canonical)
        object.__setattr__(self, "canonical", parsed.canonical)
        object.__setattr__(self, "lower_bound", parsed.lower_bound)
        object.__setattr__(self, "upper_bound", parsed.upper_bound)
        object.__setattr__(self, "kind", parsed.kind)
        object.__setattr__(self, "precision", parsed.precision)
        object.__setattr__(self, "start", parsed.start)
        object.__setattr__(self, "end", parsed.end)

    @classmethod
    def parse(cls, value: str | None) -> TemporalValue:
        return cls(value)

    @classmethod
    def unknown(cls) -> TemporalValue:
        return cls(None)

    @classmethod
    def from_day(cls, value: date) -> TemporalValue:
        if type(value) is not date:
            raise TypeError("A day temporal value requires a date.")
        return cls(value.isoformat())

    @classmethod
    def from_month(cls, year: int, month: int) -> TemporalValue:
        _reject_boolean_integer(year, "year")
        _reject_boolean_integer(month, "month")
        return cls(f"{year:04d}-{month:02d}")

    @classmethod
    def from_year(cls, year: int) -> TemporalValue:
        _reject_boolean_integer(year, "year")
        return cls(f"{year:04d}")

    @classmethod
    def from_decade(cls, start_year: int) -> TemporalValue:
        _reject_boolean_integer(start_year, "start_year")
        if start_year % 10 or not 10 <= start_year <= 9990:
            raise ValueError(
                "A decade must start on a ten-year boundary from 0010 through 9990."
            )
        return cls(f"{start_year // 10:03d}X")

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
    def is_complete_day(self) -> bool:
        return self.has_known_year and self.has_known_month and self.has_known_day

    @property
    def is_exact_day(self) -> bool:
        return self.is_complete_day


_DAY_RE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})", re.ASCII)
_MONTH_RE = re.compile(r"([0-9]{4})-([0-9]{2})", re.ASCII)
_YEAR_RE = re.compile(r"([0-9]{4})", re.ASCII)
_DECADE_RE = re.compile(r"([0-9]{3})X", re.ASCII)


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
    if any(qualifier in canonical for qualifier in "?~%"):
        raise TemporalValueParseError(
            f"Temporal qualifiers are not supported: {canonical!r}.",
            code="unsupported_qualifier",
        )
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
    if re.fullmatch(r"[0-9]{4}-(?:2[1-4])", canonical, re.ASCII):
        raise TemporalValueParseError(
            f"Temporal seasons are not supported: {canonical!r}.",
            code="unsupported_season",
        )
    if "X" in canonical:
        tokens = canonical.split("/")
        if any("X" in token and not _DECADE_RE.fullmatch(token) for token in tokens):
            raise TemporalValueParseError(
                f"Unspecified temporal components are not supported: {canonical!r}.",
                code="unsupported_unspecified_component",
            )
    if canonical.startswith(("-", "Y")) or re.fullmatch(
        r"[0-9]{5,}", canonical, re.ASCII
    ):
        raise TemporalValueParseError(
            f"Extended or negative years are not supported: {canonical!r}.",
            code="unsupported_year",
        )


def _parse_atom(canonical: str) -> _TemporalParts:
    if match := _DAY_RE.fullmatch(canonical):
        year, month, day = (int(part) for part in match.groups())
        try:
            value = date(year, month, day)
        except ValueError as exc:
            raise TemporalValueParseError(
                f"Invalid calendar day: {canonical}.", code="invalid_date"
            ) from exc
        return _atomic_parts(canonical, value, value, TemporalPrecision.DAY)

    if match := _MONTH_RE.fullmatch(canonical):
        year, month = (int(part) for part in match.groups())
        try:
            last_day = monthrange(year, month)[1]
            lower = date(year, month, 1)
            upper = date(year, month, last_day)
        except (ValueError, OverflowError) as exc:
            raise TemporalValueParseError(
                f"Invalid calendar month: {canonical}.", code="invalid_date"
            ) from exc
        return _atomic_parts(canonical, lower, upper, TemporalPrecision.MONTH)

    if match := _YEAR_RE.fullmatch(canonical):
        year = int(match.group(1))
        try:
            lower = date(year, 1, 1)
            upper = date(year, 12, 31)
        except ValueError as exc:
            raise TemporalValueParseError(
                f"Invalid calendar year: {canonical}.", code="unsupported_year"
            ) from exc
        return _atomic_parts(canonical, lower, upper, TemporalPrecision.YEAR)

    if match := _DECADE_RE.fullmatch(canonical):
        first_year = int(match.group(1)) * 10
        try:
            lower = date(first_year, 1, 1)
            upper = date(first_year + 9, 12, 31)
        except ValueError as exc:
            raise TemporalValueParseError(
                f"Unsupported calendar decade: {canonical}.",
                code="unsupported_year",
            ) from exc
        return _atomic_parts(canonical, lower, upper, TemporalPrecision.DECADE)

    raise TemporalValueParseError(
        f"Invalid temporal value syntax: {canonical!r}.", code="invalid_syntax"
    )


def _atomic_parts(
    canonical: str,
    lower: date,
    upper: date,
    precision: TemporalPrecision,
) -> _TemporalParts:
    return _TemporalParts(
        canonical=canonical,
        lower_bound=lower,
        upper_bound=upper,
        kind=TemporalValueKind.ATOMIC,
        precision=precision,
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
    if (
        start.value is not None
        and end.value is not None
        and start.value.lower_bound > end.value.upper_bound
    ):
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
