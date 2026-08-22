"""Command idempotency: what a key already produced, and whether the input
behind it is still the same one.

A command names itself with a key. Repeating that key returns the sequence range
the first attempt was given rather than appending a second time; repeating it
over different input is refused.
"""

import hashlib
import json
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from timetracker.temporal import TemporalValue

type IdempotencyKey = str  # "session-create-01J8Z3K4M5N6P7Q8R9S0T1U2V3"
type RequestFingerprint = str  # "9f86d081884c7d65..." (sha256 hex)

#: Stamped on every record. Bump it when _encode_command_value or the canonical
#: form changes: records written under another version are no longer comparable
#: and replay unchecked, rather than rejecting every retry that predates it.
FINGERPRINT_VERSION = 1


def _encode_command_value(value: Any) -> str | None:
    #: datetime before date -- datetime subclasses date, so the reverse order
    #: would silently reduce every timestamp to its calendar day.
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, TemporalValue):
        #: None for an unknown time, which json renders as null.
        return value.canonical
    raise TypeError(
        f"{type(value).__name__} has no canonical form for an idempotency "
        "fingerprint. Convert it at the call site: a repr() fallback would "
        "vary between processes and turn honest retries into mismatches."
    )


def fingerprint_command_input(command_input: dict[str, Any]) -> RequestFingerprint:
    """Hash a command's canonical input, so a key reused over different input
    can be told from an honest retry.

    The parameter is `dict`, not `Mapping`: json's encoder dispatches on
    `isinstance(o, dict)`, so any other Mapping reaches `default` and raises.
    """
    canonical = json.dumps(
        command_input,
        sort_keys=True,
        separators=(",", ":"),
        default=_encode_command_value,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
