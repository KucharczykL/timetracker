"""One act on many rows, declared once.

Making the value declares it; `games/views/bulk.py` runs any of them.

An act may write two aggregates: the reclassification appends a created
record beside the session that became it, under one correlation id. An
Undo reading every aggregate of the batch would hand a record's key to
a command that reads sessions, and refuse every row of its own batch.
"""

import inspect
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from django.db.models import Model

from common.components.primitives import ButtonColor
from common.returns import UrlName
from games.bulk_parts import (
    ActTitle,
    BulkActionName,
    BulkChoice,
    Caution,
    PreviewColumn,
    Resolve,
    RunRow,
    Scope,
    UndoRow,
    UndoRows,
)
from games.writes.answers import SubjectNoun

_TABLE: dict[BulkActionName, BulkAction[Any]] = {}


@dataclass(frozen=True, slots=True)
class BulkAction[RowT: Model]:
    """One act, run and undone."""

    name: BulkActionName
    #: The act in a person's words.
    label: str
    #: Its heading, in both counts.
    title: ActTitle
    #: Its submit.
    confirm_label: str
    #: The noun `answered()` speaks of.
    subject: SubjectNoun
    #: What the act does to a row, in the button's colours.
    color: ButtonColor
    #: Where its Undo reads its rows.
    undo_rows: UndoRows
    #: Where the act returns without an origin.
    fallback: UrlName
    scope: Scope[RowT]
    resolve: Resolve[RowT]
    run: RunRow[RowT]
    inverse: UndoRow
    #: What the confirmation shows of each row.
    preview: tuple[PreviewColumn[RowT], ...]
    #: What the act asks for first, or nothing.
    choice: BulkChoice[RowT] | None = None
    #: A note the confirmation shows, or nothing.
    caution: Caution[RowT] | None = None

    def __post_init__(self) -> None:
        """Refuse a declaration that cannot run."""
        if self.name in _TABLE:
            raise ValueError(
                f"{self.name!r} is already declared. An act names itself once."
            )
        for role, callable_, facts in (
            ("run", self.run, ("choice", "idempotency_key", "correlation_id")),
            ("inverse", self.inverse, ("undoes", "idempotency_key", "correlation_id")),
        ):
            called = getattr(callable_, "__name__", repr(callable_))
            stated = inspect.signature(callable_).parameters
            for fact in facts:
                if fact not in stated:
                    raise ValueError(
                        f"{self.name!r} states a {called} that takes no {fact}."
                    )
                if stated[fact].kind is not inspect.Parameter.KEYWORD_ONLY:
                    raise ValueError(
                        f"{self.name!r}'s {role} ({called}) takes {fact} "
                        "by position. Two of the three facts are text, so "
                        "position cannot tell them apart."
                    )
        _TABLE[self.name] = self


def bulk_action(name: BulkActionName) -> BulkAction[Any] | None:
    """The act that name declares, or none."""
    return _TABLE.get(name)


#: Every act, keyed by name. Read-only.
BULK_ACTIONS: Mapping[BulkActionName, BulkAction[Any]] = MappingProxyType(_TABLE)


#: Imported last: each module declares its acts.
from games import (  # noqa: F401
    bulk_entry_edit,
    bulk_finish,
    bulk_game_edit,
    bulk_platform_edit,
    bulk_playthrough_acts,
    bulk_purchase_edit,
    bulk_reclassification,
    bulk_removal,
    bulk_session_edit,
)
