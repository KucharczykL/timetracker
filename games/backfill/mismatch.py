"""One reason a gated pass must not commit."""

from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class Mismatch:
    """One reason the run must not commit.

    The code is each pass's own enumeration, so a pass adds a
    reason without touching another pass's list.
    """

    code: StrEnum
    #: A game, a library, or a table: whatever the code names.
    subject: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {
            "code": self.code.value,
            "detail": self.detail,
            "subject": self.subject,
        }
