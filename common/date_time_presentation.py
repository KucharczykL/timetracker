"""Request-scoped formatting for every human-visible date and time.

Machine-readable dates and timestamps deliberately do not use this module.  Its
structured profile is shared with the browser so server- and client-rendered
display text can follow the same contract without exposing ``strftime`` patterns.
"""

from dataclasses import dataclass
from datetime import date, datetime
from functools import cache
from types import MappingProxyType
from typing import Literal, TypedDict
from zoneinfo import ZoneInfo

from django.conf import settings
from django.http import HttpRequest
from django.utils import timezone as django_timezone
from django.utils.formats import date_format, get_format
from django.utils.translation import get_language, override

from timetracker.settings_resolver import resolve_str_for_user

type SegmentName = Literal["day", "month", "year", "hour", "minute", "day_period"]
type SegmentKind = Literal["numeric", "day_period"]
# Which styles a segment participates in: "date" segments render for the "date"
# style, "time" segments for "time", and both for "datetime".
type SegmentRun = Literal["date", "time"]
type HourCycle = Literal["h12", "h23"]
# Each member is an exact display intent. A missing intent requires a design
# decision and a new style; callers must never substitute the nearest style.
type DateTimeStyle = Literal["date", "time", "datetime", "month", "month_year"]


@dataclass(frozen=True)
class Affixes:
    """Literal text printed immediately before and after one segment.

    Both sides rather than a single joiner, so suffix-shaped formats stay
    expressible (``2026年7月27日``, or a trailing dot) instead of being a
    special case the walk has to know about.
    """

    prefix: str = ""
    suffix: str = ""


@dataclass(frozen=True)
class DateTimeSegmentSpec:
    """One segment in visible display order — a numeric part or the day period.

    ``min_value``/``max_value`` are carried here rather than derived by the
    widget, so the clock rules (h12 hours are 1–12, h23 are 0–23) live in one
    place. The day period bounds its two states as 0–1: it steps like any other
    segment.
    """

    name: SegmentName
    kind: SegmentKind
    run: SegmentRun
    placeholder: str
    input_length: int
    display_min_digits: int
    min_value: int
    max_value: int
    display: Affixes = Affixes()
    segmented: Affixes = Affixes()


@dataclass(frozen=True)
class DateTimeFormatProfile:
    """Structured punctuation, order, and clock rules for display values."""

    segments: tuple[DateTimeSegmentSpec, ...]
    hour_cycle: HourCycle

    def segments_for(self, *runs: SegmentRun) -> tuple[DateTimeSegmentSpec, ...]:
        """The profile's segments belonging to ``runs``, in display order.

        The composition axis for widgets: a date field takes ``("date",)``, a
        datetime field both runs, and a time field falls out for free.
        """

        return tuple(segment for segment in self.segments if segment.run in runs)


class AffixesConfig(TypedDict):
    prefix: str
    suffix: str


class SegmentConfig(TypedDict):
    name: SegmentName
    kind: SegmentKind
    run: SegmentRun
    placeholder: str
    input_length: int
    display_min_digits: int
    min_value: int
    max_value: int
    display: AffixesConfig
    segmented: AffixesConfig


class DayPeriodsConfig(TypedDict):
    am: str
    pm: str


class DateTimeFormatProfileConfig(TypedDict):
    segments: list[SegmentConfig]
    hour_cycle: HourCycle


class DateTimePresentationConfig(TypedDict):
    version: Literal[2]
    locale: str
    time_zone: str
    profile: DateTimeFormatProfileConfig
    day_periods: DayPeriodsConfig


_DATE_PART_SHAPES: dict[SegmentName, tuple[str, int, int, int]] = {
    # name: (placeholder, width, minimum, maximum). Days are bounded at 31 for
    # every month — the exact length is a calendar question the value carries,
    # not a segment property.
    "year": ("YYYY", 4, 1, 9999),
    "month": ("MM", 2, 1, 12),
    "day": ("DD", 2, 1, 31),
}


def _date_segments(
    order: tuple[SegmentName, SegmentName, SegmentName],
    *,
    display_separator: str,
    segmented_separator: str,
) -> tuple[DateTimeSegmentSpec, ...]:
    """The date run in ``order``, joined by the two separators.

    Both separators land on the *following* segment, so the leading one is
    empty and the walk's "drop the first prefix" rule needs no exception here.
    """

    return tuple(
        DateTimeSegmentSpec(
            name=name,
            kind="numeric",
            run="date",
            placeholder=placeholder,
            input_length=width,
            display_min_digits=width,
            min_value=minimum,
            max_value=maximum,
            display=Affixes(prefix="" if index == 0 else display_separator),
            segmented=Affixes(prefix="" if index == 0 else segmented_separator),
        )
        for index, name in enumerate(order)
        for placeholder, width, minimum, maximum in (_DATE_PART_SHAPES[name],)
    )


def _time_segments(
    *,
    hour_cycle: HourCycle,
    time_separator: str,
    date_time_separator: str,
    day_period_separator: str = " ",
) -> tuple[DateTimeSegmentSpec, ...]:
    """The time run: hour, minute, and — under h12 — a trailing day period.

    The hour's prefix is the date/time glue, which is exactly why formatting a
    time on its own needs no separate rule: the walk drops the first prefix it
    emits.
    """

    segments = (
        DateTimeSegmentSpec(
            name="hour",
            kind="numeric",
            run="time",
            placeholder="HH",
            input_length=2,
            display_min_digits=2,
            min_value=1 if hour_cycle == "h12" else 0,
            max_value=12 if hour_cycle == "h12" else 23,
            display=Affixes(prefix=date_time_separator),
            segmented=Affixes(prefix=date_time_separator),
        ),
        DateTimeSegmentSpec(
            name="minute",
            kind="numeric",
            run="time",
            placeholder="mm",
            input_length=2,
            display_min_digits=2,
            min_value=0,
            max_value=59,
            display=Affixes(prefix=time_separator),
            segmented=Affixes(prefix=time_separator),
        ),
    )
    if hour_cycle == "h23":
        return segments
    return segments + (
        DateTimeSegmentSpec(
            name="day_period",
            kind="day_period",
            run="time",
            placeholder="--",
            input_length=2,
            display_min_digits=0,
            min_value=0,
            max_value=1,
            display=Affixes(prefix=day_period_separator),
            segmented=Affixes(prefix=day_period_separator),
        ),
    )


def build_format_profile(
    order: tuple[SegmentName, SegmentName, SegmentName],
    *,
    hour_cycle: HourCycle,
    display_separator: str,
    segmented_separator: str,
    time_separator: str = ":",
    date_time_separator: str = " ",
) -> DateTimeFormatProfile:
    """Assemble a profile from a date order and the punctuation between runs.

    The registered profiles and any test profile go through here, so the
    segment invariants (bounds, widths, which separator lands on which segment)
    have exactly one definition.
    """

    return DateTimeFormatProfile(
        segments=_date_segments(
            order,
            display_separator=display_separator,
            segmented_separator=segmented_separator,
        )
        + _time_segments(
            hour_cycle=hour_cycle,
            time_separator=time_separator,
            date_time_separator=date_time_separator,
        ),
        hour_cycle=hour_cycle,
    )


DATE_TIME_FORMAT_PROFILES = MappingProxyType(
    {
        "iso_8601": build_format_profile(
            ("year", "month", "day"),
            hour_cycle="h23",
            display_separator="-",
            segmented_separator="-",
        ),
        "dmy_24h": build_format_profile(
            ("day", "month", "year"),
            hour_cycle="h23",
            display_separator="/",
            segmented_separator="-",
        ),
        "mdy_12h": build_format_profile(
            ("month", "day", "year"),
            hour_cycle="h12",
            display_separator="/",
            segmented_separator="-",
        ),
    }
)

DEFAULT_DATE_TIME_FORMAT_PROFILE = DATE_TIME_FORMAT_PROFILES["iso_8601"]


def date_time_format_profile(profile_id: str) -> DateTimeFormatProfile:
    """Return the registered immutable profile for ``profile_id``."""

    try:
        return DATE_TIME_FORMAT_PROFILES[profile_id]
    except KeyError as error:
        raise ValueError(f"Unsupported date/time format {profile_id!r}.") from error


@cache
def day_periods_for_locale(locale: str) -> DayPeriodsConfig:
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

    def _segment_text(
        self, segment: DateTimeSegmentSpec, value: date | datetime
    ) -> str:
        if segment.kind == "day_period":
            assert isinstance(value, datetime)
            day_periods = day_periods_for_locale(self.locale)
            return day_periods["am" if value.hour < 12 else "pm"]
        if segment.name == "hour":
            assert isinstance(value, datetime)
            hour = value.hour
            if self.profile.hour_cycle == "h12":
                hour = hour % 12 or 12
            return _format_numeric_date_part(hour, segment.display_min_digits)
        if segment.name == "minute":
            assert isinstance(value, datetime)
            return _format_numeric_date_part(value.minute, segment.display_min_digits)
        return _format_numeric_date_part(
            getattr(value, segment.name), segment.display_min_digits
        )

    def _walk(self, runs: tuple[SegmentRun, ...], value: date | datetime) -> str:
        """Render the segments belonging to ``runs`` in profile order.

        The first emitted segment drops its prefix — that single rule is what
        makes "date", "time", and "datetime" the same walk: the date/time glue
        lives on the hour's prefix and simply disappears when the hour leads.
        """

        pieces: list[str] = []
        for segment in self.profile.segments:
            if segment.run not in runs:
                continue
            prefix = "" if not pieces else segment.display.prefix
            pieces.append(
                f"{prefix}{self._segment_text(segment, value)}{segment.display.suffix}"
            )
        return "".join(pieces)

    def format(self, value: date | datetime, style: DateTimeStyle) -> str:
        """Format ``value`` using a semantic style, never a caller pattern."""

        localized = self._localized(value)
        if style == "date":
            return self._walk(("date",), localized)
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
            return self._walk(("time",), localized)
        if style == "datetime":
            return self._walk(("date", "time"), localized)
        raise ValueError(f"unknown date/time style: {style!r}")

    def to_client_config(self) -> DateTimePresentationConfig:
        """Return the versioned JSON-compatible browser contract."""

        return {
            "version": 2,
            "locale": self.locale,
            "time_zone": self.timezone.key,
            "profile": {
                "segments": [
                    {
                        "name": segment.name,
                        "kind": segment.kind,
                        "run": segment.run,
                        "placeholder": segment.placeholder,
                        "input_length": segment.input_length,
                        "display_min_digits": segment.display_min_digits,
                        "min_value": segment.min_value,
                        "max_value": segment.max_value,
                        "display": {
                            "prefix": segment.display.prefix,
                            "suffix": segment.display.suffix,
                        },
                        "segmented": {
                            "prefix": segment.segmented.prefix,
                            "suffix": segment.segmented.suffix,
                        },
                    }
                    for segment in self.profile.segments
                ],
                "hour_cycle": self.profile.hour_cycle,
            },
            "day_periods": day_periods_for_locale(self.locale),
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
    profile_id = resolve_str_for_user(getattr(request, "user", None), "DATETIME_FORMAT")
    presentation = DateTimePresentation(
        profile=date_time_format_profile(profile_id),
        locale=locale
        if isinstance(locale, str)
        else get_language() or settings.LANGUAGE_CODE,
        timezone=zone,
    )
    setattr(request, _REQUEST_CACHE_ATTRIBUTE, presentation)
    return presentation
