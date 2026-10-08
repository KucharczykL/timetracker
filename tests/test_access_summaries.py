"""What a game's live copies say, for the Games list's Access badge."""

import pytest
from entries import end_entry_access, record_entry, remove_entry
from graphs import default_graph

from games.end_ways import EndWay
from games.models import Game
from games.reads.entries import access_summaries
from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def graph(owned_library):
    return default_graph(Game(name="Tunic", library=owned_library), owned_library)


def _summary(library, game):
    return access_summaries(library, [game.pk]).get(game.pk)


def test_a_game_without_a_live_copy_has_no_summary(owned_library, graph):
    remove_entry(record_entry(owned_library, graph.release))

    assert _summary(owned_library, graph.game) is None


def test_an_owned_copy_is_owned_now(owned_library, graph):
    record_entry(owned_library, graph.release, access="owned", format="physical")

    summary = _summary(owned_library, graph.game)

    assert summary.owned_now
    assert summary.formats == {"physical"}
    assert len(summary.held) == 1
    assert summary.former is None


def test_a_borrowed_copy_is_held_but_not_owned(owned_library, graph):
    record_entry(owned_library, graph.release, access="borrowed")

    summary = _summary(owned_library, graph.game)

    assert not summary.owned_now
    assert len(summary.held) == 1


def test_an_ended_copy_is_not_held(owned_library, graph):
    kept = record_entry(owned_library, graph.release, format="physical")
    end_entry_access(record_entry(owned_library, graph.release), way=EndWay.SOLD)

    summary = _summary(owned_library, graph.game)

    assert summary.held == (kept,)
    assert summary.formats == {"physical"}
    assert len(summary.ended) == 1
    assert summary.former is None


def test_two_formats_held_read_both(owned_library, graph):
    record_entry(owned_library, graph.release, format="physical")
    record_entry(owned_library, graph.release, access="subscription")

    summary = _summary(owned_library, graph.game)

    assert summary.formats == {"physical", "digital"}
    assert summary.owned_now


def test_with_nothing_held_the_latest_end_is_former(owned_library, graph):
    end_entry_access(
        record_entry(owned_library, graph.release),
        ended=TemporalValue.parse("2020"),
    )
    latest = end_entry_access(
        record_entry(owned_library, graph.release, format="physical"),
        way=EndWay.SOLD,
        ended=TemporalValue.parse("2023-05"),
    )
    end_entry_access(record_entry(owned_library, graph.release))

    summary = _summary(owned_library, graph.game)

    assert summary.held == ()
    assert not summary.owned_now
    assert summary.former.entry == latest


def test_among_ends_on_one_day_the_later_statement_is_former(owned_library, graph):
    day = TemporalValue.parse("2023-05-01")
    end_entry_access(record_entry(owned_library, graph.release), ended=day)
    later = end_entry_access(record_entry(owned_library, graph.release), ended=day)

    assert _summary(owned_library, graph.game).former.entry == later


def test_another_librarys_copy_never_counts(owned_library, graph, django_user_model):
    stranger = django_user_model.objects.create_user("stranger").library
    theirs = default_graph(Game(name="Hades", library=stranger), stranger)
    record_entry(stranger, theirs.release)
    record_entry(owned_library, graph.release)

    summaries = access_summaries(owned_library, [graph.game.pk, theirs.game.pk])

    assert set(summaries) == {graph.game.pk}


def test_one_query_reads_every_game(owned_library, django_assert_num_queries):
    games = [
        default_graph(Game(name=name, library=owned_library), owned_library)
        for name in ("Tunic", "Hades", "Celeste")
    ]
    for graph in games:
        record_entry(owned_library, graph.release)

    with django_assert_num_queries(1):
        summaries = access_summaries(owned_library, [graph.game.pk for graph in games])

    assert len(summaries) == 3
