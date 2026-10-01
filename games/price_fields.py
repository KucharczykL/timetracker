"""A purchase's price, as forms state it."""

from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, ClassVar, cast

from django import forms

from common.components import FormFieldGroup, FormFieldPresentation
from games.commands.purchase import UNKNOWN_PRICE, StatedPrice
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


PRICE_LABELS = {
    PriceChoice.PAID: "Paid",
    PriceChoice.FREE: "Free",
    PriceChoice.UNKNOWN: "Unknown",
    PriceChoice.NONE: "No purchase",
}

#: Literal, so Tailwind finds them.
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

    price = forms.ChoiceField(widget=RadioListWidget, label="Price")
    amount = forms.CharField(required=False, label="Amount")
    currency = forms.CharField(
        required=False,
        max_length=3,
        widget=forms.TextInput(
            attrs={"x-mask": "aaa", "x-data": "", "class": "uppercase"}
        ),
        label="Currency",
    )

    def _price_fields(self, user: object) -> None:
        cast(forms.ChoiceField, self.fields["price"]).choices = [
            (choice.value, PRICE_LABELS[choice]) for choice in self.price_choices
        ]
        default = resolve_str_for_user(user, "DEFAULT_PURCHASE_CURRENCY")
        self.fields["currency"].widget.attrs["placeholder"] = default
        self.initial.setdefault("price", PriceChoice.PAID.value)
        if not self.initial.get("currency"):
            self.initial["currency"] = default

    def _clean_price(self, cleaned: dict[str, Any]) -> None:
        choice = cleaned.get("price")
        if choice not in (PriceChoice.PAID, PriceChoice.FREE):
            ignore_fields(self, "amount", "currency")
            return
        if choice == PriceChoice.FREE:
            ignore_fields(self, "amount")
        else:
            text = (cleaned.get("amount") or "").strip()
            if not text:
                self.add_error("amount", AMOUNT_REQUIRED)
            else:
                try:
                    cleaned["amount"] = Decimal(text)
                except InvalidOperation:
                    self.add_error("amount", NOT_AN_AMOUNT)
        currency = (cleaned.get("currency") or "").strip().upper()
        if currency:
            cleaned["currency"] = currency
        elif "currency" not in self.errors:
            self.add_error("currency", CURRENCY_REQUIRED)

    def stated_price(self) -> StatedPrice | None:
        """None states no purchase."""
        cleaned = self.cleaned_data
        match PriceChoice(cleaned["price"]):
            case PriceChoice.PAID:
                return StatedPrice(cleaned["amount"], cleaned["currency"])
            case PriceChoice.FREE:
                return StatedPrice(Decimal(0), cleaned["currency"])
            case PriceChoice.UNKNOWN:
                return UNKNOWN_PRICE
            case PriceChoice.NONE:
                return None


def price_group() -> FormFieldGroup:
    return FormFieldGroup(
        "Price", ("price", "amount", "currency"), look="hidden", class_="group/price"
    )


def price_presentations() -> dict[str, FormFieldPresentation]:
    return {
        "amount": FormFieldPresentation(row_class=AMOUNT_ROW),
        "currency": FormFieldPresentation(row_class=CURRENCY_ROW),
    }
