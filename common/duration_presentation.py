"""Request-scoped formatting for every human-visible elapsed duration.

A duration is not a datetime: it has no timezone, no calendar, and no 12/24-hour
clock, so it carries its own preference rather than riding on ``DATETIME_FORMAT``.
Stored values, API values, filtering, and sorting never come through here — this
module is display only.

Two rules hold across every profile:

* **Round the total once, then decompose.** Rounding a component after the split
  renders 1 h 59 m 45 s as "2 h 60 m".
* **Round, never truncate**, at each profile's own resolution. Truncation renders
  59 minutes as "0 hours", which is a lie the popover should not have to repair.
"""

import math
from dataclasses import dataclass
from datetime import timedelta
from functools import cache
from types import MappingProxyType
from typing import Protocol

from django.http import HttpRequest
from django.utils.formats import number_format
from django.utils.translation import override

from timetracker.settings_resolver import resolve_str_for_user

type DurationProfileId = str  # e.g. "decimal_hours"
type ProfileLabel = str  # e.g. "Hours and minutes"

MINUTE_SECONDS = 60
HOUR_SECONDS = 60 * MINUTE_SECONDS
DAY_SECONDS = 24 * HOUR_SECONDS
WEEK_SECONDS = 7 * DAY_SECONDS
# A year is not a whole number of weeks. 52 weeks keeps the ladder exact, and
# nothing here is a calendar date, so the four-day drift is harmless.
YEAR_SECONDS = 52 * WEEK_SECONDS


class NumberFormatter(Protocol):
    """Renders a number for display. Locale-aware in a request, plain in tests
    of the rules themselves."""

    def __call__(self, value: float, decimals: int) -> str: ...


def plain_number(value: float, decimals: int) -> str:
    return f"{value:.{decimals}f}"


def _round_half_away(value: float) -> int:
    """Half away from zero, unlike ``round()``'s banker's rounding. Durations
    are clamped non-negative before they reach here."""
    return math.floor(value + 0.5)


def _total_seconds(duration: timedelta | float | None) -> int:
    """Whole seconds, never negative: ``timestamp_end`` before
    ``timestamp_start`` is bad data, not a negative duration."""
    if duration is None:
        return 0
    seconds = (
        duration.total_seconds() if isinstance(duration, timedelta) else float(duration)
    )
    return max(int(seconds), 0)


@dataclass(frozen=True)
class LadderUnit:
    """One rung of the adaptive ladder."""

    key: str  # e.g. "day"
    seconds: int
    symbol: str  # e.g. "d"
    pad_below: bool  # zero-pad the next unit down to two digits


# Largest first; the search below relies on the order.
LADDER: tuple[LadderUnit, ...] = (
    LadderUnit("year", YEAR_SECONDS, "y", pad_below=False),
    LadderUnit("week", WEEK_SECONDS, "w", pad_below=False),
    LadderUnit("day", DAY_SECONDS, "d", pad_below=True),
    LadderUnit("hour", HOUR_SECONDS, "h", pad_below=True),
    LadderUnit("minute", MINUTE_SECONDS, "m", pad_below=False),
)


@dataclass(frozen=True)
class DurationProfile:
    """One display rendering. ``label`` names it in the settings control and in
    the popover listing the other profiles."""

    id: DurationProfileId
    label: ProfileLabel

    def render(self, seconds: int, numbers: NumberFormatter) -> str:
        raise NotImplementedError


@dataclass(frozen=True)
class DecimalHoursProfile(DurationProfile):
    def render(self, seconds: int, numbers: NumberFormatter) -> str:
        tenths = _round_half_away(seconds / HOUR_SECONDS * 10)
        return f"{numbers(tenths / 10, 1)} h"


@dataclass(frozen=True)
class HoursMinutesProfile(DurationProfile):
    def render(self, seconds: int, numbers: NumberFormatter) -> str:
        total_minutes = _round_half_away(seconds / MINUTE_SECONDS)
        hours, minutes = divmod(total_minutes, 60)
        if hours:
            return f"{numbers(hours, 0)} h {minutes:02d} m"
        # Zero keeps the column's unit stable; anything else under an hour drops
        # the pointless leading "0 h".
        return f"{minutes} m" if minutes else "0 h"


@dataclass(frozen=True)
class WholeHoursProfile(DurationProfile):
    def render(self, seconds: int, numbers: NumberFormatter) -> str:
        hours = _round_half_away(seconds / HOUR_SECONDS)
        return f"{numbers(hours, 0)} hour{'' if hours == 1 else 's'}"


@dataclass(frozen=True)
class AdaptiveProfile(DurationProfile):
    """Minutes through years, showing the largest unit the value reaches and
    the one below it."""

    def render(self, seconds: int, numbers: NumberFormatter) -> str:
        unit, below = self._units_for(seconds)
        if below is None:
            return self._minutes_only(seconds, numbers)
        rounded = _round_half_away(seconds / below.seconds) * below.seconds
        # Rounding can carry into a higher unit — 6 d 23 h 40 m becomes 1 w 0 d,
        # never 6 d 24 h.
        unit, below = self._units_for(rounded)
        if below is None:
            return self._minutes_only(rounded, numbers)
        top, remainder = divmod(rounded, unit.seconds)
        lower = remainder // below.seconds
        lower_text = f"{lower:02d}" if unit.pad_below else str(lower)
        return f"{numbers(top, 0)} {unit.symbol} {lower_text} {below.symbol}"

    def _minutes_only(self, seconds: int, numbers: NumberFormatter) -> str:
        """Below an hour the ladder agrees with hours_minutes, zero included:
        an empty duration reads "0 h" so a column's unit stays put."""
        minutes = _round_half_away(seconds / MINUTE_SECONDS)
        return f"{numbers(minutes, 0)} m" if minutes else "0 h"

    def _units_for(self, seconds: int) -> tuple[LadderUnit, LadderUnit | None]:
        """The largest unit ``seconds`` reaches and the rung below it. Below a
        minute the pair collapses to minutes alone."""
        for index, unit in enumerate(LADDER):
            if seconds >= unit.seconds:
                below = LADDER[index + 1] if index + 1 < len(LADDER) else None
                return unit, below
        return LADDER[-1], None


DURATION_FORMAT_PROFILES = MappingProxyType(
    {
        "decimal_hours": DecimalHoursProfile("decimal_hours", "Decimal hours"),
        "hours_minutes": HoursMinutesProfile("hours_minutes", "Hours and minutes"),
        "whole_hours": WholeHoursProfile("whole_hours", "Whole hours"),
        "adaptive": AdaptiveProfile("adaptive", "Adaptive units"),
    }
)

DEFAULT_DURATION_FORMAT_PROFILE = DURATION_FORMAT_PROFILES["decimal_hours"]


def duration_format_profile(profile_id: DurationProfileId) -> DurationProfile:
    """Return the registered immutable profile for ``profile_id``."""
    try:
        return DURATION_FORMAT_PROFILES[profile_id]
    except KeyError as error:
        raise ValueError(f"Unsupported duration format {profile_id!r}.") from error


def format_decimal_hours(duration: timedelta | float | None) -> str:
    """Decimal hours, preference-independent, for callers with no request —
    ``Session.__str__`` and other debug or log strings."""
    seconds = _total_seconds(duration)
    return plain_number(_round_half_away(seconds / HOUR_SECONDS * 10) / 10, 1)


@dataclass(frozen=True)
class DurationPresentation:
    """The immutable duration display contract active for one request."""

    profile: DurationProfile
    locale: str

    def _numbers(self, value: float, decimals: int) -> str:
        """Grouping and the decimal separator come from the formatting locale.

        ``force_grouping`` is explicit because ``USE_THOUSAND_SEPARATOR`` is
        unset project-wide; turning it on globally would retroactively regroup
        every price on the site. ``override`` is scoped to this call for the
        same reason ``day_periods_for_locale`` scopes its own — the formatting
        locale is deliberately never activated request-wide, so it cannot
        change application copy.
        """
        with override(self.locale):
            return number_format(value, decimals, force_grouping=True)

    def format(self, duration: timedelta | float | None) -> str:
        return self.profile.render(_total_seconds(duration), self._numbers)

    def alternates(
        self, duration: timedelta | float | None
    ) -> tuple[tuple[ProfileLabel, str], ...]:
        """The same value under the other profiles, in registry order.

        Deduplicated on the *rendered string*, never on profile identity:
        hours_minutes and adaptive agree below a day but diverge at the carry
        boundary, so "these two profiles are equivalent" is not a rule that
        holds.
        """
        seconds = _total_seconds(duration)
        seen = {self.profile.render(seconds, self._numbers)}
        rows: list[tuple[ProfileLabel, str]] = []
        for profile in DURATION_FORMAT_PROFILES.values():
            if profile.id == self.profile.id:
                continue
            rendered = profile.render(seconds, self._numbers)
            if rendered in seen:
                continue
            seen.add(rendered)
            rows.append((profile.label, rendered))
        return tuple(rows)

    def spoken(
        self, duration: timedelta | float | None, *, manual: bool = False
    ) -> str:
        """The value in full words, independent of the visible profile.

        Screen readers mangle abbreviations — "1.2 h" is read "one point two
        h", and "3 d 11 h" is worse. Hours and minutes only: no reader is
        helped by "375 days". Numbers are ungrouped so no separator is voiced.
        """
        total_minutes = _round_half_away(_total_seconds(duration) / MINUTE_SECONDS)
        hours, minutes = divmod(total_minutes, 60)
        parts = [
            f"{count} {unit}{'' if count == 1 else 's'}"
            for count, unit in ((hours, "hour"), (minutes, "minute"))
            if count
        ]
        spoken = " ".join(parts) if parts else "0 hours"
        return f"{spoken}, manual" if manual else spoken


_REQUEST_CACHE_ATTRIBUTE = "_duration_presentation"


@cache
def _profile_for_id(profile_id: DurationProfileId) -> DurationProfile:
    return duration_format_profile(profile_id)


def duration_presentation_for_request(request: HttpRequest) -> DurationPresentation:
    """Resolve and cache the presentation directly on ``request``."""
    cached = getattr(request, _REQUEST_CACHE_ATTRIBUTE, None)
    if isinstance(cached, DurationPresentation):
        return cached

    profile_id = resolve_str_for_user(getattr(request, "user", None), "DURATION_FORMAT")
    locale = getattr(request, "_date_format_locale", None)
    presentation = DurationPresentation(
        profile=_profile_for_id(profile_id),
        locale=locale if isinstance(locale, str) else "en-us",
    )
    setattr(request, _REQUEST_CACHE_ATTRIBUTE, presentation)
    return presentation
