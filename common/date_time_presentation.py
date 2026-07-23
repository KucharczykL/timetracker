"""Request-scoped formatting for every human-visible date and time.

Machine-readable dates and timestamps deliberately do not use this module.  Its
structured profile is shared with the browser so server- and client-rendered
display text can follow the same contract without exposing ``strftime`` patterns.
"""

from dataclasses import dataclass
from datetime import date, datetime
from functools import cache
from typing import Literal, TypedDict
from zoneinfo import ZoneInfo

from django.conf import settings
from django.http import HttpRequest
from django.utils import timezone as django_timezone
from django.utils.formats import date_format, get_format
from django.utils.translation import get_language, override

type DatePartName = Literal["day", "month", "year"]
type HourCycle = Literal["h12", "h23"]
# Each member is an exact display intent. A missing intent requires a design
# decision and a new style; callers must never substitute the nearest style.
type DateTimeStyle = Literal["date", "time", "datetime", "month", "month_year"]


@dataclass(frozen=True)
class DatePartSpec:
    """One numeric date segment in visible display order."""

    name: DatePartName
    placeholder: str
    input_length: int
    display_min_digits: int


@dataclass(frozen=True)
class DateTimeFormatProfile:
    """Structured punctuation, order, and clock rules for display values."""

    date_parts: tuple[DatePartSpec, DatePartSpec, DatePartSpec]
    date_separator: str
    segmented_date_separator: str
    time_separator: str
    date_time_separator: str
    hour_cycle: HourCycle


class DatePartConfig(TypedDict):
    name: DatePartName
    placeholder: str
    input_length: int
    display_min_digits: int


class DayPeriodsConfig(TypedDict):
    am: str
    pm: str


class DateTimeFormatProfileConfig(TypedDict):
    date_parts: list[DatePartConfig]
    date_separator: str
    segmented_date_separator: str
    time_separator: str
    date_time_separator: str
    hour_cycle: HourCycle


class DateTimePresentationConfig(TypedDict):
    version: Literal[1]
    locale: str
    time_zone: str
    profile: DateTimeFormatProfileConfig
    day_periods: DayPeriodsConfig


DEFAULT_DATE_TIME_FORMAT_PROFILE = DateTimeFormatProfile(
    date_parts=(
        DatePartSpec("day", "DD", input_length=2, display_min_digits=2),
        DatePartSpec("month", "MM", input_length=2, display_min_digits=2),
        DatePartSpec("year", "YYYY", input_length=4, display_min_digits=4),
    ),
    date_separator="/",
    segmented_date_separator="-",
    time_separator=":",
    date_time_separator=" ",
    hour_cycle="h23",
)


@cache
def _day_periods_for_locale(locale: str) -> DayPeriodsConfig:
    """Return the locale's AM/PM text shared by server and client formatting."""

    with override(locale):
        return {
            "am": date_format(datetime(2000, 1, 1, 0), "A"),
            "pm": date_format(datetime(2000, 1, 1, 12), "A"),
        }


def _format_numeric_date_part(value: int, minimum_digits: int) -> str:
    """Pad a number for display without truncating larger values."""

    return str(value).zfill(minimum_digits)


@dataclass(frozen=True)
class DateTimePresentation:
    """The immutable date/time display contract active for one request."""

    profile: DateTimeFormatProfile
    locale: str
    timezone: ZoneInfo

    def _localized(self, value: date | datetime) -> date | datetime:
        if not isinstance(value, datetime):
            return value
        if django_timezone.is_naive(value):
            raise ValueError("DateTimePresentation requires an aware datetime")
        return value.astimezone(self.timezone)

    def _format_date(self, value: date | datetime) -> str:
        part_values = {
            "day": value.day,
            "month": value.month,
            "year": value.year,
        }
        return self.profile.date_separator.join(
            _format_numeric_date_part(part_values[part.name], part.display_min_digits)
            for part in self.profile.date_parts
        )

    def _format_time(self, value: datetime) -> str:
        if self.profile.hour_cycle == "h23":
            hour = value.hour
            day_period = ""
        else:
            hour = value.hour % 12 or 12
            day_periods = _day_periods_for_locale(self.locale)
            day_period = f" {day_periods['am' if value.hour < 12 else 'pm']}"
        return f"{hour:02d}{self.profile.time_separator}{value.minute:02d}{day_period}"

    def format(self, value: date | datetime, style: DateTimeStyle) -> str:
        """Format ``value`` using a semantic style, never a caller pattern."""

        localized = self._localized(value)
        if style == "date":
            return self._format_date(localized)
        if style == "month":
            with override(self.locale):
                return date_format(localized, "F")
        if style == "month_year":
            with override(self.locale):
                return date_format(
                    localized,
                    get_format("YEAR_MONTH_FORMAT", lang=self.locale),
                )
        if not isinstance(localized, datetime):
            raise TypeError(f"{style} formatting requires a datetime")
        if style == "time":
            return self._format_time(localized)
        if style == "datetime":
            return (
                f"{self._format_date(localized)}"
                f"{self.profile.date_time_separator}"
                f"{self._format_time(localized)}"
            )
        raise ValueError(f"unknown date/time style: {style!r}")

    def to_client_config(self) -> DateTimePresentationConfig:
        """Return the versioned JSON-compatible browser contract."""

        return {
            "version": 1,
            "locale": self.locale,
            "time_zone": self.timezone.key,
            "profile": {
                "date_parts": [
                    {
                        "name": part.name,
                        "placeholder": part.placeholder,
                        "input_length": part.input_length,
                        "display_min_digits": part.display_min_digits,
                    }
                    for part in self.profile.date_parts
                ],
                "date_separator": self.profile.date_separator,
                "segmented_date_separator": self.profile.segmented_date_separator,
                "time_separator": self.profile.time_separator,
                "date_time_separator": self.profile.date_time_separator,
                "hour_cycle": self.profile.hour_cycle,
            },
            "day_periods": _day_periods_for_locale(self.locale),
        }


_REQUEST_CACHE_ATTRIBUTE = "_date_time_presentation"


def date_time_presentation_for_request(request: HttpRequest) -> DateTimePresentation:
    """Resolve and cache the presentation directly on ``request``."""

    cached = getattr(request, _REQUEST_CACHE_ATTRIBUTE, None)
    if isinstance(cached, DateTimePresentation):
        return cached

    active_timezone = django_timezone.get_current_timezone()
    zone = (
        active_timezone
        if isinstance(active_timezone, ZoneInfo)
        else ZoneInfo(django_timezone.get_current_timezone_name())
    )
    locale = getattr(request, "_date_format_locale", None)
    presentation = DateTimePresentation(
        profile=DEFAULT_DATE_TIME_FORMAT_PROFILE,
        locale=locale
        if isinstance(locale, str)
        else get_language() or settings.LANGUAGE_CODE,
        timezone=zone,
    )
    setattr(request, _REQUEST_CACHE_ATTRIBUTE, presentation)
    return presentation
