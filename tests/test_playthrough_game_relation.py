"""A filter reaches a run through the game it records, keyed on identity.

A criterion may name that game as an instance or as the integer key a saved
filter still carries, and either has to select the same rows.
"""

import uuid
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from common.criteria import (
    FilterQueryContext,
    Modifier,
    RelationMatch,
    StringCriterion,
    with_filter_aliases,
)
from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DateTimePresentation,
)
from games.filters import GameFilter, PlaythroughFilter
from games.forms import PlaythroughForm
from games.models import (
    Game,
    Playthrough,
    PlaythroughKind,
)
from games.reads.playthrough_runs import library_runs

PRESENTATION = DateTimePresentation(
    DEFAULT_DATE_TIME_FORMAT_PROFILE, "en-us", ZoneInfo("UTC")
)

UNRESTRICTED_FILTER_CONTEXT = FilterQueryContext(
    lambda model: with_filter_aliases(model._default_manager.all())
)

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def game(owned_library):
    return Game.objects.create(library=owned_library, name="Filtered Game")


# --- Filters that reach a run through its game -------------------------------


def born_run(game: Game, note: str = "") -> Playthrough:
    """The noted run born with the game."""
    run = Playthrough.objects.get(player_game__game=game)
    Playthrough.objects.filter(pk=run.pk).update(note=note)
    return Playthrough.objects.get(pk=run.pk)


def second_run(run: Playthrough, note: str) -> Playthrough:
    """Another run at the same tracked game."""
    return Playthrough.objects.create(
        pk=uuid.uuid7(),
        library=run.library,
        player_game=run.player_game,
        kind=PlaythroughKind.ORDINARY,
        created_at=timezone.now(),
        note=note,
    )


def test_playthroughfilter_game_criterion_selects_the_right_rows(game, owned_library):
    other_game = Game.objects.create(library=owned_library, name="Other")
    matching = born_run(game)
    born_run(other_game)

    filter_ = PlaythroughFilter.where(game=[game.id])
    results = library_runs(owned_library).filter(
        filter_.to_q(UNRESTRICTED_FILTER_CONTEXT)
    )
    assert list(results) == [matching]


def test_gamefilter_playthrough_filter_any_selects_games_with_a_matching_run(
    game, owned_library
):
    other_game = Game.objects.create(library=owned_library, name="Other")
    born_run(game, note="Marathon session")
    born_run(other_game, note="Something else")

    filter_ = GameFilter(
        playthrough_filter=PlaythroughFilter(
            note=StringCriterion(value="Marathon", modifier=Modifier.INCLUDES),
        )
    )
    results = Game.objects.filter(library=owned_library).filter(
        filter_.to_q(UNRESTRICTED_FILTER_CONTEXT)
    )
    assert list(results) == [game]


def test_gamefilter_playthrough_filter_none_excludes_games_with_a_matching_run(
    game, owned_library
):
    other_game = Game.objects.create(library=owned_library, name="Other")
    born_run(game, note="Marathon session")
    born_run(other_game, note="Something else")

    filter_ = GameFilter(
        playthrough_filter=PlaythroughFilter(
            note=StringCriterion(value="Marathon", modifier=Modifier.INCLUDES),
            match=RelationMatch.NONE,
        )
    )
    results = Game.objects.filter(library=owned_library).filter(
        filter_.to_q(UNRESTRICTED_FILTER_CONTEXT)
    )
    assert list(results) == [other_game]


def test_gamefilter_playthrough_filter_all_requires_every_run_to_match(
    game, owned_library
):
    other_game = Game.objects.create(library=owned_library, name="Other")
    born_run(game, note="Marathon session")
    second_run(born_run(other_game, note="Marathon session"), note="Something else")

    filter_ = GameFilter(
        playthrough_filter=PlaythroughFilter(
            note=StringCriterion(value="Marathon", modifier=Modifier.INCLUDES),
            match=RelationMatch.ALL,
        )
    )
    results = Game.objects.filter(library=owned_library).filter(
        filter_.to_q(UNRESTRICTED_FILTER_CONTEXT)
    )
    assert list(results) == [game]


def test_playthroughfilter_game_filter_selects_runs_for_matching_games(
    game, owned_library
):
    other_game = Game.objects.create(library=owned_library, name="Other")
    matching = born_run(game)
    born_run(other_game)

    filter_ = PlaythroughFilter(
        game_filter=GameFilter(name=StringCriterion(value=game.name)),
    )
    results = library_runs(owned_library).filter(
        filter_.to_q(UNRESTRICTED_FILTER_CONTEXT)
    )
    assert list(results) == [matching]


# --- Form initial-value shim -------------------------------------------------


def test_playthroughform_states_the_games_identity(game, owned_library):
    """#687 made the form a plain Form.

    The value the game field posts is still the game's own identity,
    which is what #644 promoted and what the widget's options carry.
    """
    form = PlaythroughForm(
        {"game": str(game.pk), "started": "", "ended": "", "note": ""},
        library=owned_library,
        presentation=PRESENTATION,
    )

    assert form.is_valid(), form.errors
    assert form.cleaned_data["game"].pk == game.pk
    assert form.fields["game"].prepare_value(game.pk) == game.pk
