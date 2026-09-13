"""What the legacy Session rows hold.

#700 imports the classifiers, so the report and the
conversion name one row the same way. Those names are
public for that reason alone.
"""

import uuid
from dataclasses import dataclass, fields
from datetime import timedelta
from enum import StrEnum

from games.models import Session


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
