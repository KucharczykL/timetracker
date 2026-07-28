import json
from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.http import HttpRequest
from django.test import Client, RequestFactory, override_settings
from django.urls import reverse
from django.utils import timezone, translation

from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    Affixes,
    DateTimeFormatProfile,
    DateTimePresentation,
    DateTimeSegmentSpec,
    build_format_profile,
    date_time_format_profile,
    date_time_presentation_for_request,
)
from timetracker import config as config_module
from timetracker import settings_resolver
from timetracker.settings_commands import change_user_setting


@pytest.mark.parametrize(
    ("profile_id", "expected_date", "expected_time", "expected_datetime"),
    [
        ("iso_8601", "2026-07-22", "14:05", "2026-07-22 14:05"),
        ("dmy_24h", "22/07/2026", "14:05", "22/07/2026 14:05"),
        ("mdy_12h", "07/22/2026", "02:05 PM", "07/22/2026 02:05 PM"),
    ],
)
def test_registered_profiles_format_each_semantic_style(
    profile_id: str,
    expected_date: str,
    expected_time: str,
    expected_datetime: str,
) -> None:
    presentation = DateTimePresentation(
        profile=date_time_format_profile(profile_id),
        locale="en-us",
        timezone=ZoneInfo("Europe/Prague"),
    )
    value = datetime(2026, 7, 22, 12, 5, tzinfo=UTC)

    assert presentation.format(value, "date") == expected_date
    assert presentation.format(value, "time") == expected_time
    assert presentation.format(value, "datetime") == expected_datetime
    assert presentation.format(value, "month") == "July"
    assert presentation.format(value, "month_year") == "July 2026"


@pytest.mark.parametrize(
    ("hour", "expected"),
    [(0, "12:05 AM"), (12, "12:05 PM")],
)
def test_mdy_12h_formats_midnight_and_noon(hour: int, expected: str) -> None:
    presentation = DateTimePresentation(
        profile=date_time_format_profile("mdy_12h"),
        locale="en-us",
        timezone=ZoneInfo("UTC"),
    )

    assert (
        presentation.format(datetime(2026, 7, 2, hour, 5, tzinfo=UTC), "time")
        == expected
    )


def test_unsupported_profile_id_fails_loudly() -> None:
    with pytest.raises(ValueError, match="Unsupported date/time format"):
        date_time_format_profile("rfc_3339")


def test_alternate_profile_controls_order_separators_and_hour_cycle() -> None:
    profile = build_format_profile(
        ("year", "month", "day"),
        hour_cycle="h12",
        display_separator=".",
        segmented_separator="·",
        time_separator="h",
        date_time_separator=" @ ",
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


def _numeric(
    name: str, *, width: int, display: int, prefix: str
) -> DateTimeSegmentSpec:
    return DateTimeSegmentSpec(
        name=name,  # type: ignore[arg-type]
        kind="numeric",
        run="date",
        placeholder=name.upper(),
        input_length=width,
        display_min_digits=display,
        min_value=1,
        max_value=9999,
        display=Affixes(prefix=prefix),
    )


def test_segments_can_have_shorter_display_than_input_width() -> None:
    """Display width is independent of typed width — an unpadded d/m/yyyy.

    ``build_format_profile`` ties the two together because every registered
    profile pads; the contract itself does not require it.
    """

    presentation = DateTimePresentation(
        profile=DateTimeFormatProfile(
            segments=(
                _numeric("day", width=2, display=1, prefix=""),
                _numeric("month", width=2, display=1, prefix="/"),
                _numeric("year", width=4, display=4, prefix="/"),
            ),
            hour_cycle="h23",
        ),
        locale="en-us",
        timezone=ZoneInfo("UTC"),
    )

    assert presentation.format(date(2026, 7, 2), "date") == "2/7/2026"


def test_h12_time_uses_the_exact_client_day_period_for_non_english_locale() -> None:
    presentation = DateTimePresentation(
        profile=build_format_profile(
            ("year", "month", "day"),
            hour_cycle="h12",
            display_separator="/",
            segmented_separator="-",
        ),
        locale="cs",
        timezone=ZoneInfo("UTC"),
    )

    assert presentation.format(
        datetime(2026, 7, 2, 17, 5, tzinfo=UTC), "time"
    ).endswith(presentation.to_client_config()["day_periods"]["pm"])


def test_aware_datetime_converts_before_calendar_fields_are_read() -> None:
    presentation = DateTimePresentation(
        profile=DEFAULT_DATE_TIME_FORMAT_PROFILE,
        locale="en-us",
        timezone=ZoneInfo("Pacific/Kiritimati"),
    )

    assert (
        presentation.format(datetime(2026, 1, 1, 23, 30, tzinfo=UTC), "datetime")
        == "2026-01-02 13:30"
    )


def test_plain_date_never_shifts_timezone() -> None:
    presentation = DateTimePresentation(
        profile=DEFAULT_DATE_TIME_FORMAT_PROFILE,
        locale="en-us",
        timezone=ZoneInfo("Pacific/Kiritimati"),
    )

    assert presentation.format(date(2026, 1, 1), "date") == "2026-01-01"


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


def test_month_uses_exact_month_only_intent() -> None:
    presentation = DateTimePresentation(
        profile=DEFAULT_DATE_TIME_FORMAT_PROFILE,
        locale="cs",
        timezone=ZoneInfo("UTC"),
    )

    assert presentation.format(date(2026, 7, 1), "month") == "červenec"


def test_presentation_and_nested_profile_are_immutable() -> None:
    presentation = DateTimePresentation(
        profile=DEFAULT_DATE_TIME_FORMAT_PROFILE,
        locale="en-us",
        timezone=ZoneInfo("UTC"),
    )

    with pytest.raises(FrozenInstanceError):
        presentation.locale = "cs"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        presentation.profile.hour_cycle = "h12"  # type: ignore[misc]


def test_client_config_is_exact_and_versioned() -> None:
    """The one exhaustive pin on the wire shape.

    Spelled out rather than rebuilt from the profile, so a field that silently
    changes name, moves run, or loses its bounds fails here."""

    presentation = DateTimePresentation(
        profile=DEFAULT_DATE_TIME_FORMAT_PROFILE,
        locale="en-us",
        timezone=ZoneInfo("Europe/Prague"),
    )

    assert presentation.to_client_config() == (
        {
            "version": 2,
            "locale": "en-us",
            "time_zone": "Europe/Prague",
            "profile": {
                "segments": [
                    {
                        "name": "year",
                        "kind": "numeric",
                        "run": "date",
                        "placeholder": "YYYY",
                        "input_length": 4,
                        "display_min_digits": 4,
                        "min_value": 1,
                        "max_value": 9999,
                        "display": {"prefix": "", "suffix": ""},
                        "segmented": {"prefix": "", "suffix": ""},
                    },
                    {
                        "name": "month",
                        "kind": "numeric",
                        "run": "date",
                        "placeholder": "MM",
                        "input_length": 2,
                        "display_min_digits": 2,
                        "min_value": 1,
                        "max_value": 12,
                        "display": {"prefix": "-", "suffix": ""},
                        "segmented": {"prefix": "-", "suffix": ""},
                    },
                    {
                        "name": "day",
                        "kind": "numeric",
                        "run": "date",
                        "placeholder": "DD",
                        "input_length": 2,
                        "display_min_digits": 2,
                        "min_value": 1,
                        "max_value": 31,
                        "display": {"prefix": "-", "suffix": ""},
                        "segmented": {"prefix": "-", "suffix": ""},
                    },
                    {
                        "name": "hour",
                        "kind": "numeric",
                        "run": "time",
                        "placeholder": "HH",
                        "input_length": 2,
                        "display_min_digits": 2,
                        "min_value": 0,
                        "max_value": 23,
                        "display": {"prefix": " ", "suffix": ""},
                        "segmented": {"prefix": " ", "suffix": ""},
                    },
                    {
                        "name": "minute",
                        "kind": "numeric",
                        "run": "time",
                        "placeholder": "mm",
                        "input_length": 2,
                        "display_min_digits": 2,
                        "min_value": 0,
                        "max_value": 59,
                        "display": {"prefix": ":", "suffix": ""},
                        "segmented": {"prefix": ":", "suffix": ""},
                    },
                ],
                "hour_cycle": "h23",
            },
            "day_periods": {"am": "AM", "pm": "PM"},
            "session_time_zone_display": "account",
        }
    )


@override_settings(LANGUAGE_CODE="cs")
def test_request_factory_uses_active_timezone_and_caches_identity(db) -> None:
    request = HttpRequest()

    with timezone.override(ZoneInfo("Pacific/Kiritimati")):
        first = date_time_presentation_for_request(request)
        second = date_time_presentation_for_request(request)

    assert first is second
    assert first.locale == "cs"
    assert first.timezone.key == "Pacific/Kiritimati"


@override_settings(LANGUAGE_CODE="en-us")
def test_request_factory_captures_active_language(db) -> None:
    request = HttpRequest()

    with translation.override("cs"):
        presentation = date_time_presentation_for_request(request)

    assert presentation.locale == "cs"


@pytest.mark.django_db
def test_request_factory_uses_personal_datetime_format() -> None:
    user = get_user_model().objects.create_user(username="profile-user")
    change_user_setting(user, "DATETIME_FORMAT", "mdy_12h")
    request = RequestFactory().get("/")
    request.user = user

    presentation = date_time_presentation_for_request(request)

    assert presentation.profile is date_time_format_profile("mdy_12h")


def test_request_factory_uses_environment_datetime_format(
    monkeypatch, tmp_path: Path, db
) -> None:
    # DATETIME_FORMAT resolves from the env var below without touching the DB,
    # but SESSION_TIME_ZONE_DISPLAY has no such override here, so resolving the
    # full presentation still needs the site-settings DB layer underneath it.
    monkeypatch.setenv("DATETIME_FORMAT", "dmy_24h")
    monkeypatch.setenv("ENV_FILE", str(tmp_path / "missing.env"))
    monkeypatch.setenv("INI_FILE", str(tmp_path / "missing.ini"))
    config_module.reset_caches()
    settings_resolver.clear_cache()
    request = RequestFactory().get("/")

    try:
        presentation = date_time_presentation_for_request(request)
        assert presentation.profile is date_time_format_profile("dmy_24h")
    finally:
        config_module.reset_caches()
        settings_resolver.clear_cache()


class _RootAttributeParser(HTMLParser):
    attributes: dict[str, str | None]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "html":
            self.attributes = dict(attrs)


def test_root_document_emits_active_client_contract(db) -> None:
    parser = _RootAttributeParser()
    parser.feed(Client().get(reverse("login")).content.decode())

    contract = json.loads(parser.attributes["data-date-time-presentation"] or "")
    assert contract["version"] == 2
    assert contract["locale"] == "en-us"
    assert contract["time_zone"] == "UTC"
    segments = contract["profile"]["segments"]
    assert [(segment["name"], segment["run"]) for segment in segments] == [
        ("year", "date"),
        ("month", "date"),
        ("day", "date"),
        ("hour", "time"),
        ("minute", "time"),
    ]
    assert [segment["display"]["prefix"] for segment in segments] == [
        "",
        "-",
        "-",
        " ",
        ":",
    ]
    assert contract["profile"]["hour_cycle"] == "h23"
    assert contract["day_periods"] == {"am": "AM", "pm": "PM"}


def test_authenticated_root_document_emits_personal_mdy_12h_contract(
    db,
) -> None:
    user = get_user_model().objects.create_user(username="root-profile-user")
    change_user_setting(user, "DATETIME_FORMAT", "mdy_12h")
    client = Client()
    client.force_login(user)
    parser = _RootAttributeParser()

    parser.feed(client.get(reverse("games:list_games")).content.decode())

    contract = json.loads(parser.attributes["data-date-time-presentation"] or "")
    segments = contract["profile"]["segments"]
    assert [segment["name"] for segment in segments] == [
        "month",
        "day",
        "year",
        "hour",
        "minute",
        # h12 is the only reason this segment exists at all.
        "day_period",
    ]
    assert [segment["display"]["prefix"] for segment in segments[:3]] == ["", "/", "/"]
    assert contract["profile"]["hour_cycle"] == "h12"
    hour = next(segment for segment in segments if segment["name"] == "hour")
    assert (hour["min_value"], hour["max_value"]) == (1, 12)
    assert "profile_id" not in contract
    assert "profile_id" not in contract["profile"]


@override_settings(LANGUAGE_CODE="en-us")
def test_root_document_keeps_ui_language_separate_from_formatting_locale(
    db,
) -> None:
    parser = _RootAttributeParser()

    with translation.override("cs"):
        parser.feed(Client().get(reverse("login")).content.decode())

    contract = json.loads(parser.attributes["data-date-time-presentation"] or "")
    assert contract["locale"] == "en-us"
    assert parser.attributes["lang"] == "cs"


def test_codegen_command_emits_date_time_presentation_type(tmp_path: Path) -> None:
    with override_settings(BASE_DIR=tmp_path):
        call_command("gen_element_types", verbosity=0)

    output = (tmp_path / "ts/generated/date-time-presentation.ts").read_text()
    assert (
        'export type SegmentName = "day" | "month" | "year" | "hour" | "minute"'
        ' | "day_period";'
    ) in output
    assert 'export type SegmentKind = "numeric" | "day_period";' in output
    assert 'export type SegmentRun = "date" | "time";' in output
    assert 'export type HourCycle = "h12" | "h23";' in output
    assert "export interface DateTimePresentationConfig" in output
    assert "version: 2;" in output
    assert "profile: DateTimeFormatProfileConfig;" in output
    assert "day_periods: DayPeriodsConfig;" in output
    assert "segments: SegmentConfig[];" in output
    assert "input_length: number;" in output
    assert "display_min_digits: number;" in output
    assert "min_value: number;" in output
    assert "display: AffixesConfig;" in output
