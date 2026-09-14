"""One reason a pass must not commit."""

from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class Mismatch[CodeT: StrEnum]:
    """One reason the run must not commit."""

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
