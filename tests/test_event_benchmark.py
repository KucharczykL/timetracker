"""The benchmark harness: percentiles, counting, budgets, scenarios."""

import pytest

from games.events.benchmark import Timings, nearest_rank, summarize


def test_nearest_rank_returns_an_observation_for_one_sample():
    assert nearest_rank([0.5], 95) == 0.5


def test_nearest_rank_never_interpolates_between_two_observations():
    #: statistics.quantiles would answer 0.15 here.
    assert nearest_rank([0.1, 0.2], 50) == 0.1


def test_nearest_rank_can_land_on_the_last_observation():
    samples = [float(value) for value in range(1, 11)]
    assert nearest_rank(samples, 95) == 10.0


def test_nearest_rank_sorts_before_ranking():
    assert nearest_rank([0.3, 0.1, 0.2], 50) == 0.2


def test_nearest_rank_refuses_an_empty_sample_set():
    with pytest.raises(ValueError, match="at least one sample"):
        nearest_rank([], 95)


def test_summarize_reports_the_count_the_tail_and_the_worst():
    samples = [float(value) for value in range(1, 21)]
    assert summarize(samples) == Timings(samples=20, p50=10.0, p95=19.0, maximum=20.0)
