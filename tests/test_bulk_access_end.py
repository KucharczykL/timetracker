"""The one question an end act asks."""

from datetime import date
from zoneinfo import ZoneInfo

import pytest
from django.http import QueryDict

from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DateTimePresentation,
)
from games.bulk_access_end import (
    AccessEndQuestion,
    BulkAccessEndForm,
    decode_access_end,
    encode_access_end,
)
from games.bulk_parts import AsksNothing
from games.commands.endpoint import WayActStatement
from games.end_ways import EndWay
from games.events.dispatch import CommandRejected
from games.models import DEVICE_WAYS, ENTRY_WAYS
from games.views.bulk import CHOICE_FIELD
from timetracker.temporal import TemporalValue, temporal_input_name

TODAY = date(2026, 10, 4)
PRESENTATION = DateTimePresentation(
    DEFAULT_DATE_TIME_FORMAT_PROFILE, "en-us", ZoneInfo("UTC")
)


def _post(**fields: str) -> QueryDict:
    post = QueryDict(mutable=True)
    post.update(fields)
    return post


def _form(ways, data=None) -> BulkAccessEndForm:
    return BulkAccessEndForm(
        data,
        prefix=CHOICE_FIELD,
        ways=ways,
        presentation=PRESENTATION,
        today=TODAY,
    )


@pytest.mark.parametrize(
    "when",
    [
        TemporalValue.from_day(date(2024, 5, 1)),
        TemporalValue.parse("2024-05"),
        TemporalValue.unknown(),
    ],
)
def test_a_statement_survives_its_own_encoding(when):
    statement = WayActStatement(when, EndWay.SOLD, "to a friend")

    decoded = decode_access_end(encode_access_end(statement), ENTRY_WAYS)

    assert decoded.way == EndWay.SOLD
    assert decoded.note == "to a friend"
    assert decoded.when == when


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "[]",
        '{"way": "sold", "note": ""}',
        '{"when": null, "way": "sold", "note": "", "extra": 1}',
        '{"when": null, "way": "nonsense", "note": ""}',
        '{"when": null, "way": ["sold"], "note": ""}',
        '{"when": null, "way": "sold", "note": 5}',
        '{"when": 5, "way": "sold", "note": ""}',
        '{"when": "someday", "way": "sold", "note": ""}',
        '{"when": "", "way": "sold", "note": ""}',
    ],
)
def test_an_unreadable_statement_is_refused(raw):
    with pytest.raises(CommandRejected):
        decode_access_end(raw, ENTRY_WAYS)


def test_a_way_the_act_does_not_take_is_refused():
    raw = encode_access_end(WayActStatement(None, EndWay.UNSTATED, ""))

    with pytest.raises(CommandRejected):
        decode_access_end(raw, DEVICE_WAYS)


def test_the_copy_form_leads_with_not_said_and_today():
    form = _form(ENTRY_WAYS)

    assert form.fields["way"].choices[0] == ("unstated", "Not said")
    assert form.fields["ended"].initial == TemporalValue.from_day(TODAY)
    assert list(form.fields) == ["way", "ended", "note"]


def test_the_device_form_refuses_no_way():
    form = _form(DEVICE_WAYS, _post(**{f"{CHOICE_FIELD}-way": ""}))

    assert form.fields["way"].choices[0][0] == ""
    assert not form.is_valid()
    assert "way" in form.errors


@pytest.mark.django_db
def test_settling_is_idempotent(owned_library):
    choice = AccessEndQuestion(ENTRY_WAYS).choice()
    name = f"{CHOICE_FIELD}-ended"
    once = choice.settle(
        owned_library,
        _post(
            **{
                f"{CHOICE_FIELD}-way": "sold",
                f"{CHOICE_FIELD}-note": " boxed \r\n",
                temporal_input_name(name, "kind"): "date",
                temporal_input_name(name, "start_year"): "2024",
                temporal_input_name(name, "start_month"): "5",
                temporal_input_name(name, "start_day"): "1",
            }
        ),
    )

    assert choice.settle(owned_library, _post(**{CHOICE_FIELD: once})) == once
    assert decode_access_end(once, ENTRY_WAYS).note == "boxed"


@pytest.mark.django_db
def test_settling_refuses_an_invalid_form_by_label(owned_library):
    choice = AccessEndQuestion(DEVICE_WAYS).choice()

    with pytest.raises(CommandRejected) as refused:
        choice.settle(owned_library, _post(**{f"{CHOICE_FIELD}-way": ""}))

    assert refused.value.sentence.startswith("What happened:")


@pytest.mark.django_db
def test_no_rows_asks_nothing(owned_library):
    offered = AccessEndQuestion(ENTRY_WAYS).choice().offer(owned_library, [], "choice")

    assert isinstance(offered, AsksNothing)
