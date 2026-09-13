"""What the legacy Session rows hold.

#700 imports the classifiers, so the report and the
conversion name one row the same way. Those names are
public for that reason alone.
"""

import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, fields
from datetime import date, timedelta
from enum import StrEnum
from itertools import batched
from typing import NamedTuple
from zoneinfo import ZoneInfo

from django.conf import settings

from common.keyset import keyset_pages
from games.models import (
    Game,
    PlayerGame,
    Playthrough,
    PlaythroughKind,
    Session,
    UserLibrary,
)
from games.reads.playthrough_activity import activity_clock


class TimingVerdict(StrEnum):
    """What one legacy row states about its time.

    The first three are the modes #689 admits. The last
    three are what no mode holds, named so a count can
    show they are empty.
    """

    #: An end earlier than the start.
    NEGATIVE_ELAPSED = "negative_elapsed"
    #: A manual duration below zero.
    NEGATIVE_MANUAL = "negative_manual"
    TIMED = "timed"
    DURATION_ONLY = "duration_only"
    CORRECTED = "corrected"
    #: A start alone, which is a session still open.
    RUNNING = "running"


def classify_timing(session: Session) -> TimingVerdict:
    """One of six verdicts per row.

    The order is the rule: a row that is both reversed and
    negative is named by the interval, because that is the
    part a duration cannot repair.
    """
    #: The column is nullable, so a null reads as no
    #: manual duration rather than raising. Testing it for
    #: presence instead would call every live row timed.
    manual = session.duration_manual or timedelta(0)
    if session.timestamp_end is not None and session.timestamp_end < (
        session.timestamp_start
    ):
        return TimingVerdict.NEGATIVE_ELAPSED
    if manual < timedelta(0):
        return TimingVerdict.NEGATIVE_MANUAL
    if session.timestamp_end is None:
        return (
            TimingVerdict.DURATION_ONLY
            if manual > timedelta(0)
            else TimingVerdict.RUNNING
        )
    return TimingVerdict.CORRECTED if manual > timedelta(0) else TimingVerdict.TIMED


@dataclass(frozen=True, slots=True)
class PreflightCounts:
    """What one library holds, summable into totals."""

    #: Every session on a game this library owns.
    sessions_in_scope: int = 0
    #: The rows a verdict was taken on.
    classified: int = 0
    #: Carried beside the verdict, never instead of it.
    removed: int = 0
    #: Reads zero, and is printed so a reader sees that.
    unaccounted: int = 0

    negative_elapsed: int = 0
    negative_manual: int = 0
    timed: int = 0
    duration_only: int = 0
    corrected: int = 0
    running: int = 0

    #: A null the schema allows and the data does not hold.
    manual_duration_null: int = 0
    #: Rows naming the zone they were committed in.
    committed_zone_stated: int = 0

    on_removed_game: int = 0
    without_player_game: int = 0
    on_removed_player_game: int = 0

    #: One run, so containment was never consulted.
    sole_run: int = 0
    contained_primary: int = 0
    bucket_primary: int = 0
    many_claimers_primary: int = 0
    contained_secondary: int = 0
    bucket_secondary: int = 0
    many_claimers_secondary: int = 0

    games_owned: int = 0
    games_without_sessions: int = 0
    games_needing_bucket_primary: int = 0
    games_needing_bucket_secondary: int = 0

    #: The same instant read in the two zones.
    day_differs: int = 0
    month_differs: int = 0
    year_differs: int = 0

    def __add__(self, other: PreflightCounts) -> PreflightCounts:
        return PreflightCounts(
            **{
                field.name: getattr(self, field.name) + getattr(other, field.name)
                for field in fields(self)
            }
        )

    def as_dict(self) -> dict[str, int]:
        return {field.name: getattr(self, field.name) for field in fields(self)}


#: The value an accumulation starts from.
NO_COUNTS = PreflightCounts()


@dataclass(frozen=True, slots=True)
class Samples:
    """The first few identifiers, never random.

    Two runs over unchanged data print the same bytes.
    """

    negative_elapsed: tuple[uuid.UUID, ...] = ()
    negative_manual: tuple[uuid.UUID, ...] = ()
    running: tuple[uuid.UUID, ...] = ()
    bucket_primary: tuple[uuid.UUID, ...] = ()
    many_claimers_primary: tuple[uuid.UUID, ...] = ()
    games_needing_bucket_primary: tuple[uuid.UUID, ...] = ()

    def as_dict(self) -> dict[str, list[str]]:
        return {
            field.name: [str(value) for value in getattr(self, field.name)]
            for field in fields(self)
        }


class RunInterval(NamedTuple):
    """One run, as the two days that bound it.

    Read from the generated bound columns rather than the
    stated values: a run started in a month bounds the
    whole month, and the day a session fell on is compared
    against the bound, not against the spelling.
    """

    run_id: uuid.UUID
    started_lower: date | None
    completed_upper: date | None


def claims(interval: RunInterval, day: date) -> bool:
    """Whether the run's interval holds that day.

    Either bound alone is an open interval on the other
    side: a run started and never finished claims every
    day since. A run stating neither claims nothing, so it
    never draws a session in on emptiness alone.
    """
    if interval.started_lower is None and interval.completed_upper is None:
        return False
    if interval.started_lower is not None and day < interval.started_lower:
        return False
    return interval.completed_upper is None or day <= interval.completed_upper


class AssignmentOutcome(StrEnum):
    """How a session found its run, or failed to."""

    #: The game holds one run, so the day was never read.
    SOLE_RUN = "sole_run"
    CONTAINED = "contained"
    #: No run, or no single one: a person decides.
    BUCKET = "bucket"


class Assignment(NamedTuple):
    """The outcome, the run when one was found, the claimers."""

    outcome: AssignmentOutcome
    run_id: uuid.UUID | None
    #: Zero for a sole run, which consulted no interval.
    claimers: int


def assign_run(runs: Sequence[RunInterval], day: date) -> Assignment:
    """The run a legacy session lands on.

    One run takes it whatever its day, because a library
    tracking a game holds a run for it and the session
    happened at that game. Past one, only containment can
    choose, and two claimers choose nothing.
    """
    if len(runs) == 1:
        return Assignment(AssignmentOutcome.SOLE_RUN, runs[0].run_id, 0)
    claimers = [run for run in runs if claims(run, day)]
    if len(claimers) == 1:
        return Assignment(AssignmentOutcome.CONTAINED, claimers[0].run_id, 1)
    return Assignment(AssignmentOutcome.BUCKET, None, len(claimers))


class ZonePair(NamedTuple):
    """The two zones one instant is read in.

    The primary is the process zone, the secondary the
    library's display zone, which is what every day-grained
    read groups in today.
    """

    primary: ZoneInfo
    secondary: ZoneInfo

    def names(self) -> tuple[str, str]:
        return (str(self.primary), str(self.secondary))


def report_zones(library: UserLibrary, override: ZoneInfo | None = None) -> ZonePair:
    """The zones this library's days are read in."""
    secondary = override if override is not None else activity_clock(library).zone
    return ZonePair(primary=ZoneInfo(settings.TIME_ZONE), secondary=secondary)


@dataclass(frozen=True, slots=True)
class LibraryPreflight:
    """One library's whole report."""

    library_id: uuid.UUID
    username: str
    zones: tuple[str, str]
    counts: PreflightCounts
    samples: Samples

    def as_dict(self) -> dict[str, object]:
        return {
            "library_id": str(self.library_id),
            "username": self.username,
            "zones": list(self.zones),
            "counts": self.counts.as_dict(),
            "samples": self.samples.as_dict(),
        }


#: Games per query.
WALK_PAGE_SIZE = 200

#: Identifiers per sampled list.
DEFAULT_SAMPLE_SIZE = 20


def preflight_library(
    library: UserLibrary,
    *,
    sample_size: int = DEFAULT_SAMPLE_SIZE,
    day_zone: ZoneInfo | None = None,
) -> LibraryPreflight:
    """One library's legacy sessions, read and counted."""
    zones = report_zones(library, day_zone)
    counts = NO_COUNTS
    negative_elapsed: list[uuid.UUID] = []
    negative_manual: list[uuid.UUID] = []
    running: list[uuid.UUID] = []
    bucketed: list[uuid.UUID] = []
    many_claimers: list[uuid.UUID] = []
    bucket_games: list[uuid.UUID] = []

    owned = Game.objects.filter(library=library)
    for batch in batched(
        keyset_pages(owned, key=("id",), page_size=WALK_PAGE_SIZE), WALK_PAGE_SIZE
    ):
        game_ids = [game.pk for game in batch]
        sessions_by_game: dict[uuid.UUID, list[Session]] = defaultdict(list)
        for session in Session.objects.filter(game_id__in=game_ids).order_by("id"):
            sessions_by_game[session.game_id].append(session)

        #: A removed tracking row holds no live run and is
        #: otherwise indistinguishable from none at all.
        tracking_by_game: dict[uuid.UUID, PlayerGame] = {}
        removed_tracking: set[uuid.UUID] = set()
        for tracking_row in PlayerGame.objects.filter(
            library=library, game_id__in=game_ids
        ).only("id", "game_id", "removed_at"):
            if tracking_row.removed_at is None:
                tracking_by_game[tracking_row.game_id] = tracking_row
            else:
                removed_tracking.add(tracking_row.game_id)

        runs_by_tracking: dict[uuid.UUID, list[RunInterval]] = defaultdict(list)
        for run_id, tracked_id, started, completed in (
            Playthrough.objects.filter(
                library=library,
                player_game_id__in=[row.pk for row in tracking_by_game.values()],
                removed_at__isnull=True,
                kind=PlaythroughKind.ORDINARY,
            )
            .order_by("created_at", "id")
            .values_list("id", "player_game_id", "started_lower", "completed_upper")
        ):
            runs_by_tracking[tracked_id].append(RunInterval(run_id, started, completed))

        for game in batch:
            counts = counts + PreflightCounts(games_owned=1)
            sessions = sessions_by_game.get(game.pk, [])
            counts = counts + PreflightCounts(
                sessions_in_scope=len(sessions),
                games_without_sessions=int(not sessions),
            )
            if not sessions:
                continue

            tracked = tracking_by_game.get(game.pk)
            if game.removed_at is not None:
                counts = counts + PreflightCounts(on_removed_game=len(sessions))
                continue
            if tracked is None:
                field = (
                    "on_removed_player_game"
                    if game.pk in removed_tracking
                    else "without_player_game"
                )
                counts = counts + PreflightCounts(**{field: len(sessions)})
                continue

            runs = runs_by_tracking.get(tracked.pk, [])
            buckets_primary = 0
            buckets_secondary = 0
            for session in sessions:
                counts = counts + PreflightCounts(
                    classified=1,
                    removed=int(session.removed_at is not None),
                    manual_duration_null=int(session.duration_manual is None),
                    committed_zone_stated=int(bool(session.timestamp_start_timezone)),
                )
                verdict = classify_timing(session)
                counts = counts + PreflightCounts(**{verdict.value: 1})
                match verdict:
                    case TimingVerdict.NEGATIVE_ELAPSED:
                        negative_elapsed.append(session.pk)
                    case TimingVerdict.NEGATIVE_MANUAL:
                        negative_manual.append(session.pk)
                    case TimingVerdict.RUNNING:
                        running.append(session.pk)
                    case _:
                        pass

                primary_day = session.timestamp_start.astimezone(zones.primary).date()
                secondary_day = session.timestamp_start.astimezone(
                    zones.secondary
                ).date()
                counts = counts + PreflightCounts(
                    day_differs=int(primary_day != secondary_day),
                    month_differs=int(
                        (primary_day.year, primary_day.month)
                        != (secondary_day.year, secondary_day.month)
                    ),
                    year_differs=int(primary_day.year != secondary_day.year),
                )

                primary = assign_run(runs, primary_day)
                secondary = assign_run(runs, secondary_day)
                if primary.outcome is AssignmentOutcome.SOLE_RUN:
                    #: One run answers in both zones, so the
                    #: count is not doubled by reading twice.
                    counts = counts + PreflightCounts(sole_run=1)
                    continue
                counts = counts + PreflightCounts(
                    **{
                        f"{primary.outcome.value}_primary": 1,
                        f"{secondary.outcome.value}_secondary": 1,
                    }
                )
                counts = counts + PreflightCounts(
                    many_claimers_primary=int(primary.claimers > 1),
                    many_claimers_secondary=int(secondary.claimers > 1),
                )
                if primary.outcome is AssignmentOutcome.BUCKET:
                    buckets_primary += 1
                    bucketed.append(session.pk)
                    if primary.claimers > 1:
                        many_claimers.append(session.pk)
                if secondary.outcome is AssignmentOutcome.BUCKET:
                    buckets_secondary += 1

            counts = counts + PreflightCounts(
                games_needing_bucket_primary=int(bool(buckets_primary)),
                games_needing_bucket_secondary=int(bool(buckets_secondary)),
            )
            if buckets_primary:
                bucket_games.append(game.pk)

    counts = counts + PreflightCounts(
        unaccounted=counts.sessions_in_scope
        - counts.classified
        - counts.on_removed_game
        - counts.without_player_game
        - counts.on_removed_player_game
    )

    def capped(values: list[uuid.UUID]) -> tuple[uuid.UUID, ...]:
        return tuple(values[:sample_size])

    return LibraryPreflight(
        library_id=library.pk,
        username=library.user.username,
        zones=zones.names(),
        counts=counts,
        samples=Samples(
            negative_elapsed=capped(negative_elapsed),
            negative_manual=capped(negative_manual),
            running=capped(running),
            bucket_primary=capped(bucketed),
            many_claimers_primary=capped(many_claimers),
            games_needing_bucket_primary=capped(bucket_games),
        ),
    )


@dataclass(frozen=True, slots=True)
class SharedCatalogCounts:
    """The catalog rows no library owns.

    A session at a shared game belongs to no library's
    census, so it is reported here or nowhere.
    """

    shared_games: int = 0
    shared_game_sessions: int = 0

    def as_dict(self) -> dict[str, int]:
        return {field.name: getattr(self, field.name) for field in fields(self)}


def shared_catalog_counts() -> SharedCatalogCounts:
    """Count the shared games and their sessions."""
    shared = Game.objects.filter(library__isnull=True)
    return SharedCatalogCounts(
        shared_games=shared.count(),
        shared_game_sessions=Session.objects.filter(game__in=shared).count(),
    )
