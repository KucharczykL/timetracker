"""One end of access, asked once.

Imports no act; acts never import acts.
"""

import datetime
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TypedDict

from django import forms
from django.db.models import Model
from django.http import QueryDict

from common.components.primitives import FormFields
from common.date_time_presentation import (
    DateTimePresentation,
    date_time_presentation_for_user,
)
from games.bulk_edit import form_refusal, stated_object, statement_unreadable
from games.bulk_parts import (
    AsksNothing,
    BulkChoice,
    ChoiceValue,
    Control,
    FieldName,
    Offered,
)
from games.commands.endpoint import WayActStatement
from games.end_ways import END_WAY_LABELS, EndWay, EndWays
from games.entry_forms import normalised_note
from games.forms import PrimitiveWidgetsMixin, TemporalFormField
from games.models import UserLibrary
from games.reads.calendar import calendar_today
from timetracker.temporal import TemporalValue


class AccessEndJson(TypedDict):
    """The carried statement; every key stated."""

    #: Null is an unknown day.
    when: str | None
    way: str
    note: str


_KEYS = frozenset(AccessEndJson.__required_keys__)

#: Leads where Not said is not offered.
_NO_WAY_CHOSEN = ("", "Choose…")


def encode_access_end(statement: WayActStatement) -> ChoiceValue:
    """Both unknown spellings encode as null."""
    carried: AccessEndJson = {
        "when": None if statement.when is None else statement.when.canonical,
        "way": statement.way.value,
        "note": statement.note,
    }
    return json.dumps(carried, sort_keys=True)


def decode_access_end(raw: ChoiceValue, ways: EndWays) -> WayActStatement:
    """Null decodes to `TemporalValue.unknown()`."""
    stated = stated_object(raw, _KEYS)
    if set(stated) != _KEYS:
        raise statement_unreadable(f"{raw!r} leaves out {sorted(_KEYS - set(stated))}")
    way, note = stated["way"], stated["note"]
    if not isinstance(way, str) or way not in {admitted.value for admitted in ways}:
        raise statement_unreadable(f"{raw!r} states a way this act does not take")
    if not isinstance(note, str):
        raise statement_unreadable(f"{raw!r} states a note that is no text")
    return WayActStatement(
        _when(raw, stated["when"]), EndWay(way), normalised_note(note)
    )


def _when(raw: ChoiceValue, value: object) -> TemporalValue:
    if value is None:
        return TemporalValue.unknown()
    if not isinstance(value, str):
        raise statement_unreadable(f"{raw!r} states a day that is no text")
    try:
        return TemporalValue.parse(value)
    except ValueError as malformed:
        raise statement_unreadable(f"{raw!r} states no day") from malformed


class BulkAccessEndForm(PrimitiveWidgetsMixin, forms.Form):
    """Way, day and note for every row."""

    way = forms.ChoiceField(label="What happened")
    note = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 2}), label="Note"
    )

    def __init__(
        self,
        data: QueryDict | None = None,
        *,
        prefix: FieldName,
        ways: EndWays,
        presentation: DateTimePresentation,
        today: datetime.date,
    ) -> None:
        super().__init__(data, prefix=prefix)
        choices = [(way.value, END_WAY_LABELS[way]) for way in ways]
        if EndWay.UNSTATED in ways:
            #: Unstated leads, preselected.
            choices.sort(key=lambda choice: choice[0] != EndWay.UNSTATED.value)
            self.initial.setdefault("way", EndWay.UNSTATED.value)
        else:
            choices.insert(0, _NO_WAY_CHOSEN)
        way = self.fields["way"]
        assert isinstance(way, forms.ChoiceField)
        way.choices = choices
        self.fields["ended"] = TemporalFormField(
            presentation=presentation,
            label="When",
            initial=TemporalValue.from_day(today),
        )
        self.order_fields(["way", "ended", "note"])

    def clean_note(self) -> str:
        return normalised_note(self.cleaned_data["note"])

    def statement(self) -> WayActStatement:
        cleaned = self.cleaned_data
        return WayActStatement(
            cleaned["ended"], EndWay(cleaned["way"]), cleaned["note"]
        )


@dataclass(frozen=True, slots=True)
class AccessEndQuestion:
    """Offer and decode over one way set."""

    ways: EndWays

    def decode(self, raw: ChoiceValue) -> WayActStatement:
        return decode_access_end(raw, self.ways)

    def choice[RowT: Model](self) -> BulkChoice[RowT]:
        def offer(
            library: UserLibrary, rows: Sequence[RowT], field_name: FieldName
        ) -> Offered:
            if not rows:
                #: The confirmation states there are no rows.
                return AsksNothing()
            return Control(FormFields(self._form(library, None, field_name)))

        def settle(library: UserLibrary, post: QueryDict) -> ChoiceValue:
            """Carried statement, else the form's."""
            #: Local: the act table imports this module.
            from games.views.bulk import CHOICE_FIELD

            carried = post.get(CHOICE_FIELD, "")
            if carried:
                return encode_access_end(self.decode(carried))
            form = self._form(library, post, CHOICE_FIELD)
            if not form.is_valid():
                raise form_refusal(form, labelled=True)
            return encode_access_end(form.statement())

        return BulkChoice(offer=offer, settle=settle)

    def _form(
        self, library: UserLibrary, data: QueryDict | None, field_name: FieldName
    ) -> BulkAccessEndForm:
        return BulkAccessEndForm(
            data,
            prefix=field_name,
            ways=self.ways,
            presentation=date_time_presentation_for_user(library.user),
            today=calendar_today(library),
        )
