"""One reason a pass must not commit."""

from dataclasses import dataclass
from enum import StrEnum
from typing import TypedDict

type MismatchSubject = str  # a row id, a library id, a table name
type MismatchDetail = str


class MismatchEntry(TypedDict):
    """The wire shape of one mismatch."""

    code: str
    detail: MismatchDetail
    subject: MismatchSubject


@dataclass(frozen=True, slots=True)
class Mismatch[CodeT: StrEnum]:
    """One reason the run must not commit."""

    code: CodeT
    subject: MismatchSubject
    detail: MismatchDetail

    def as_dict(self) -> MismatchEntry:
        return {
            "code": self.code.value,
            "detail": self.detail,
            "subject": self.subject,
        }
