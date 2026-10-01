"""The forms that state a purchase."""

import datetime
import hashlib
import uuid
from enum import StrEnum
from typing import Any, ClassVar

from django import forms

from common.components import FormFieldGroup, FormFieldPresentation
from common.date_time_presentation import DateTimePresentation
from games.commands.endpoint import ActStatement
from games.endpoints import PURCHASE_REFUND
from games.entry_forms import (
    Submission,
    SubmissionKind,
    normalised_note,
)
from games.forms import (
    PrimitiveWidgetsMixin,
    RadioListWidget,
    TemporalFormField,
    apply_primitive_widget_classes,
)
from games.models import Purchase, PurchaseKind, UserLibrary
from games.price_fields import (
    PriceFields,
    ignore_fields,
    price_choice_of,
    price_group,
    price_presentations,
)
from games.reads.endpoints import stated
from games.writes.endpoint import KEEP, Restated
from games.writes.purchase import PurchaseDraft
from timetracker.temporal import TemporalValue

REFUND_CHANGED_SINCE_OPENED = (
    "This purchase's refund changed since you opened this page. "
    "Reload it and save again."
)


#: Literal, so Tailwind finds them.
REFUND_GROUP = "group/refund"
REFUNDED_ROW = "hidden group-has-[[value=refunded]:checked]/refund:block"


class RefundChoice(StrEnum):
    REFUNDED = "refunded"
    NOT_REFUNDED = "not_refunded"


def purchase_groups() -> list[FormFieldGroup]:
    return [
        FormFieldGroup("What", ("kind", "name"), look="hidden"),
        price_group(),
        FormFieldGroup("When", ("purchased",), look="hidden"),
    ]


def edit_groups() -> list[FormFieldGroup]:
    return [
        *purchase_groups(),
        FormFieldGroup(
            "Refund",
            ("refund", "refunded", "refund_note"),
            look="hidden",
            class_=REFUND_GROUP,
        ),
    ]


def edit_presentations() -> dict[str, FormFieldPresentation]:
    refunded_only = FormFieldPresentation(row_class=REFUNDED_ROW)
    return price_presentations() | {
        "refunded": refunded_only,
        "refund_note": refunded_only,
    }


def _purchase_fields(form: forms.Form, presentation: DateTimePresentation) -> None:
    form.fields["kind"] = forms.ChoiceField(
        choices=PurchaseKind.choices, label="What it bought"
    )
    form.fields["name"] = forms.CharField(required=False, label="Name")
    form.fields["purchased"] = TemporalFormField(
        presentation=presentation, label="Bought on"
    )
    form.fields["note"] = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 2}), label="Note"
    )
    apply_primitive_widget_classes(
        {name: form.fields[name] for name in ("kind", "name", "note")}
    )


class PurchaseAddForm(PrimitiveWidgetsMixin, Submission, PriceFields):
    """One purchase of a held copy."""

    kind: ClassVar[SubmissionKind] = "purchase-add"

    def __init__(
        self,
        *args,
        library: UserLibrary,
        presentation: DateTimePresentation,
        today: datetime.date,
        **kwargs,
    ):
        super().__init__(*args, user=library.user, **kwargs)
        _purchase_fields(self, presentation)
        self.initial.setdefault("kind", PurchaseKind.GAME.value)
        self.fields["purchased"].initial = TemporalValue.from_day(today)
        self.order_fields(
            ["kind", "name", "price", "amount", "currency", "purchased", "note"]
        )

    def clean_note(self) -> str:
        return normalised_note(self.cleaned_data["note"])

    def draft(self, entry_id: uuid.UUID) -> PurchaseDraft:
        cleaned = self.cleaned_data
        price = self.price_statement()
        if price is None:
            raise ValueError("Add purchase offers no 'No purchase'.")
        return PurchaseDraft(
            copy=entry_id,
            kind=cleaned["kind"],
            name=cleaned["name"],
            price=price,
            note=cleaned["note"],
            purchased=ActStatement(cleaned["purchased"], ""),
        )


#: A refund block's hash.
type RefundFingerprint = str


def _refund_block(refund: ActStatement | None) -> RefundFingerprint:
    """One refund block, hashed."""
    words = "" if refund is None else "\x1f".join((str(refund.when), refund.note))
    return hashlib.sha256(words.encode()).hexdigest()


def _standing_refund(purchase: Purchase) -> ActStatement | None:
    standing = stated(purchase, PURCHASE_REFUND)
    return None if standing is None else ActStatement(standing.when, standing.note)


def refund_seen(purchase: Purchase) -> RefundFingerprint:
    """The refund block this purchase renders."""
    return _refund_block(_standing_refund(purchase))


class PurchaseEditForm(PrimitiveWidgetsMixin, PriceFields):
    """A purchase's facts and refund restated."""

    #: Unset until clean; reading it raises.
    _refund: Restated[ActStatement]

    refund = forms.TypedChoiceField(
        coerce=RefundChoice,
        choices=[
            (RefundChoice.NOT_REFUNDED.value, "Not refunded"),
            (RefundChoice.REFUNDED.value, "Refunded"),
        ],
        widget=RadioListWidget,
        label="Refund",
    )
    refund_note = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 2}), label="Refund note"
    )
    #: The refund this page showed.
    refund_seen = forms.CharField(required=False, widget=forms.HiddenInput)

    def __init__(
        self,
        *args,
        purchase: Purchase,
        presentation: DateTimePresentation,
        **kwargs,
    ):
        standing = _standing_refund(purchase)
        initial: dict[str, Any] = {
            "kind": purchase.kind,
            "name": purchase.name,
            "price": price_choice_of(purchase).value,
            "amount": "" if not purchase.amount else str(purchase.amount),
            "currency": purchase.currency,
            "purchased": purchase.purchased,
            "note": purchase.note,
            "refund": (
                RefundChoice.NOT_REFUNDED if standing is None else RefundChoice.REFUNDED
            ).value,
            "refunded": None if standing is None else standing.when,
            "refund_note": "" if standing is None else standing.note,
            "refund_seen": refund_seen(purchase),
        }
        kwargs["initial"] = initial | dict(kwargs.get("initial") or {})
        super().__init__(*args, user=purchase.library.user, **kwargs)
        self._purchase = purchase
        self._standing = standing
        _purchase_fields(self, presentation)
        self.fields["refunded"] = TemporalFormField(
            presentation=presentation, label="Refunded on"
        )
        self.order_fields(
            [
                "kind",
                "name",
                "price",
                "amount",
                "currency",
                "purchased",
                "refund",
                "refunded",
                "refund_note",
                "note",
            ]
        )

    def clean_note(self) -> str:
        return normalised_note(self.cleaned_data["note"])

    def clean_refund_note(self) -> str:
        return normalised_note(self.cleaned_data["refund_note"])

    def clean(self) -> dict[str, Any] | None:
        cleaned = super().clean()
        if cleaned is None:
            return cleaned
        submitted: ActStatement | None = None
        if cleaned.get("refund") is RefundChoice.REFUNDED:
            submitted = ActStatement(
                cleaned.get("refunded"), cleaned.get("refund_note", "")
            )
        else:
            ignore_fields(self, "refunded", "refund_note")
        seen = cleaned.get("refund_seen") or ""
        untouched = _refund_block(submitted) == seen
        #: Moved since opened, and changed here.
        if seen != refund_seen(self._purchase) and not untouched:
            self.add_error(None, REFUND_CHANGED_SINCE_OPENED)
        #: An untouched block states nothing.
        self._refund = KEEP if untouched or submitted == self._standing else submitted
        return cleaned

    def purchased(self) -> ActStatement:
        return ActStatement(
            self.cleaned_data["purchased"], self._purchase.purchase_note
        )

    def refund_statement(self) -> Restated[ActStatement]:
        """Set by clean; unset before it."""
        return self._refund
