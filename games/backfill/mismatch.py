"""One reason a gated pass must not commit."""

from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class Mismatch:
    """One reason the run must not commit.

    Each pass enumerates its own codes.
    """

    code: StrEnum
    #: Whatever the code names.
    subject: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {
            "code": self.code.value,
            "detail": self.detail,
            "subject": self.subject,
        }
