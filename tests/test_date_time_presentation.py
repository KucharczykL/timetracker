import json
from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from django.core.management import call_command
from django.http import HttpRequest
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone, translation

from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DatePartSpec,
    DateTimeFormatProfile,
    DateTimePresentation,
    date_time_presentation_for_request,
)


def test_default_presentation_formats_each_semantic_style() -> None:
    presentation = DateTimePresentation(
        profile=DEFAULT_DATE_TIME_FORMAT_PROFILE,
        locale="en-us",
        timezone=ZoneInfo("Europe/Prague"),
    )
    value = datetime(2026, 7, 22, 12, 5, tzinfo=UTC)

    assert presentation.format(value, "date") == "22/07/2026"
    assert presentation.format(value, "time") == "14:05"
    assert presentation.format(value, "datetime") == "22/07/2026 14:05"
    assert presentation.format(value, "month_year") == "July 2026"


def test_alternate_profile_controls_order_separators_and_hour_cycle() -> None:
    profile = DateTimeFormatProfile(
        date_parts=(
            DatePartSpec("year", "YYYY", 4),
            DatePartSpec("month", "MM", 2),
            DatePartSpec("day", "DD", 2),
        ),
        date_separator=".",
        segmented_date_separator="·",
        time_separator="h",
        date_time_separator=" @ ",
        hour_cycle="h12",
    )
    presentation = DateTimePresentation(
        profile=profile,
        locale="en-us",
        timezone=ZoneInfo("UTC"),
    )

    assert (
        presentation.format(datetime(2026, 7, 2, 17, 5, tzinfo=UTC), "datetime")
        == "2026.07.02 @ 05h05 PM"
    )


def test_aware_datetime_converts_before_calendar_fields_are_read() -> None:
    presentation = DateTimePresentation(
        profile=DEFAULT_DATE_TIME_FORMAT_PROFILE,
        locale="en-us",
        timezone=ZoneInfo("Pacific/Kiritimati"),
    )

    assert (
        presentation.format(datetime(2026, 1, 1, 23, 30, tzinfo=UTC), "datetime")
        == "02/01/2026 13:30"
    )


def test_plain_date_never_shifts_timezone() -> None:
    presentation = DateTimePresentation(
        profile=DEFAULT_DATE_TIME_FORMAT_PROFILE,
        locale="en-us",
        timezone=ZoneInfo("Pacific/Kiritimati"),
    )

    assert presentation.format(date(2026, 1, 1), "date") == "01/01/2026"


def test_naive_datetime_is_rejected() -> None:
    presentation = DateTimePresentation(
        profile=DEFAULT_DATE_TIME_FORMAT_PROFILE,
        locale="en-us",
        timezone=ZoneInfo("UTC"),
    )

    with pytest.raises(ValueError, match="aware datetime"):
        presentation.format(datetime(2026, 1, 1, 12, 0), "datetime")


def test_month_year_uses_presentation_locale_without_changing_ui_locale() -> None:
    presentation = DateTimePresentation(
        profile=DEFAULT_DATE_TIME_FORMAT_PROFILE,
        locale="cs",
        timezone=ZoneInfo("UTC"),
    )
    before = translation.get_language()

    assert presentation.format(date(2026, 7, 1), "month_year") == "červenec 2026"
    assert translation.get_language() == before


def test_presentation_and_nested_profile_are_immutable() -> None:
    presentation = DateTimePresentation(
        profile=DEFAULT_DATE_TIME_FORMAT_PROFILE,
        locale="en-us",
        timezone=ZoneInfo("UTC"),
    )

    with pytest.raises(FrozenInstanceError):
        presentation.locale = "cs"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        presentation.profile.date_separator = "."  # type: ignore[misc]


def test_client_config_is_exact_and_versioned() -> None:
    presentation = DateTimePresentation(
        profile=DEFAULT_DATE_TIME_FORMAT_PROFILE,
        locale="en-us",
        timezone=ZoneInfo("Europe/Prague"),
    )

    assert presentation.to_client_config() == {
        "version": 1,
        "locale": "en-us",
        "time_zone": "Europe/Prague",
        "profile": {
            "date_parts": [
                {"name": "day", "placeholder": "DD", "length": 2},
                {"name": "month", "placeholder": "MM", "length": 2},
                {"name": "year", "placeholder": "YYYY", "length": 4},
            ],
            "date_separator": "/",
            "segmented_date_separator": "-",
            "time_separator": ":",
            "date_time_separator": " ",
            "hour_cycle": "h23",
        },
    }


@override_settings(LANGUAGE_CODE="cs")
def test_request_factory_uses_active_timezone_and_caches_identity() -> None:
    request = HttpRequest()

    with timezone.override(ZoneInfo("Pacific/Kiritimati")):
        first = date_time_presentation_for_request(request)
        second = date_time_presentation_for_request(request)

    assert first is second
    assert first.locale == "cs"
    assert first.timezone.key == "Pacific/Kiritimati"


class _RootAttributeParser(HTMLParser):
    attributes: dict[str, str | None]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "html":
            self.attributes = dict(attrs)


def test_root_document_emits_active_client_contract(db) -> None:
    parser = _RootAttributeParser()
    parser.feed(Client().get(reverse("login")).content.decode())

    contract = json.loads(parser.attributes["data-date-time-presentation"] or "")
    assert contract["version"] == 1
    assert contract["locale"] == "en-us"
    assert contract["time_zone"] == "Europe/Prague"
    assert contract["profile"] == {
        "date_parts": [
            {"name": "day", "placeholder": "DD", "length": 2},
            {"name": "month", "placeholder": "MM", "length": 2},
            {"name": "year", "placeholder": "YYYY", "length": 4},
        ],
        "date_separator": "/",
        "segmented_date_separator": "-",
        "time_separator": ":",
        "date_time_separator": " ",
        "hour_cycle": "h23",
    }


def test_codegen_command_emits_date_time_presentation_type(tmp_path: Path) -> None:
    with override_settings(BASE_DIR=tmp_path):
        call_command("gen_element_types", verbosity=0)

    output = (tmp_path / "ts/generated/date-time-presentation.ts").read_text()
    assert 'export type DatePartName = "day" | "month" | "year";' in output
    assert 'export type HourCycle = "h12" | "h23";' in output
    assert "export interface DateTimePresentationConfig" in output
    assert "version: 1;" in output
    assert "profile: DateTimeFormatProfileConfig;" in output
