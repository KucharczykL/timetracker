"""What the legacy Session rows hold.

#700 imports the classifiers, so the report and the
conversion name one row the same way. Those names are
public for that reason alone.
"""

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
