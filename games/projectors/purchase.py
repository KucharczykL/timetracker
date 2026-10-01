"""Current-state rows for purchases."""

import uuid
from decimal import Decimal
from typing import ClassVar

from games.events.envelope import RecordedEvent
from games.events.projection import HandlerMap, Projector, ProjectorFamily
from games.events.purchase import (
    PURCHASE_AMOUNT_CHANGED,
    PURCHASE_CORRECTED,
    PURCHASE_CREATED,
    PURCHASE_ENTRY_CHANGED,
    PURCHASE_KIND_CHANGED,
    PURCHASE_NAME_CHANGED,
    PURCHASE_NOTE_CHANGED,
    PURCHASE_REMOVED,
    PURCHASE_RESTORED,
)
from games.models import PURCHASE_DAY_COLUMNS, Purchase


def _amount(text: str | None) -> Decimal | None:
    return None if text is None else Decimal(text)


class Purchases(Projector):
    """One row per purchase."""

    family_name = ProjectorFamily.CURRENT_STATE

    def _created(self, event: RecordedEvent) -> None:
        #: Never names the mark; removal survives replay.
        payload = event.payload
        self.project(
            Purchase,
            event,
            entry_id=uuid.UUID(payload["entry"]["id"]),
            kind=payload["kind"],
            name=payload["name"],
            amount=_amount(payload["amount"]),
            currency=payload["currency"],
            note=payload["note"],
            created_at=event.recorded_at,
            **self.opening_columns(
                PURCHASE_DAY_COLUMNS, event, note=payload["purchase_note"]
            ),
        )

    def _kind_changed(self, event: RecordedEvent) -> None:
        self.amend(Purchase, event, kind=event.payload["kind"])

    def _name_changed(self, event: RecordedEvent) -> None:
        self.amend(Purchase, event, name=event.payload["name"])

    def _note_changed(self, event: RecordedEvent) -> None:
        self.amend(Purchase, event, note=event.payload["note"])

    def _amount_changed(self, event: RecordedEvent) -> None:
        self.amend(
            Purchase,
            event,
            amount=_amount(event.payload["amount"]),
            currency=event.payload["currency"],
        )

    def _entry_changed(self, event: RecordedEvent) -> None:
        self.amend(Purchase, event, entry_id=uuid.UUID(event.payload["entry"]["id"]))

    def _purchase_corrected(self, event: RecordedEvent) -> None:
        self.project_corrected(PURCHASE_DAY_COLUMNS, event)

    def _removed(self, event: RecordedEvent) -> None:
        self.amend(Purchase, event, removed_at=event.recorded_at)

    def _restored(self, event: RecordedEvent) -> None:
        self.amend(Purchase, event, removed_at=None)

    handles: ClassVar[HandlerMap] = {
        PURCHASE_CREATED: _created,
        PURCHASE_KIND_CHANGED: _kind_changed,
        PURCHASE_NAME_CHANGED: _name_changed,
        PURCHASE_NOTE_CHANGED: _note_changed,
        PURCHASE_AMOUNT_CHANGED: _amount_changed,
        PURCHASE_ENTRY_CHANGED: _entry_changed,
        PURCHASE_CORRECTED: _purchase_corrected,
        PURCHASE_REMOVED: _removed,
        PURCHASE_RESTORED: _restored,
    }
