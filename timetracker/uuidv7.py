import secrets
import uuid
from datetime import UTC, datetime
from typing import Annotated

from django.core.exceptions import ValidationError
from django.db import NotSupportedError, models
from django.urls.converters import UUIDConverter
from pydantic import AfterValidator

INVALID_UUID_CODE = "invalid_uuid"
INVALID_UUID_VERSION_CODE = "invalid_uuid_version"

type UnixMilliseconds = int  # e.g. 1734000000000

_RAND_A_BITS = 12
_RAND_B_BITS = 62
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def uuid7_at(
    moment: datetime, *, sequence: int | None = None, entropy: int | None = None
) -> uuid.UUID:
    """Encode a UUIDv7 whose embedded timestamp is `moment`, not "now".

    `sequence`, when given, is written into the 12-bit rand_a field in the
    position used by an RFC 9562 Method 1 fixed-length dedicated counter,
    so repeated calls at the same millisecond can be given an explicit,
    testable order. This function only places the value there; seeding a
    fresh counter per millisecond tick, as Method 1 itself calls for, is
    the caller's responsibility.

    `entropy`, when given, fills the 62-bit rand_b tail that is otherwise
    drawn from `secrets`. It exists for callers that must be reproducible
    from their own seeded generator - `anonymize_sample` regenerates a
    committed fixture and needs a byte-identical result per seed. Leave it
    unset anywhere the value reaches a real record.
    """
    if moment.utcoffset() is None:
        raise ValueError("moment must be timezone-aware")
    if sequence is not None and not 0 <= sequence < (1 << _RAND_A_BITS):
        raise ValueError(f"sequence must be between 0 and {(1 << _RAND_A_BITS) - 1}")
    if entropy is not None and not 0 <= entropy < (1 << _RAND_B_BITS):
        raise ValueError(f"entropy must be between 0 and {(1 << _RAND_B_BITS) - 1}")

    # Floor to the millisecond via integer timedelta arithmetic, not
    # round(moment.timestamp() * 1000): floating-point .timestamp() loses
    # precision near the microsecond digit, and rounding (vs. flooring)
    # would disagree with PostgreSQL's date_trunc('milliseconds', ...),
    # which the migration's reconciliation check compares against. (This
    # also matches how CPython's own uuid.uuid7() computes its embedded
    # timestamp - nanoseconds // 1_000_000 - though its rand_a/rand_b are
    # a 42-bit Method 1 counter plus a 32-bit random tail, not the
    # independent random/sequence fields used here.)
    elapsed = moment - _EPOCH
    unix_ts_ms: UnixMilliseconds = (
        elapsed.days * 86_400_000
        + elapsed.seconds * 1000
        + elapsed.microseconds // 1000
    )
    # unix_ts_ms's only possible out-of-range direction is negative (a
    # pre-epoch moment): a valid datetime's upper bound (year 9999) sits
    # well under the 48-bit field's ~year-10889 ceiling, so only the lower
    # bound needs guarding.
    if unix_ts_ms < 0:
        raise ValueError("moment must not be before the Unix epoch")

    rand_a = secrets.randbits(_RAND_A_BITS) if sequence is None else sequence
    rand_b = secrets.randbits(_RAND_B_BITS) if entropy is None else entropy

    value = unix_ts_ms << 80
    value |= rand_a << 64
    value |= rand_b
    return uuid.UUID(int=value, version=7)


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


UUIDv7 = Annotated[uuid.UUID, AfterValidator(parse_uuidv7)]


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
    # No default_validators: to_python() below already parses and
    # version-checks every value, raising before Field.clean()'s
    # run_validators() step would ever run a redundant second pass.
    # validate_uuidv7 stays a public validator for callers that need one
    # independent of this field (e.g. a form field that isn't this one).

    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("default", uuid.uuid7)
        kwargs.setdefault("db_default", PostgreSQLUUIDv7())
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        # Field.deconstruct() records a db_default only when one exists, so a
        # field that deliberately has none would come back from clone() with
        # __init__'s generated default re-applied — and migration state would
        # disagree with the model forever. Record the absence explicitly.
        if not self.has_db_default():
            kwargs["db_default"] = models.NOT_PROVIDED
        return name, path, args, kwargs

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
