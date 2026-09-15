"""Both tables' session figures, side by side.

The statistics gate's second half: what the stats page and the navbar
print from sessions and no playtime figure answers. The legacy side
reads `duration_total`, so a manual entry counts its stated time on
both sides, and both sides break every tie on the same key -- the
converted session keeps the legacy row's id.
"""

import uuid
from collections.abc import Callable, Iterator, Sequence
from datetime import date, timedelta
from typing import Final, NamedTuple, Protocol
from zoneinfo import ZoneInfo

from django.db.models import Avg, Count
from django.db.models.functions import TruncDate
from django.utils import timezone

from games.models import Session, SessionQuerySet, UserLibrary
from games.reads import session_figures as projection_figures
from games.reads.playthrough_completions import YearScope
from games.reads.playtime import legacy, projection
from games.reads.playtime_parity import FigureKind, FigureScope, one_snapshot


class LongestFigure(NamedTuple):
    duration: timedelta
    game_id: uuid.UUID
    session_id: uuid.UUID


class CountFigure(NamedTuple):
    sessions: int
    game_id: uuid.UUID


class AverageFigure(NamedTuple):
    average: timedelta
    game_id: uuid.UUID


class DayFigure(NamedTuple):
    day: date
    game_id: uuid.UUID


type FigureValue = (
    int | bool | LongestFigure | CountFigure | AverageFigure | DayFigure | None
)


class SessionFigureSource(Protocol):
    """One member per figure a surface prints from sessions."""

    def session_count(self, library: UserLibrary, year: YearScope) -> int: ...
    def distinct_days(self, library: UserLibrary, year: YearScope) -> int: ...
    def longest_session(
        self, library: UserLibrary, year: YearScope
    ) -> LongestFigure | None: ...
    def most_sessions_game(
        self, library: UserLibrary, year: YearScope
    ) -> CountFigure | None: ...
    def highest_average_game(
        self, library: UserLibrary, year: YearScope
    ) -> AverageFigure | None: ...
    def first_play(self, library: UserLibrary, year: YearScope) -> DayFigure | None: ...
    def last_play(self, library: UserLibrary, year: YearScope) -> DayFigure | None: ...
    def has_sessions(self, library: UserLibrary) -> bool: ...


class LegacySessionFigures:
    """Legacy rows; days read in the active zone."""

    @staticmethod
    def _scoped(library: UserLibrary, year: YearScope) -> SessionQuerySet:
        sessions = Session.objects.for_library(library)
        if year is None:
            return sessions
        return sessions.filter(timestamp_start__year=year)

    def session_count(self, library: UserLibrary, year: YearScope) -> int:
        return self._scoped(library, year).count()

    def distinct_days(self, library: UserLibrary, year: YearScope) -> int:
        return (
            self._scoped(library, year)
            .annotate(day=TruncDate("timestamp_start"))
            .values("day")
            .distinct()
            .aggregate(days=Count("day"))["days"]
        )

    def longest_session(
        self, library: UserLibrary, year: YearScope
    ) -> LongestFigure | None:
        row = (
            self._scoped(library, year)
            .order_by("-duration_total", "game__sort_name", "game_id", "id")
            .values_list("duration_total", "game_id", "id")
            .first()
        )
        return None if row is None else LongestFigure(*row)

    def most_sessions_game(
        self, library: UserLibrary, year: YearScope
    ) -> CountFigure | None:
        row = (
            self._scoped(library, year)
            .values("game_id", "game__sort_name")
            .annotate(sessions=Count("id"))
            .order_by("-sessions", "game__sort_name", "game_id")
            .values_list("sessions", "game_id")
            .first()
        )
        return None if row is None else CountFigure(*row)

    def highest_average_game(
        self, library: UserLibrary, year: YearScope
    ) -> AverageFigure | None:
        row = (
            self._scoped(library, year)
            .values("game_id", "game__sort_name")
            .annotate(average=Avg("duration_total"))
            .order_by("-average", "game__sort_name", "game_id")
            .values_list("average", "game_id")
            .first()
        )
        return None if row is None else AverageFigure(*row)

    def _play(
        self, library: UserLibrary, year: YearScope, *order: str
    ) -> DayFigure | None:
        row = (
            self._scoped(library, year)
            .annotate(day=TruncDate("timestamp_start"))
            .order_by(*order)
            .values_list("day", "game_id")
            .first()
        )
        return None if row is None else DayFigure(*row)

    def first_play(self, library: UserLibrary, year: YearScope) -> DayFigure | None:
        return self._play(library, year, "day", "id")

    def last_play(self, library: UserLibrary, year: YearScope) -> DayFigure | None:
        return self._play(library, year, "-day", "-id")

    def has_sessions(self, library: UserLibrary) -> bool:
        return Session.objects.for_library(library).exists()


class ProjectionSessionFigures:
    """The page's own readers, answered as keys."""

    def session_count(self, library: UserLibrary, year: YearScope) -> int:
        return projection_figures.session_count(library, year)

    def distinct_days(self, library: UserLibrary, year: YearScope) -> int:
        return projection_figures.distinct_days(library, year)

    def longest_session(
        self, library: UserLibrary, year: YearScope
    ) -> LongestFigure | None:
        longest = projection_figures.longest_session(library, year)
        if longest is None:
            return None
        return LongestFigure(
            longest.session.effective_duration, longest.game.pk, longest.session.pk
        )

    def most_sessions_game(
        self, library: UserLibrary, year: YearScope
    ) -> CountFigure | None:
        most = projection_figures.most_sessions_game(library, year)
        return None if most is None else CountFigure(most.sessions, most.game.pk)

    def highest_average_game(
        self, library: UserLibrary, year: YearScope
    ) -> AverageFigure | None:
        highest = projection_figures.highest_average_game(library, year)
        return (
            None if highest is None else AverageFigure(highest.average, highest.game.pk)
        )

    def first_play(self, library: UserLibrary, year: YearScope) -> DayFigure | None:
        first = projection_figures.first_play(library, year)
        return None if first is None else DayFigure(first.day, first.game.pk)

    def last_play(self, library: UserLibrary, year: YearScope) -> DayFigure | None:
        last = projection_figures.last_play(library, year)
        return None if last is None else DayFigure(last.day, last.game.pk)

    def has_sessions(self, library: UserLibrary) -> bool:
        return projection_figures.has_sessions(library)


class SessionFigure(NamedTuple):
    scope: FigureScope
    legacy: FigureValue
    projection: FigureValue


class SessionSourcePair(NamedTuple):
    legacy: SessionFigureSource
    projection: SessionFigureSource


SESSION_SOURCES: Final = SessionSourcePair(
    LegacySessionFigures(), ProjectionSessionFigures()
)

#: Members read; the coverage test holds this whole.
COMPARED_SESSION_MEMBERS: Final = frozenset(
    {
        "session_count",
        "distinct_days",
        "longest_session",
        "most_sessions_game",
        "highest_average_game",
        "first_play",
        "last_play",
        "has_sessions",
    }
)
#: Members no figure reads, and why.
UNCOMPARED_SESSION_MEMBERS: Final[dict[str, str]] = {}

#: One figure, read from either source.
type SessionRead = Callable[[SessionFigureSource], FigureValue]

#: Each scoped member: its kind and the figure it answers.
SCOPED_MEMBERS: Final[tuple[tuple[FigureKind, str], ...]] = (
    (FigureKind.SESSION_COUNT, "session_count"),
    (FigureKind.DISTINCT_DAYS, "distinct_days"),
    (FigureKind.LONGEST_SESSION, "longest_session"),
    (FigureKind.MOST_SESSIONS, "most_sessions_game"),
    (FigureKind.HIGHEST_AVERAGE, "highest_average_game"),
    (FigureKind.FIRST_PLAY, "first_play"),
    (FigureKind.LAST_PLAY, "last_play"),
)


def _figure(
    sources: SessionSourcePair, scope: FigureScope, read: SessionRead
) -> SessionFigure:
    return SessionFigure(scope, read(sources.legacy), read(sources.projection))


def _scoped_read(member: str, library: UserLibrary, year: YearScope) -> SessionRead:
    return lambda source: getattr(source, member)(library, year)


def _scoped_figures(
    sources: SessionSourcePair, library: UserLibrary, year: YearScope
) -> Iterator[SessionFigure]:
    key = () if year is None else (str(year),)
    label = "all-time" if year is None else f"year {year}"
    for kind, member in SCOPED_MEMBERS:
        yield _figure(
            sources,
            FigureScope(kind, key, f"{kind} {label}"),
            _scoped_read(member, library, year),
        )


def session_figures(
    library: UserLibrary,
    zone: ZoneInfo,
    *,
    sources: SessionSourcePair = SESSION_SOURCES,
) -> list[SessionFigure]:
    """Each figure once, per played year and all-time."""
    with one_snapshot(), timezone.override(zone):
        years = sorted(
            set(legacy.played_years(library)) | set(projection.played_years(library))
        )
        return [
            *_scoped_figures(sources, library, None),
            *(
                figure
                for year in years
                for figure in _scoped_figures(sources, library, year)
            ),
            _figure(
                sources,
                FigureScope(FigureKind.HAS_SESSIONS, (), "has sessions"),
                lambda source: source.has_sessions(library),
            ),
        ]


def differing_session_figures(
    figures: Sequence[SessionFigure],
) -> list[SessionFigure]:
    return [figure for figure in figures if figure.legacy != figure.projection]
