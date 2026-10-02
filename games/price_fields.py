"""A purchase's price, as forms state it."""

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, ClassVar, cast

from django import forms
from django.contrib.auth.models import User

from common.components import FormFieldGroup, FormFieldPresentation
from games.commands.purchase import (
    AMOUNT_WITHOUT_CURRENCY,
    UNKNOWN_PRICE,
    StatedPrice,
    check_price,
)
from games.events.dispatch import CommandRejected
from games.forms import RadioListWidget
from games.models import Purchase
from timetracker.settings_resolver import resolve_str_for_user

AMOUNT_REQUIRED = "State what you paid, or choose another price."
NOT_AN_AMOUNT = "Enter an amount, such as 19.99."
CURRENCY_REQUIRED = "State the currency, such as EUR."


class PriceChoice(StrEnum):
    """What the price segment states."""

    PAID = "paid"
    FREE = "free"
    UNKNOWN = "unknown"
    #: Add to library only: no purchase.
    NONE = "none"
    #: Bulk Edit only: each row's own.
    KEEP = "keep"


PRICE_LABELS: Mapping[PriceChoice, str] = {
    PriceChoice.PAID: "Paid",
    PriceChoice.FREE: "Free",
    PriceChoice.UNKNOWN: "Unknown",
    PriceChoice.NONE: "No purchase",
    PriceChoice.KEEP: "Keep",
}

#: Literal, so Tailwind finds them.
PRICE_GROUP = "group/price"
AMOUNT_ROW = "hidden group-has-[[value=paid]:checked]/price:block"
CURRENCY_ROW = (
    "hidden group-has-[[value=paid]:checked]/price:block "
    "group-has-[[value=free]:checked]/price:block"
)


def price_choice_of(purchase: Purchase) -> PriceChoice:
    if purchase.amount is None:
        return PriceChoice.UNKNOWN
    return PriceChoice.FREE if purchase.amount == 0 else PriceChoice.PAID


def ignore_fields(form: forms.Form, *names: str) -> None:
    """A hidden row holds no error."""
    for name in names:
        form.errors.pop(name, None)
        form.cleaned_data.pop(name, None)


class PriceFields(forms.Form):
    """The price segment, amount and currency."""

    price_choices: ClassVar[tuple[PriceChoice, ...]] = (
        PriceChoice.PAID,
        PriceChoice.FREE,
        PriceChoice.UNKNOWN,
    )

    price = forms.TypedChoiceField(
        coerce=PriceChoice, widget=RadioListWidget, label="Price"
    )
    amount = forms.CharField(required=False, label="Amount")
    currency = forms.CharField(
        required=False,
        max_length=3,
        widget=forms.TextInput(
            attrs={"x-mask": "aaa", "x-data": "", "class": "uppercase"}
        ),
        label="Currency",
    )

    def __init__(self, *args, user: User, **kwargs):
        super().__init__(*args, **kwargs)
        cast(forms.ChoiceField, self.fields["price"]).choices = [
            (choice.value, PRICE_LABELS[choice]) for choice in self.price_choices
        ]
        default = resolve_str_for_user(user, "DEFAULT_PURCHASE_CURRENCY")
        self.fields["currency"].widget.attrs["placeholder"] = default
        self.initial.setdefault("price", PriceChoice.PAID.value)
        if not self.initial.get("currency"):
            self.initial["currency"] = default

    def clean(self) -> dict[str, Any] | None:
        cleaned = super().clean()
        if cleaned is not None:
            self._clean_price(cleaned)
        return cleaned

    def _clean_price(self, cleaned: dict[str, Any]) -> None:
        choice = cleaned.get("price")
        if choice not in (PriceChoice.PAID, PriceChoice.FREE):
            ignore_fields(self, "amount", "currency")
            return
        if choice == PriceChoice.FREE:
            ignore_fields(self, "amount")
        else:
            self._clean_amount(cleaned)
        self._clean_currency(cleaned)
        if choice == PriceChoice.PAID and self._amount_and_currency_parsed():
            self._check_price(cleaned)

    def _amount_and_currency_parsed(self) -> bool:
        return "amount" not in self.errors and "currency" not in self.errors

    def _check_price(self, cleaned: dict[str, Any]) -> None:
        """The command's rules, shown on the field."""
        try:
            check_price(StatedPrice(cleaned["amount"], cleaned["currency"]))
        except CommandRejected as refusal:
            if refusal.sentence == AMOUNT_WITHOUT_CURRENCY:
                self.add_error("currency", refusal.sentence)
            else:
                self.add_error("amount", refusal.sentence or NOT_AN_AMOUNT)

    def _clean_amount(self, cleaned: dict[str, Any]) -> None:
        text = (cleaned.get("amount") or "").strip()
        if not text:
            self.add_error("amount", AMOUNT_REQUIRED)
            return
        try:
            cleaned["amount"] = Decimal(text)
        except InvalidOperation:
            self.add_error("amount", NOT_AN_AMOUNT)

    def _clean_currency(self, cleaned: dict[str, Any]) -> None:
        currency = (cleaned.get("currency") or "").strip().upper()
        if currency:
            cleaned["currency"] = currency
        elif "currency" not in self.errors:
            self.add_error("currency", CURRENCY_REQUIRED)

    def price_statement(self) -> StatedPrice | None:
        """None states no purchase."""
        cleaned = self.cleaned_data
        choice: PriceChoice = cleaned["price"]
        match choice:
            case PriceChoice.PAID:
                return StatedPrice(cleaned["amount"], cleaned["currency"])
            case PriceChoice.FREE:
                return StatedPrice(Decimal(0), cleaned["currency"])
            case PriceChoice.UNKNOWN:
                return UNKNOWN_PRICE
            case PriceChoice.NONE:
                return None
            case PriceChoice.KEEP:
                raise ValueError("Keep states no price; read it first.")


def price_group() -> FormFieldGroup:
    return FormFieldGroup(
        "Price", ("price", "amount", "currency"), look="hidden", class_=PRICE_GROUP
    )


def price_presentations() -> dict[str, FormFieldPresentation]:
    return {
        "amount": FormFieldPresentation(row_class=AMOUNT_ROW),
        "currency": FormFieldPresentation(row_class=CURRENCY_ROW),
    }
