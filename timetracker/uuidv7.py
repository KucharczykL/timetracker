import uuid

from django.core.exceptions import ValidationError
from django.urls.converters import UUIDConverter

INVALID_UUID_CODE = "invalid_uuid"
INVALID_UUID_VERSION_CODE = "invalid_uuid_version"


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


class UUIDv7Converter:
    regex = UUIDConverter.regex

    def to_python(self, value: str) -> uuid.UUID:
        return parse_uuidv7(value)

    def to_url(self, value: str | uuid.UUID) -> str:
        return str(parse_uuidv7(value))
