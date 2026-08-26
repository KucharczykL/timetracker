"""What a command costs, what a rebuild costs, and what one event costs.

The charter fixes two numbers -- 100 ms at p95 for an ordinary command, 60
seconds for a 100,000-event rebuild -- and asks that write amplification be
recorded after every new projector family without fixing a limit for it. This
module measures all three against the real workload, and this module is the
only place those numbers are written down.

It names things and decides things; it never does work. Nothing here imports
benchmark_workload or benchmark_run, and that is what keeps the three modules
acyclic.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass

#: A wall-clock interval, from time.monotonic().
type Seconds = float


@dataclass(frozen=True, slots=True)
class Timings:
    """One scenario's latency distribution."""

    samples: int
    p50: Seconds
    p95: Seconds
    maximum: Seconds


def nearest_rank(samples: Sequence[Seconds], percentile: int) -> Seconds:
    """The observation at `percentile`, never a value between two.

    `statistics.quantiles` interpolates, which invents a latency nothing
    measured. A budget is a claim about observations.
    """
    if not samples:
        raise ValueError("A percentile needs at least one sample.")
    ordered = sorted(samples)
    index = math.ceil(percentile / 100 * len(ordered)) - 1
    return ordered[max(index, 0)]


def summarize(samples: Sequence[Seconds]) -> Timings:
    """The three numbers worth reading; the mean hides the tail."""
    return Timings(
        samples=len(samples),
        p50=nearest_rank(samples, 50),
        p95=nearest_rank(samples, 95),
        maximum=max(samples),
    )
