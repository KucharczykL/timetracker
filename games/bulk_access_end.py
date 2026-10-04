"""One end of access, asked once.

Imports no act: the device act and the
copy act both read it.
"""

import datetime
import json
from collections.abc import Sequence

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
from games.end_ways import END_WAY_LABELS, EndWay
from games.entry_forms import normalised_note
from games.forms import PrimitiveWidgetsMixin, TemporalFormField
from games.models import UserLibrary
from games.reads.calendar import calendar_today
from timetracker.temporal import TemporalValue

_KEYS = frozenset({"when", "way", "note"})

#: Leads where no way says nothing.
_NO_WAY_CHOSEN = ("", "Choose…")


def encode_access_end(statement: WayActStatement) -> ChoiceValue:
    """Null is an unknown day."""
    when = None if statement.when is None else statement.when.canonical
    return json.dumps(
        {"when": when, "way": statement.way.value, "note": statement.note},
        sort_keys=True,
    )


def decode_access_end(raw: ChoiceValue, ways: Sequence[EndWay]) -> WayActStatement:
    """An earlier settle's answer, or a refusal."""
    stated = stated_object(raw, _KEYS)
    if set(stated) != _KEYS:
        raise statement_unreadable(f"{raw!r} leaves out {sorted(_KEYS - set(stated))}")
    way, note = stated["way"], stated["note"]
    if way not in {admitted.value for admitted in ways}:
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
        day = TemporalValue.parse(value)
    except ValueError as malformed:
        raise statement_unreadable(f"{raw!r} states no day") from malformed
    if day.canonical is None:
        raise statement_unreadable(f"{raw!r} states an unknown day as text")
    return day


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
        ways: Sequence[EndWay],
        presentation: DateTimePresentation,
        today: datetime.date,
    ) -> None:
        super().__init__(data, prefix=prefix)
        choices = [(way.value, END_WAY_LABELS[way]) for way in ways]
        if EndWay.UNSTATED in ways:
            #: "Not said" leads.
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


def _form(
    library: UserLibrary,
    data: QueryDict | None,
    field_name: FieldName,
    ways: Sequence[EndWay],
) -> BulkAccessEndForm:
    return BulkAccessEndForm(
        data,
        prefix=field_name,
        ways=ways,
        presentation=date_time_presentation_for_user(library.user),
        today=calendar_today(library),
    )


def access_end_choice[RowT: Model](ways: Sequence[EndWay]) -> BulkChoice[RowT]:
    """The question, over the act's ways."""

    def offer(
        library: UserLibrary, rows: Sequence[RowT], field_name: FieldName
    ) -> Offered:
        if not rows:
            #: The confirmation states there are no rows.
            return AsksNothing()
        return Control(FormFields(_form(library, None, field_name, ways)))

    def settle(library: UserLibrary, post: QueryDict) -> ChoiceValue:
        """Carried statement, else the form's."""
        #: Local: the act table imports this module.
        from games.views.bulk import CHOICE_FIELD

        carried = post.get(CHOICE_FIELD, "")
        if carried:
            return encode_access_end(decode_access_end(carried, ways))
        form = _form(library, post, CHOICE_FIELD, ways)
        if not form.is_valid():
            raise form_refusal(form, labelled=True)
        return encode_access_end(form.statement())

    return BulkChoice(offer=offer, settle=settle)
