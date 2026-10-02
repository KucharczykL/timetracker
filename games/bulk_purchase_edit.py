"""Edit many purchases' kind, price, day, note."""

import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, ClassVar, TypedDict, cast

from django import forms
from django.contrib.auth.models import User
from django.http import QueryDict
from django.template.defaultfilters import truncatechars

from common.components import FormFieldGroup, FormFieldPresentation
from common.components.primitives import FormFields, P
from common.date_time_presentation import (
    DateTimePresentation,
    date_time_presentation_for_user,
)
from common.temporal_presentation import present_temporal_value
from games.bulk_actions import BulkAction
from games.bulk_edit import (
    form_refusal,
    keeping,
    log_overwrite,
    restated,
    settled,
    stated_object,
    statement_unreadable,
)
from games.bulk_parts import (
    ActTitle,
    AsksNothing,
    BulkChoice,
    ChoiceValue,
    Control,
    EventRows,
    FieldName,
    Offered,
    RowOutcome,
)
from games.bulk_purchases import (
    PURCHASE_PREVIEW,
    purchase_resolution,
    purchase_scope,
    removed_purchase,
)
from games.commands.endpoint import ActStatement
from games.commands.purchase import UNKNOWN_PRICE, StatedPrice, check_price
from games.entry_forms import normalised_note
from games.events.append import SourceMetadata
from games.events.dispatch import CommandRejected
from games.events.idempotency import IdempotencyKey
from games.events.purchase import PricePayload, PurchaseKindValue, price_payload
from games.forms import (
    KEEP,
    ChoiceSearchSelectWidget,
    Keep,
    PrimitiveWidgetsMixin,
    TemporalFormField,
    TemporalWidget,
    UnsetFieldsForm,
    UnsetWidget,
)
from games.models import Purchase, PurchaseKind, UserLibrary
from games.price_fields import (
    PriceChoice,
    PriceFields,
    price_group,
    price_presentations,
)
from games.reads.purchase_facts import purchase_fact_changes
from games.views.purchase_menu import price_words
from games.writes.answers import answered
from games.writes.purchase import SUBJECT, restate_purchase
from timetracker.temporal import TemporalValue


class PurchaseEditJson(TypedDict, total=False):
    """The wire statement; absent is unstated."""

    kind: PurchaseKindValue
    #: Null is an unknown price.
    price: PricePayload | None
    #: Null is an unknown day.
    purchased: str | None
    note: str


_KEYS = frozenset(PurchaseEditJson.__optional_keys__)

NOTHING_STATED = "Choose a kind, a price, a day or a note."
UNKNOWN_DAY = "Unknown day"
NOT_EDITED_BY_THIS_BATCH = (
    "That purchase was not changed by this batch, so it was left as it is."
)
PURCHASE_REMOVED = "That purchase is removed. Restore it first."

#: How long a kept note reads.
_KEPT_NOTE_LENGTH = 40


@dataclass(frozen=True, slots=True)
class PurchaseEditStatement:
    """What one batch states; None leaves alone.

    An unknown `purchased` restates no day.
    Never collapse it through `stated_date`:
    None here keeps the row's day.
    """

    kind: PurchaseKind | None
    price: StatedPrice | None
    purchased: TemporalValue | None
    note: str | None

    def __post_init__(self) -> None:
        if _nothing(self.kind, self.price, self.purchased, self.note):
            raise ValueError("An edit states a kind, a price, a day or a note.")

    @classmethod
    def of(
        cls,
        kind: PurchaseKind | None,
        price: StatedPrice | None,
        purchased: TemporalValue | None,
        note: str | None,
    ) -> PurchaseEditStatement | None:
        """None where nothing is stated."""
        if _nothing(kind, price, purchased, note):
            return None
        return cls(kind, price, purchased, note)

    def encode(self) -> ChoiceValue:
        stated: PurchaseEditJson = {}
        if self.kind is not None:
            stated["kind"] = cast(PurchaseKindValue, self.kind.value)
        if self.price is not None:
            stated["price"] = price_payload(self.price.amount, self.price.currency)
        if self.purchased is not None:
            stated["purchased"] = self.purchased.canonical
        if self.note is not None:
            stated["note"] = self.note
        return json.dumps(stated, sort_keys=True)

    @classmethod
    def decode(cls, raw: ChoiceValue) -> PurchaseEditStatement:
        """An earlier settle's answer, or a refusal."""
        stated = stated_object(raw, _KEYS)
        kind = stated.get("kind")
        if "kind" in stated and kind not in PurchaseKind.values:
            raise statement_unreadable(f"{raw!r} states a kind that is no word")
        price = None if "price" not in stated else _price(raw, stated["price"])
        purchased = (
            None if "purchased" not in stated else _purchased(raw, stated["purchased"])
        )
        note = stated.get("note")
        if "note" in stated and not isinstance(note, str):
            raise statement_unreadable(f"{raw!r} states a note that is no text")
        try:
            return cls(
                None if kind is None else PurchaseKind(kind),
                price,
                purchased,
                None if note is None else normalised_note(note),
            )
        except ValueError as empty:
            raise statement_unreadable(f"{raw!r} states nothing") from empty


def _nothing(*facts: object) -> bool:
    return all(fact is None for fact in facts)


def _price(raw: ChoiceValue, value: object) -> StatedPrice:
    """`check_price` at settle, not per row."""
    if value is None:
        return UNKNOWN_PRICE
    if not isinstance(value, dict) or set(value) != {"amount", "currency"}:
        raise statement_unreadable(f"{raw!r} states a price that is no price")
    amount, currency = value["amount"], value["currency"]
    if not isinstance(amount, str) or not isinstance(currency, str):
        raise statement_unreadable(f"{raw!r} states a price that is no price")
    try:
        return check_price(StatedPrice(Decimal(amount), currency).normalized())
    except (InvalidOperation, CommandRejected) as refused:
        raise statement_unreadable(f"{raw!r} states no price") from refused


def _purchased(raw: ChoiceValue, value: object) -> TemporalValue:
    """Null is an unknown day."""
    if value is None:
        return TemporalValue.unknown()
    if not isinstance(value, str):
        raise statement_unreadable(f"{raw!r} states a day that is no text")
    try:
        day = TemporalValue.parse(value)
    except ValueError as malformed:
        raise statement_unreadable(f"{raw!r} states no day") from malformed
    if day.canonical is None:
        raise statement_unreadable(f"{raw!r} states an unknown day as text")
    return day


# ── The question ─────────────────────────────────────────────────────────────


def _note_shown(note: str) -> str:
    return truncatechars(note, _KEPT_NOTE_LENGTH) if note else "no note"


class BulkPurchaseEditForm(PrimitiveWidgetsMixin, UnsetFieldsForm, PriceFields):
    """Empty keeps; ⊘ states no note."""

    price_choices: ClassVar[tuple[PriceChoice, ...]] = (
        PriceChoice.KEEP,
        PriceChoice.PAID,
        PriceChoice.FREE,
        PriceChoice.UNKNOWN,
    )

    kind = forms.TypedChoiceField(
        choices=PurchaseKind.choices,
        coerce=PurchaseKind,
        empty_value=None,
        required=False,
        label="What it bought",
        widget=ChoiceSearchSelectWidget(),
    )
    note = forms.CharField(
        required=False,
        widget=UnsetWidget(forms.Textarea(attrs={"rows": 2}), none_label="No note"),
    )

    def __init__(
        self,
        data: QueryDict | None = None,
        *,
        prefix: FieldName,
        user: User,
        presentation: DateTimePresentation,
        rows: Sequence[Purchase] = (),
    ) -> None:
        super().__init__(
            data, prefix=prefix, user=user, initial={"price": PriceChoice.KEEP.value}
        )
        self.fields["purchased"] = TemporalFormField(
            presentation=presentation,
            label="Bought on",
            widget=UnsetWidget(
                TemporalWidget(presentation=presentation, label="Bought on"),
                none_label=UNKNOWN_DAY,
            ),
        )
        self.order_fields(["kind", "price", "amount", "currency", "purchased", "note"])
        #: Kind and note hint as placeholders.
        self._keep_hints: Mapping[FieldName, str] = {}
        if rows:
            cast(
                ChoiceSearchSelectWidget, self.fields["kind"].widget
            ).placeholder = keeping(
                rows, lambda row: row.kind, lambda word: PurchaseKind(word).label
            )
            self._keep_hints = {
                "price": keeping(rows, price_words, str),
                "purchased": keeping(
                    rows,
                    lambda row: row.purchased,
                    lambda day: present_temporal_value(day, presentation),
                ),
            }
            note = cast(UnsetWidget, self.fields["note"].widget).widget
            note.attrs["placeholder"] = keeping(rows, lambda row: row.note, _note_shown)

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean() or {}
        if self.errors:
            return cleaned
        note: str | Keep = cleaned["note"]
        statement = PurchaseEditStatement.of(
            cleaned["kind"],
            self.price_change(),
            _day_stated(cleaned["purchased"]),
            None if note is KEEP else normalised_note(note),
        )
        if statement is None:
            raise forms.ValidationError(NOTHING_STATED)
        self._statement = statement
        return cleaned

    def keep_presentations(self) -> Mapping[FieldName, FormFieldPresentation]:
        """Each "Keep:" line, under its field."""
        return {
            name: FormFieldPresentation(
                after_control=P(class_="text-type-micro text-body")[hint]
            )
            for name, hint in self._keep_hints.items()
        }

    def price_change(self) -> StatedPrice | None:
        """None keeps each row's price."""
        if self.cleaned_data["price"] is PriceChoice.KEEP:
            return None
        return self.price_statement()

    def statement(self) -> PurchaseEditStatement:
        """The valid form, as one statement."""
        return self._statement


def _day_stated(cleaned: TemporalValue | Keep | None) -> TemporalValue | None:
    """Keep keeps; ⊘ states no day."""
    if cleaned is KEEP:
        return None
    if cleaned is None:
        return TemporalValue.unknown()
    return cleaned


def _form(
    library: UserLibrary,
    data: QueryDict | None,
    field_name: FieldName,
    rows: Sequence[Purchase] = (),
) -> BulkPurchaseEditForm:
    return BulkPurchaseEditForm(
        data,
        prefix=field_name,
        user=library.user,
        presentation=date_time_presentation_for_user(library.user),
        rows=rows,
    )


def offer_edit(
    library: UserLibrary, rows: Sequence[Purchase], field_name: FieldName
) -> Offered:
    """Every field is prefixed `field_name`."""
    if not rows:
        #: The confirmation states there are no rows.
        return AsksNothing()
    form = _form(library, None, field_name, rows)
    return Control(
        FormFields(
            form,
            groups=[
                FormFieldGroup("What", ("kind",), look="hidden"),
                price_group(),
                FormFieldGroup("When", ("purchased", "note"), look="hidden"),
            ],
            presentations={**price_presentations(), **form.keep_presentations()},
        )
    )


def settle_edit(library: UserLibrary, post: QueryDict) -> ChoiceValue:
    """Carried statement, else the form's."""
    #: Local: the act table imports this module.
    from games.views.bulk import CHOICE_FIELD

    carried = post.get(CHOICE_FIELD, "")
    if carried:
        return PurchaseEditStatement.decode(carried).encode()
    form = _form(library, post, CHOICE_FIELD)
    if not form.is_valid():
        raise form_refusal(form, labelled=True)
    return form.statement().encode()


EDIT_CHOICE: BulkChoice[Purchase] = BulkChoice(offer=offer_edit, settle=settle_edit)


# ── Forward ──────────────────────────────────────────────────────────────────


def _source() -> SourceMetadata:
    return {"bulk": {"action": PURCHASE_EDIT.name}}


def _state(
    actor: User,
    purchase: Purchase,
    statement: PurchaseEditStatement,
    *,
    purchase_note: str,
    idempotency_key: IdempotencyKey,
    correlation_id: uuid.UUID,
) -> RowOutcome:
    """One dispatch: a row never commits half."""
    return RowOutcome.of(
        restate_purchase(
            actor,
            purchase,
            kind=None
            if statement.kind is None
            else cast(PurchaseKindValue, statement.kind.value),
            price=statement.price,
            note=statement.note,
            purchased=None
            if statement.purchased is None
            else ActStatement(statement.purchased, purchase_note),
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            source_metadata=_source(),
        ).result
    )


def edit_one(
    actor: User,
    purchase: Purchase,
    *,
    choice: ChoiceValue | None,
    idempotency_key: IdempotencyKey,
    correlation_id: uuid.UUID,
) -> RowOutcome:
    with answered(SUBJECT):
        statement = settled(
            choice,
            PurchaseEditStatement.decode,
            act_name=PURCHASE_EDIT.name,
            row_description=f"Purchase {purchase.pk} of library {actor.library.pk}",
        )
    return _state(
        actor,
        purchase,
        statement,
        #: The day moves; its note stays.
        purchase_note=purchase.purchase_note,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )


# ── Backward ─────────────────────────────────────────────────────────────────


def edit_back(
    actor: User,
    purchase_id: uuid.UUID,
    *,
    undoes: uuid.UUID,
    idempotency_key: IdempotencyKey,
    correlation_id: uuid.UUID,
) -> RowOutcome:
    """Each changed fact back as before."""
    purchase = removed_purchase(actor, purchase_id)
    with answered(SUBJECT):
        changes = purchase_fact_changes(actor.library, purchase_id, undoes)
        if not changes.changed_any:
            raise CommandRejected(
                f"batch {undoes} changed no fact of Purchase {purchase_id}",
                sentence=NOT_EDITED_BY_THIS_BATCH,
            )
        held_kind = PurchaseKind(purchase.kind)
        held_price = StatedPrice(purchase.amount, purchase.currency)
        held_day = ActStatement(purchase.purchased, purchase.purchase_note)
        day_back = restated(changes.purchased, held_day)
        restatement = PurchaseEditStatement.of(
            restated(changes.kind, held_kind),
            restated(changes.price, held_price),
            _day_of(day_back),
            restated(changes.note, purchase.note),
        )
        if restatement is None:
            #: Every changed fact is back already.
            return RowOutcome.UNCHANGED
        if purchase.removed_at is not None:
            raise CommandRejected(
                f"Purchase {purchase_id} is removed", sentence=PURCHASE_REMOVED
            )
    described = f"Purchase {purchase.pk} of library {purchase.library_id}"
    for change, held, fact in (
        (changes.kind, held_kind, "kind"),
        (changes.price, held_price, "price"),
        (changes.purchased, held_day, "purchased"),
        (changes.note, purchase.note, "note"),
    ):
        log_overwrite(
            change,
            held,
            act_name=PURCHASE_EDIT.name,
            fact=fact,
            row_description=described,
        )
    return _state(
        actor,
        purchase,
        restatement,
        purchase_note=purchase.purchase_note if day_back is None else day_back.note,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )


def _day_of(day_back: ActStatement | None) -> TemporalValue | None:
    """An undated day back is unknown."""
    if day_back is None:
        return None
    return TemporalValue.unknown() if day_back.when is None else day_back.when


PURCHASE_EDIT = BulkAction(
    name="purchase.edit",
    label="Edit…",
    title=ActTitle(one="Edit this purchase", many="Edit {count} purchases"),
    confirm_label="Save",
    subject=SUBJECT,
    color="blue",
    undo_rows=EventRows(Purchase),
    fallback="games:list_purchases",
    scope=purchase_scope,
    resolve=purchase_resolution,
    run=edit_one,
    inverse=edit_back,
    preview=PURCHASE_PREVIEW,
    choice=EDIT_CHOICE,
)
