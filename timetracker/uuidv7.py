import secrets
import uuid
from datetime import UTC, datetime

from django.core.exceptions import ValidationError
from django.db import NotSupportedError, models
from django.urls.converters import UUIDConverter

INVALID_UUID_CODE = "invalid_uuid"
INVALID_UUID_VERSION_CODE = "invalid_uuid_version"

type UnixMilliseconds = int  # e.g. 1734000000000

_VERSION_7 = 0x7
_VARIANT_RFC_4122 = 0b10
_RAND_A_BITS = 12
_RAND_B_BITS = 62
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def uuid7_at(moment: datetime, *, sequence: int | None = None) -> uuid.UUID:
    """Encode a UUIDv7 whose embedded timestamp is `moment`, not "now".

    `sequence`, when given, is written into the 12-bit rand_a field as the
    monotonic counter RFC 9562 method 2 permits, so repeated calls at the
    same millisecond can be given an explicit, testable order.
    """
    if moment.tzinfo is None:
        raise ValueError("moment must be timezone-aware")

    # Floor to the millisecond via integer timedelta arithmetic, not
    # round(moment.timestamp() * 1000): floating-point .timestamp() loses
    # precision near the microsecond digit, and rounding (vs. flooring)
    # would disagree with both PostgreSQL's date_trunc('milliseconds', ...)
    # and CPython's own uuid.uuid7() (nanoseconds // 1_000_000), which the
    # migration's reconciliation check compares against.
    elapsed = moment - _EPOCH
    unix_ts_ms: UnixMilliseconds = (
        elapsed.days * 86_400_000
        + elapsed.seconds * 1000
        + elapsed.microseconds // 1000
    )
    rand_a = secrets.randbits(_RAND_A_BITS) if sequence is None else sequence
    rand_b = secrets.randbits(_RAND_B_BITS)

    value = (unix_ts_ms & 0xFFFF_FFFF_FFFF) << 80
    value |= ((_VERSION_7 << _RAND_A_BITS) | (rand_a & 0xFFF)) << 64
    value |= (_VARIANT_RFC_4122 << _RAND_B_BITS) | (rand_b & 0x3FFF_FFFF_FFFF_FFFF)
    return uuid.UUID(int=value)


class UUIDv7ParseError(ValueError):
    """A malformed UUID or a UUID outside the required variant/version."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def parse_uuidv7(value: str | uuid.UUID) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = uuid.UUID(value)
        except (AttributeError, ValueError) as exc:
            raise UUIDv7ParseError(
                "Enter a valid UUID.", code=INVALID_UUID_CODE
            ) from exc
    else:
        raise UUIDv7ParseError("Enter a valid UUID.", code=INVALID_UUID_CODE)

    if parsed.variant != uuid.RFC_4122 or parsed.version != 7:
        raise UUIDv7ParseError(
            "UUID must use RFC 9562 version 7.",
            code=INVALID_UUID_VERSION_CODE,
        )
    return parsed


def _parse_for_django(value: str | uuid.UUID) -> uuid.UUID:
    try:
        return parse_uuidv7(value)
    except UUIDv7ParseError as exc:
        raise ValidationError(str(exc), code=exc.code, params={"value": value}) from exc


def validate_uuidv7(value: str | uuid.UUID) -> None:
    _parse_for_django(value)


class PostgreSQLUUIDv7(models.Func):
    function = "uuidv7"
    output_field = models.UUIDField()


class UUIDv7Field(models.UUIDField):
    default_validators = (validate_uuidv7,)

    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("default", uuid.uuid7)
        kwargs.setdefault("db_default", PostgreSQLUUIDv7())
        super().__init__(*args, **kwargs)

    def db_type(self, connection) -> str:
        if connection.vendor != "postgresql":
            raise NotSupportedError("UUIDv7Field requires PostgreSQL.")
        return "uuid_v7"

    def to_python(self, value):
        if value is None:
            return None
        return _parse_for_django(value)

    def from_db_value(self, value, expression, connection):
        if value is None:
            return None
        return self.to_python(value)


class UUIDv7Converter:
    regex = UUIDConverter.regex

    def to_python(self, value: str) -> uuid.UUID:
        return parse_uuidv7(value)

    def to_url(self, value: str | uuid.UUID) -> str:
        return str(parse_uuidv7(value))
