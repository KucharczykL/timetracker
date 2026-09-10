"""One reason a gated pass must not commit."""

from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class Mismatch[CodeT: StrEnum]:
    """One reason the run must not commit.

    Each pass names its own code type. Two
    enumerations may spell one value alike, and
    members of both compare and hash equal, so a
    set mixing them counts one where it holds two.
    """

    code: CodeT
    #: Whatever the code names.
    subject: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {
            "code": self.code.value,
            "detail": self.detail,
            "subject": self.subject,
        }
