"""The forms that state a purchase."""

import datetime
import hashlib
import uuid
from enum import StrEnum
from typing import Any

from django import forms

from common.components import FormFieldGroup, FormFieldPresentation
from common.date_time_presentation import DateTimePresentation
from games.commands.endpoint import ActStatement
from games.endpoints import PURCHASE_REFUND
from games.entry_forms import (
    SubmissionAct,
    SubmissionNoun,
    _Submission,
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
from games.writes.endpoint import KEEP, Keep
from games.writes.purchase import PurchaseDraft
from timetracker.temporal import TemporalValue

REFUND_CHANGED_SINCE_OPENED = (
    "This purchase's refund changed since you opened this page. "
    "Reload it and save again."
)


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
            class_="group/refund",
        ),
    ]


def edit_presentations() -> dict[str, FormFieldPresentation]:
    refunded_only = FormFieldPresentation(
        row_class="hidden group-has-[[value=refunded]:checked]/refund:block"
    )
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


class PurchaseAddForm(PrimitiveWidgetsMixin, _Submission, PriceFields):
    """One purchase of a held copy."""

    noun: SubmissionNoun = "purchase"
    act: SubmissionAct = "add"

    def __init__(
        self,
        *args,
        library: UserLibrary,
        presentation: DateTimePresentation,
        today: datetime.date,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        _purchase_fields(self, presentation)
        self.initial.setdefault("kind", PurchaseKind.GAME.value)
        self.fields["purchased"].initial = TemporalValue.from_day(today)
        self._price_fields(library.user)
        self.order_fields(
            ["kind", "name", "price", "amount", "currency", "purchased", "note"]
        )

    def clean_note(self) -> str:
        return normalised_note(self.cleaned_data["note"])

    def clean(self) -> dict[str, Any] | None:
        cleaned = super().clean()
        if cleaned is not None:
            self._clean_price(cleaned)
        return cleaned

    def draft(self, entry_id: uuid.UUID) -> PurchaseDraft:
        cleaned = self.cleaned_data
        price = self.stated_price()
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


def _refund_block(when: TemporalValue | None, note: str, *, refunded: bool) -> str:
    """One refund block, hashed."""
    words = "\x1f".join((str(when), note)) if refunded else ""
    return hashlib.sha256(words.encode()).hexdigest()


def refund_seen(purchase: Purchase) -> str:
    """The refund block this purchase renders."""
    standing = stated(purchase, PURCHASE_REFUND)
    if standing is None:
        return _refund_block(None, "", refunded=False)
    return _refund_block(standing.when, standing.note, refunded=True)


class PurchaseEditForm(PrimitiveWidgetsMixin, PriceFields):
    """A purchase's facts and refund restated."""

    refund = forms.ChoiceField(
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
        standing = stated(purchase, PURCHASE_REFUND)
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
        super().__init__(*args, **kwargs)
        self.purchase = purchase
        self.standing = standing
        _purchase_fields(self, presentation)
        self.fields["refunded"] = TemporalFormField(
            presentation=presentation, label="Refunded on"
        )
        self._price_fields(purchase.library.user)
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
        self._clean_price(cleaned)
        if cleaned.get("refund") != RefundChoice.REFUNDED:
            ignore_fields(self, "refunded", "refund_note")
        seen = cleaned.get("refund_seen") or ""
        submitted = _refund_block(
            cleaned.get("refunded"),
            cleaned.get("refund_note", ""),
            refunded=cleaned.get("refund") == RefundChoice.REFUNDED,
        )
        #: Only a refund this page changed.
        if seen != refund_seen(self.purchase) and submitted != seen:
            self.add_error(None, REFUND_CHANGED_SINCE_OPENED)
        return cleaned

    def purchased(self) -> ActStatement:
        return ActStatement(self.cleaned_data["purchased"], self.purchase.purchase_note)

    def refund_statement(self) -> ActStatement | None | Keep:
        """KEEP keeps; None voids."""
        cleaned = self.cleaned_data
        if cleaned["refund"] != RefundChoice.REFUNDED:
            return KEEP if self.standing is None else None
        statement = ActStatement(
            cleaned.get("refunded"), cleaned.get("refund_note", "")
        )
        if self.standing is not None and statement == ActStatement(
            self.standing.when, self.standing.note
        ):
            return KEEP
        return statement
